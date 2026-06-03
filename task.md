# ZENTRA Change Task

## Objective

Implement all requested changes in a single ordered execution pass, without stopping midway, without asking the user for clarification during execution, and without leaving any requested item partially done.

Success means:
- All requested business-rule changes are implemented.
- All naming corrections are applied.
- The signal cadence is expanded to 3 deliveries per trading day.
- The codebase passes a full verification run after the changes.
- Operational steps for the user are documented at the end.

## Scope

This task covers:
- Stop loss cap change from 8% to 5%.
- Buy ranking rule change so RSI is the primary ranking trigger, and MACD becomes confirmation.
- Stock name corrections for OASA and RMKE.
- Full review of all IDX stock names used by the project to confirm the remaining mappings are correct.
- Moving average changes from MA 20/50 to MA 9/21.
- Volume rule change to require at least 5 days of lookback/confirmation.
- Adding a midday signal run at 13:00 WIB so signals are sent 3 times per day.
- Full testing and verification after implementation.

## Assumptions

- “Presentase stop loss jadi Max 5%” means the hard stop-loss cap must be reduced from 8% to 5% everywhere the risk model enforces it.
- “Level buy ranking pakai RSI kalo udah crossing udah buy, macd jadi konfirmasi rsi” means RSI crossover/state must drive the ranking/decision first, while MACD is only a confirming filter and must not override an RSI-led buy setup.
- “MA diganti, ma 20 jadi 9, ma 50 jadi 21” means the strategy should switch to EMA/SMA windows 9 and 21 consistently across indicators, scoring, narrative, backtest, and tests where those windows are referenced.
- “Volume minimal 5 hari kebelakang” means volume confirmation should use at least the last 5 trading days, not fewer.
- The midday run should be treated as a first-class scan slot, not a manual workaround.
- The existing GitHub Actions setup is triggered externally by cronjob.org via repository dispatch, so the cronjob.org trigger configuration must be updated as part of the task handoff.

## Phase 1: Inventory and impact map

1. Identify every file that currently depends on:
   - stop-loss percentage
   - EMA/MA windows
   - RSI/MACD scoring logic
   - volume confirmation logic
   - ticker display names
   - run modes / schedule slots
   - workflow event names
2. Confirm whether the midday run needs:
   - a new GitHub Actions workflow file
   - a new repository dispatch event
   - changes to run-log slot handling
   - changes to duplicate-lock keys
3. Confirm all tests that will need updates.

Verification:
- Produce a complete file list of impacted code paths before editing.
- Do not start code changes until the impact map is complete.

## Phase 2: Correct stock names

1. Fix the known incorrect display names:
   - `OASA` -> `Maharaksa Biru Energi`
   - `RMKE` -> `RMK Energy`
2. Review every other stock name mapping used in the project against IDX sources and confirm they are correct.
3. Update any tests or narratives that depend on the old names.

Verification:
- The ticker-to-name mapping used in messages and narratives matches the intended names.
- No other ticker names remain incorrect after the IDX review.

## Phase 3: Update strategy indicators

1. Replace MA 20 with MA 9 where the strategy currently uses the faster moving average.
2. Replace MA 50 with MA 21 where the strategy currently uses the slower moving average.
3. Update scoring logic so RSI is the primary buy-ranking signal.
4. Make MACD a confirmation signal for RSI instead of the primary driver.
5. Ensure the change is reflected consistently in:
   - indicator calculation
   - schema validation
   - scoring classification
   - narratives
   - backtest logic
   - tests

Verification:
- Indicator columns, scoring, and tests all refer to the same MA windows.
- A setup with RSI crossing should rank as BUY when the MACD confirmation condition is satisfied.
- MACD alone should not promote a weak RSI setup into a BUY.

## Phase 4: Adjust risk and volume rules

1. Reduce the maximum stop loss cap to 5%.
2. Change volume confirmation to require at least 5 trading days of lookback/confirmation.
3. Update any calculations, validations, and message text that expose these rules.

Verification:
- Risk calculations never exceed the 5% stop-loss cap.
- Volume-related scoring or gating uses a 5-day minimum.
- Existing risk and validator tests are updated to the new thresholds.

## Phase 5: Add midday scan slot

1. Add a third scan run at 13:00 WIB after session 1 ends.
2. Make the scan slot explicit in the code path so morning, midday, and closing are distinct runs.
3. Ensure lock keys and run logs stay idempotent across all three slots.
4. Add or update the GitHub Actions workflow needed for the midday signal path.
5. Update cronjob.org configuration expectations so it triggers the new midday run in addition to the existing runs.

Verification:
- There are exactly 3 scheduled signal deliveries per trading day.
- Duplicate-trigger protection still works per slot.
- Midday runs do not collide with morning or closing runs.

## Phase 6: Tests and verification

1. Update unit tests for:
   - stop-loss cap
   - RSI-led buy ranking
   - MACD confirmation behavior
   - MA 9/21
   - 5-day volume rule
   - corrected ticker names
   - midday scheduling / slot handling
2. Update integration tests for:
   - run-lock behavior across three daily slots
   - signal generation flow across the new rules
   - Telegram formatting if wording changes
3. Run the full test suite.
4. Run the project preflight checks.
5. Fix any failures before considering the task complete.

Verification:
- `pytest` passes.
- Preflight passes.
- No new lint or runtime errors are introduced by the changes.

## Phase 7: Final review

1. Review the diff for completeness against this task.
2. Confirm nothing requested was skipped.
3. Confirm the implementation is internally consistent with the updated strategy rules.
4. Confirm the midday operational change is documented for the user.

Verification:
- Every requested item in this task exists in the final diff or is explicitly documented as unchanged with a reason.

## Post-completion steps for the user

After the code changes are finished:

1. Update cronjob.org so it triggers the new midday repository dispatch event at 13:00 WIB.
2. Keep the existing morning and closing triggers active.
3. Deploy or merge the updated code and workflow files.
4. Run the production preflight again against the target environment.
5. Watch the next 1-2 trading days of run logs to confirm all 3 daily slots behave correctly.

## Non-negotiables

- Do not stop halfway through.
- Do not ask the user for extra clarification during execution.
- Do not leave any requested change partially applied.
- Do not skip full verification after implementation.
- Continue until every item above is complete.
