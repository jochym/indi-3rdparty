# Changelog - indi-celestronaux System Tests

## [2026-01-22 00:45] - Phase 5 Progress: Tracking Loop Observed
- Implemented `test_predictive_tracking` to monitor background tracking updates.
- Documented that predictive tracking appears inactive or highly suppressed in the current Alt-Az simulation environment (Issue 14 in `ISSUES.md`).
- Increased test timeouts and polling frequencies to ensure thorough observation of driver behavior.

## [2026-01-22 00:25] - Phase 4b Progress: Anti-backlash Logic Verified
- Implemented `test_approach_direction` to verify the driver's anti-backlash overshoot logic.
- Verified that enabling `APPROACH_CONSTANT_OFFSET` results in successful GOTO motion.
- Improved `wait_for_motion` helper for more precise tracking of physical movements.

## [2026-01-22 00:05] - Phase 4a Progress: Multi-star Alignment Verified
- Implemented `test_alignment_multistar` to verify multi-point alignment database management.
- Verified that the alignment subsystem is correctly activated and performs coordinate transformations during physical motion.
- Confirmed that `ALIGNMENT_POINTSET_SIZE` correctly tracks added points.

## [2026-01-21 23:45] - Phase 4b Progress: Homing Test Verified
- Verified `HOME` all command and automated return to zero position.
- Updated simulator (`nse_telescope.py`) to correctly implement `MC_LEVEL_DONE` (0x12) and `MC_SEEK_DONE` (0x18).
- Updated simulator to perform physical motion towards zero during homing.
- Handled azimuth wrap-around and early state transition in `test_homing`.

## [2026-01-21 23:15] - Phase 5 Start: Stability & Robustness
- **Reconnection Test:** Implemented `test_reconnection` to verify recovery from lost TCP connection. Observed that the driver takes a significant amount of time (over 65s) to detect connection loss.
- **Manual Motion:** Continuing to investigate why NSWE manual motion commands are reaching the driver but not resulting in physical motion in the simulator.

## [2026-01-21 14:45] - Phase 4a Completion: Alignment Subsystem Verified
- **Resolved GOTO Issue (Issue 13):** Confirmed that RA/Dec GOTO works perfectly after a valid `Sync`. The earlier failure was caused by using `set_text` for Number properties and missing Alignment Plugin selection.
- Verified coordinate transformation accuracy: relative RA/Dec moves are highly precise after 1-star alignment.
- Updated `INDIClient` to use `set_number` for Number properties and `set_switch` correctly.
- Discovered and documented `EQUATORIAL_EOD_COORD` transitioning to `Idle` instead of `Ok` after slew.
- Improved test robustness by explicitly clearing alignment points and setting Time/Location.

## [2026-01-21 14:15] - Phase 4a Progress: Infrastructure Fixes

## [2026-01-21 12:45] - Phase 3 Completion: Status, Telemetry & Encoders
