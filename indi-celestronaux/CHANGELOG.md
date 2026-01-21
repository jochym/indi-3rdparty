# Changelog - indi-celestronaux System Tests

## [2026-01-21 14:45] - Phase 4a Completion: Alignment Subsystem Verified
- **Resolved GOTO Issue (Issue 13):** Confirmed that RA/Dec GOTO works perfectly after a valid `Sync`. The earlier failure was caused by using `set_text` for Number properties and missing Alignment Plugin selection.
- Verified coordinate transformation accuracy: relative RA/Dec moves are highly precise after 1-star alignment.
- Updated `INDIClient` to use `set_number` for Number properties and `set_switch` correctly.
- Discovered and documented `EQUATORIAL_EOD_COORD` transitioning to `Idle` instead of `Ok` after slew.
- Improved test robustness by explicitly clearing alignment points and setting Time/Location.

## [2026-01-21 14:15] - Phase 4a Progress: Infrastructure Fixes

## [2026-01-21 12:45] - Phase 3 Completion: Status, Telemetry & Encoders
