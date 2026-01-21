# Registry of Potential Driver Issues

This file tracks potential issues discovered in the driver during testing. 
The driver is currently treated as a "golden standard" and should not be modified.

## Potential Issues
1. **Firmware Info remains Idle:** During system tests, the driver connects to the simulator, but the "Firmware Info" property never transitions to "Ok". It remains "Idle". Values are correctly populated, but the property state is not updated by the driver.
2. **Missing Firmware Versions in Simulator:** The simulator returns empty responses for GPS (0xB0), WiFi (0xB5), and BAT (0xB6) firmware version requests, leading to "Unknown" values in the driver.
3. **Property naming mismatch:** The test expected `DEVICE_PORT` but the driver uses `DEVICE_ADDRESS`. (This might be a test issue rather than a driver issue, but noted here for record).
