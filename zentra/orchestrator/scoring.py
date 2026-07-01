"""ZENTRA Orchestrator — ticker processing, exit handling, and buy scoring."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import structlog

from zentra.analysis.indicators import TechnicalIndicators
from zentra.analysis.scorer import SignalScorer
from zentra.config import SignalResult, SignalType
from zentra.data.schema import validate_indicator_schema, validate_ohlcv_schema
from zentra.data.validator import DataValidator
from zentra.db.ohlcv_repo import OHLCVRepo
from zentra.db.signals_repo import SignalsRepo
from zentra.exceptions import (
    CalculationError,
    DataIntegrityError,
    InsufficientDataError,
    StaleDataError,
)
from zentra.narrative.generator import NarrativeGenerator
from zentra.orchestrator.core import ZENTRAOrchestrator

log = structlog.get_logger()


def _process_ticker(
    self,
    *,
    ticker: str,
    all_data: dict[str, pd.DataFrame],
    validator: DataValidator,
    indicators: TechnicalIndicators,
    scorer: SignalScorer,
    narrative_gen: NarrativeGenerator,
    signals_repo: SignalsRepo | None,
    ohlcv_repo: OHLCVRepo | None,
    ticker_log,
) -> SignalResult | dict[str, str] | None:
    """Process a single ticker through the full pipeline.

    Returns:
        SignalResult on success,
        dict with skip/fail info,
        None if nothing to report.
    """
    try:
        # 1. Get raw data
        df = all_data.get(ticker)
        if df is None or df.empty:
            return {"ticker": ticker, "status": "failed", "reason": "no_data"}

        # 2. P1-8: Handle partial candle for morning mode
        df = self._handle_partial_candle(df, ticker_log)
        if df.empty:
            return {"ticker": ticker, "status": "failed", "reason": "empty_after_candle_drop"}

        # 3. Validate
        validation = validator.validate(ticker, df)
        if not validation.is_valid:
            ticker_log.warning("validation_failed", phase="validate", errors=validation.errors)
            return {"ticker": ticker, "status": "failed", "reason": f"validation: {validation.errors[0]}"}

        for warning in validation.warnings:
            ticker_log.warning("validation_warning", phase="validate", warning=warning)

        # 4. Use cleaned DataFrame (P0-6: validator is source of truth for cleaning)
        df_clean = validation.cleaned_df if validation.cleaned_df is not None else df

        # 5. Validate OHLCV schema contract (P1-10)
        try:
            validate_ohlcv_schema(df_clean, ticker)
        except DataIntegrityError as e:
            ticker_log.warning("ohlcv_schema_failed", phase="validate", error=str(e))
            return {"ticker": ticker, "status": "skipped", "reason": "schema_violation"}

        # 6. Persist to cache
        if ohlcv_repo and not self._dry_run:
            try:
                ohlcv_repo.upsert_batch(ticker, df_clean)
            except Exception as e:
                ticker_log.warning("cache_upsert_failed", phase="persist", error=str(e))

        # 7. Enrich with indicators
        df_ind = indicators.compute_all(df_clean)

        # 8. Validate indicator schema (P1-10)
        try:
            validate_indicator_schema(df_ind, ticker)
        except DataIntegrityError as e:
            ticker_log.warning("indicator_schema_failed", phase="enrich", error=str(e))
            return {"ticker": ticker, "status": "skipped", "reason": "indicator_schema_violation"}

        # 9. Check for active signal (EXIT path or skip on WATCH)
        active = signals_repo.get_active_signal(ticker, signal_type=None) if signals_repo else None
        if active:
            if active.get("signal_type") == "BUY":
                return self._handle_exit(
                    ticker=ticker,
                    df_ind=df_ind,
                    active=active,
                    scorer=scorer,
                    narrative_gen=narrative_gen,
                    ticker_log=ticker_log,
                )
            # WATCH active — skip, avoid duplicate until it expires
            return None

        # 10. Score for BUY
        return self._handle_buy_scoring(
            ticker=ticker,
            df_ind=df_ind,
            scorer=scorer,
            narrative_gen=narrative_gen,
            ticker_log=ticker_log,
        )

    except (CalculationError, InsufficientDataError, StaleDataError) as e:
        ticker_log.warning("ticker_processing_error", phase="process", error=str(e))
        return {"ticker": ticker, "status": "failed", "reason": str(e)}
    except Exception as e:
        ticker_log.error("ticker_unexpected_error", phase="process", error=str(e))
        return {"ticker": ticker, "status": "failed", "reason": f"unexpected: {e}"}


def _handle_exit(
    self,
    *,
    ticker: str,
    df_ind,
    active: dict,
    scorer: SignalScorer,
    narrative_gen: NarrativeGenerator,
    ticker_log,
) -> SignalResult | None:
    """Handle EXIT check for a ticker with an active signal."""
    created_str = active.get("created_at", "")
    if created_str:
        created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        days_held = (datetime.now(tz=UTC) - created_dt).days
    else:
        days_held = 99

    exit_result = scorer.check_exit(ticker, df_ind, active, days_held=days_held)
    if exit_result:
        exit_result.narrative = narrative_gen.generate_exit(exit_result, active)
        ticker_log.info(
            "exit_signal_detected",
            phase="score",
            exit_status=exit_result.exit_status.value if exit_result.exit_status else "unknown",
            reasons=exit_result.exit_reasons,
        )
        return exit_result
    return None


def _handle_buy_scoring(
    self,
    *,
    ticker: str,
    df_ind,
    scorer: SignalScorer,
    narrative_gen: NarrativeGenerator,
    ticker_log,
) -> SignalResult | None:
    """Score a ticker for BUY/WATCH signal."""
    buy_result = scorer.score_buy(ticker, df_ind)
    ticker_log.info(
        "scored",
        phase="score",
        score=buy_result.score,
        type=buy_result.signal_type.value,
        confluence=buy_result.confluence_count,
    )

    if buy_result.signal_type in (SignalType.BUY, SignalType.WATCH):
        buy_result.narrative = narrative_gen.generate_buy(buy_result)
        return buy_result
    return None


ZENTRAOrchestrator._process_ticker = _process_ticker
ZENTRAOrchestrator._handle_exit = _handle_exit
ZENTRAOrchestrator._handle_buy_scoring = _handle_buy_scoring
