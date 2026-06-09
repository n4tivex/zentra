# ZENTRA Operational Runbook

## Market Holiday Or Calendar Override

- Source of truth: `zentra/market_calendar.json`.
- Emergency same-day override: set `IDX_MARKET_HOLIDAYS=YYYY-MM-DD[,YYYY-MM-DD]`.
- Validate changes with `python scripts/check_market_calendar.py --require-next-year`.
- A closed market run records `calendar_reason` as `weekend`, `official_holiday`, or `calendar_override`.

## Partial Fetch

- Check `run_logs.fetched_count`, `cached_count`, `missing_count`, `failure_count`, `missing_tickers`, and `failed_fetch_tickers`.
- `PARTIAL` means the scan completed with degraded coverage.
- `FAILED` means coverage dropped below the enforced threshold or all provider/cache paths failed.
- Re-run only after confirming the provider has recovered or cache data is valid.

## Market Data Pending Or Provider Stale

- `market_data_pending`: closing scan expected today's candle, but the provider still shows the previous trading day.
- `provider_stale`: latest available candle is older than the expected trading day.
- Do not classify either case as a holiday. Wait for provider recovery, then rerun the same slot manually if needed.

## DB Failure

- `db_insert`, `db_update`, `db_delete`, `db_conflict`, and `db_write` are operational failures.
- `run_logs.update_run()` failures fail the job because final state persistence is part of the run outcome.
- Check Supabase table health and the latest migration status before rerunning.

## Duplicate Trigger

- Runs are locked by `mode:run_date:run_slot`.
- A duplicate trigger exits cleanly with `failure_category=duplicate_run_lock`.
- If a lock remains after a crashed worker, inspect `run_locks` and release only the stale row for that slot.

## cronjob.org Triggers

- Keep existing morning and closing jobs active.

## Telegram Failure

- Public signal delivery failures are counted in `telegram_failed`.
- Admin alerts are best-effort and recorded with `admin_alert_sent`.
- A scan with message delivery failure is not recorded as a clean success.

## Preflight

- Offline validation: `python scripts/preflight.py --skip-network`.
- Production validation: `python scripts/preflight.py`.
- Production preflight checks env vars, calendar loading, Supabase reachability, and Telegram credentials.
