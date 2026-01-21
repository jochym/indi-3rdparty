# Potential Issues

## Driver
1. **Firmware Info State**: The `Firmware Info` property remains in `IPS_IDLE` state after connection, even if populated. It is expected to transition to `IPS_OK` to indicate successful retrieval.
   - *Observation*: In `test_basic.py`, the property is received with state `Idle`.
   - *Location*: `celestronaux.cpp`, `Handshake` / `getVersions`. `FirmwareTP.setState(IPS_OK)` seems missing or not applied correctly.

2. **Firmware Version Retrieval**: The driver fails to retrieve firmware versions from the simulator (values remain "Unknown"), even though connection succeeds.
   - *Observation*: `Firmware Info` values are "Unknown".
   - *Context*: `Handshake` succeeds (Connection OK), but `getVersions` seems to fail silently (timeouts?).
