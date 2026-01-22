### 14. Predictive tracking inactive in simulation
- **Observation**: Even with multiple alignment points and significant induced tracking error, the driver's background tracking loop does not send periodic guide rate updates to the simulator.
- **Impact**: Tracking accuracy over long periods cannot be verified in the current simulation environment.
- **Location**: `celestronaux.cpp`, `TimerHit()` / `trackByRate()` loop.
