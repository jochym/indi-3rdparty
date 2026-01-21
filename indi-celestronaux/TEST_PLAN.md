# Test Suite Roadmap - indi-celestronaux

This plan outlines the step-by-step development of the system test suite for the Celestron AUX driver.

## Phase 1: Basic Communication & Handshake
- [x] Verify TCP connection (Driver -> Simulator)
- [x] Verify Firmware Version retrieval (GET_VER)
- [ ] Verify connection error handling (e.g., simulator not running)

## Phase 2: Motion Control (Functional Testing)
- [ ] **Slew (GOTO):** Verify high-speed and low-speed slewing to specific coordinates in both Alt-Az and RA-Dec modes.
- [ ] **Abort:** Verify that motion stops immediately when an Abort command is issued.
- [ ] **Manual Motion:** Verify NSWE manual slewing at different rates.
- [ ] **Tracking Rates:** Verify that setting different tracking rates (Sidereal, Lunar, Solar, Custom) correctly updates the motor controller rates.
- [ ] **Slew Limits:** Verify that the driver respects software slew limits and stops the mount.

## Phase 3: Status, Telemetry & Encoders
- [ ] **Position Polling:** Verify that encoder positions are correctly polled and converted to degrees/hours.
- [ ] **State Transitions:** Verify transitions between Idle, Slewing, and Tracking states.
- [ ] **Sync:** Verify that the Sync command correctly updates the driver's internal alignment model.

## Phase 4: Advanced Features & Imperfections
- [ ] **Backlash Compensation:** Simulate backlash in the simulator and verify the driver's compensation logic.
- [ ] **Periodic Error:** Simulate PE and verify tracking stability.
- [ ] **Alignment Subsystem:** Test multi-point alignment and pointing accuracy using the internal math plugins.

## Phase 5: Stability & Robustness
- [ ] **Long-duration Tracking:** Verify tracking consistency over several hours.
- [ ] **Reconnection:** Verify that the driver can gracefully recover from a lost TCP connection.
