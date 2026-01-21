# Changelog - indi-celestronaux System Tests

## [2026-01-21 12:10] - Phase 2 Progress: Motion Control
- Implemented `test_motion_altaz` and `test_abort_altaz`.
- Added `wait_for_state`, `wait_for_condition`, and `wait_for_any_property` to `INDIClient` for more robust testing.
- Improved `connect_to_sim` to wait for coordinate properties and enable debug logging.
- Encountered and investigating issue with `HORIZONTAL_COORD` not transitioning to `Busy` state upon GOTO.
