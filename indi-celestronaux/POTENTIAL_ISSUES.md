# Registry of Potential Driver Issues

This file tracks potential issues discovered in the driver during testing. 
The driver is currently treated as a "golden standard" and should not be modified.

## Potential Issues
1. **Firmware Info remains Idle:** During system tests, the driver connects to the simulator, but the "Firmware Info" property never transitions to "Ok". It remains "Idle". Values are correctly populated, but the property state is not updated by the driver.
2. **Missing Firmware Versions in Simulator:** The simulator returns empty responses for GPS (0xB0), WiFi (0xB5), and BAT (0xB6) firmware version requests, leading to "Unknown" values in the driver.
3. **Property naming mismatch:** The test expected `DEVICE_PORT` but the driver uses `DEVICE_ADDRESS`. (This might be a test issue rather than a driver issue, but noted here for record).
4. **HORIZONTAL_COORD remains Idle during Tracking:** Even when tracking is active and AZ/ALT values are changing, the `HORIZONTAL_COORD` property state remains `Idle`.
5. **EQUATORIAL_EOD_COORD state update:** While `EQUATORIAL_EOD_COORD` correctly shows `Ok` when updated, it doesn't seem to transition to `Busy` during a slew initiated via `HORIZONTAL_COORD`.
6. **Default Mount Type:** Driver defaults to `EQ_GEM` when connecting to the simulator, even if it's emulating an Evolution mount (which is Alt-Az).
7. **GOTO via EQUATORIAL_EOD_COORD ignored without Alignment:** Commands sent to `EQUATORIAL_EOD_COORD` are ignored until a `Sync` command establishes an alignment point.
8. **ON_COORD_SET multi-switch issue:** `ON_COORD_SET` can have multiple switches `On` at the same time if not handled carefully by the client, which might confuse the driver.
9. **Simulator crash on 2-byte guiderate:** The simulator crashed when receiving a 2-byte data payload for guiderate commands, while expecting 3 bytes. (Fixed in simulator code).
10. **Extremely slow GOTO speed in simulation:** Motion towards target Az=100 from Az=1.8 takes more than 30 seconds at default rates.
