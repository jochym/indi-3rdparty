# Issues Registry - indi-celestronaux

This file tracks issues discovered during the development and testing of the Celestron AUX driver and its system tests.

## Status: Resolved

### 1. Firmware Version Retrieval Failure
- **Issue**: Driver failed to retrieve firmware versions (values remained "Unknown").
- **Resolution**: Identified two causes:
  1. Test was using incorrect property `DEVICE_PORT` instead of `DEVICE_ADDRESS`, so driver never actually connected to simulator.
  2. Simulator was not responding correctly to `GET_VER` (0xFE).
- **Fix**: Updated `test_basic.py` and simulator code. Handshake now succeeds.

### 2. Simulator crash on 2-byte guiderate
- **Issue**: Simulator crashed when receiving `MC_SET_POS_GUIDERATE` with 2-byte payload.
- **Resolution**: Updated `nse_telescope.py` to handle variable length payloads (padding to 3 bytes if needed).

### 3. Driver Source Typo (Build Failure)
- **Issue**: Typo in `celestronaux.cpp` (`proportionalTerm` instead of `propotionalTerm`) prevented building against modern INDI libraries.
- **Resolution**: Fixed the typo in `celestronaux.cpp`.

### 4. GOTO RA/Dec ignored after Sync
- **Issue**: Commands sent to `EQUATORIAL_EOD_COORD` did not initiate motion.
- **Resolution**: Identified that the driver ignores celestial commands until an alignment point is established via `Sync`. Also ensured the client uses `<newNumberVector>` instead of `<newTextVector>` for coordinates.

## Status: Open / Potential Driver Issues

### 5. Firmware Info State stuck at Idle
- **Observation**: `Firmware Info` property values are updated correctly, but the property state remains `IPS_IDLE`.
- **Impact**: Clients might wait indefinitely for an `IPS_OK` state that never arrives.
- **Location**: `celestronaux.cpp`, `updateProperties()`.

### 6. HORIZONTAL_COORD State stuck at Idle
- **Observation**: Even during active tracking or slewing, `HORIZONTAL_COORD` state remains `IPS_IDLE`.
- **Impact**: Makes it difficult for clients to detect motion completion via this property.

### 7. EQUATORIAL_EOD_COORD state transitions to Idle after Slew
- **Observation**: Upon completion of a GOTO, the state transitions from `Busy` to `Idle` instead of `Ok`.

### 8. Default Mount Type Mismatch
- **Observation**: Driver defaults to `EQ_GEM` internally (visible in `TELESCOPE_MOUNT_TYPE` property) even when connecting to an Alt-Az simulator (Evolution). This forces unnecessary coordinate transformations.

### 9. ON_COORD_SET Multi-switch Issue
- **Observation**: `ON_COORD_SET` can have multiple switches (`TRACK`, `SLEW`, `SYNC`) set to `On` simultaneously if the client is not careful. The driver does not seem to enforce 1-of-many rule internally upon receiving updates.

### 10. Sync Command Time Dependency
- **Observation**: Issuing a `Sync` command results in unexpected RA/Dec values if the driver's `TIME_UTC` is not explicitly set to match the test's context. The driver uses the system OS clock for transformations.

### 11. Encoder to Degree Conversion Offset
- **Observation**: There is a constant offset between raw encoder steps and reported `HORIZONTAL_COORD` degrees. While the scale ($2^{24}$ steps/rev) is correct, the zero point is arbitrary until aligned.

### 12. Extremely slow GOTO speed in simulation
- **Observation**: Slew speeds in simulation are very low, making long-distance GOTOs time out in tests.

### 13. Manual Motion (NSWE) buttons not functional
- **Observation**: Commands sent to `TELESCOPE_MOTION_NS` and `TELESCOPE_MOTION_WE` are ignored.
- **Cause**: The driver implements `MoveNS()` and `MoveWE()` but does not set the `TELESCOPE_CAN_SLEW` capability bit in its constructor. As a result, the base `INDI::Telescope` class does not define these properties or process updates for them.
- **Location**: `celestronaux.cpp`, Constructor.

### 14. Predictive tracking inactive in simulation
- **Observation**: Even with multiple alignment points and significant induced tracking error, the driver's background tracking loop does not send periodic guide rate updates to the simulator.
- **Impact**: Tracking accuracy over long periods cannot be verified in the current simulation environment.
- **Location**: `celestronaux.cpp`, `TimerHit()` / `trackByRate()` loop.
