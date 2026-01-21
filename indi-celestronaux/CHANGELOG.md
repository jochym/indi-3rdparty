# Changelog - indi-celestronaux System Tests

## [2026-01-21 14:15] - Phase 4a Completion: Alignment Subsystem
- Verified 1-star alignment: `Sync` command is accepted and correctly updates `EQUATORIAL_EOD_COORD` state.
- Identified critical issue where RA/Dec GOTO is ignored even after Sync (logged in `POTENTIAL_ISSUES.md`).
- Established robust `INDIClient` with support for partial vector updates and XML stream handling.
- Fixed driver build error (typo in `proportionalTerm`).
- Improved test environment stability: process cleanup and binary restoration.

## [2026-01-21 12:45] - Phase 3 Completion: Status, Telemetry & Encoders
