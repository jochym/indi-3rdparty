# Changelog - indi-celestronaux System Tests

## [2026-01-21 12:45] - Phase 3 Completion: Status, Telemetry & Encoders
- Verified encoder accuracy: azimuth degree changes correspond correctly to raw encoder step changes ($2^{24}$ steps per $360^\circ$).
- Verified Sync command acceptance: driver correctly transitions `EQUATORIAL_EOD_COORD` to `Ok` state after Sync, although reported values might differ due to internal transformations.
- Documented internal coordinate system offsets and Sync behavior in `POTENTIAL_ISSUES.md`.
- Phase 3 roadmap items completed.
- Implemented `test_motion_altaz` and `test_abort_altaz`.
- Added `wait_for_state`, `wait_for_condition`, and `wait_for_any_property` to `INDIClient` for more robust testing.
- Improved `connect_to_sim` to wait for coordinate properties and enable debug logging.
- Encountered and investigating issue with `HORIZONTAL_COORD` not transitioning to `Busy` state upon GOTO.
