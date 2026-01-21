# NexStar AUX Simulator

This is an advanced simulator for Celestron AUX-protocol mounts. It emulates the behavior of Motor Controllers (MC), Hand Controller (HC), GPS, and other devices on the AUX bus.

## Features

- **Physical Model**: Simulates motion with backlash, periodic error (PE), cone error, and non-perpendicularity.
- **Atmospheric Refraction**: Optional simulation of atmospheric refraction.
- **Multiple Interfaces**:
  - **Headless**: Minimal dependencies, suitable for automated tests.
  - **TUI (Textual)**: Rich terminal user interface with real-time telemetry.
  - **Web Console**: 3D visualization of the mount using Three.js, including a schematic sky view.
- **Stellarium Support**: Built-in server for Stellarium telescope control protocol.
- **Configurable**: All parameters can be tuned via `config.toml`.

## Installation

The simulator requires Python 3.11+.

### Minimal (for basic testing)
```bash
pip install ephem
```

### Full (with TUI and Web Console)
```bash
pip install ephem textual fastapi uvicorn websockets numpy scipy
```

## Usage

Run the simulator from the `simulator/` directory:

```bash
# Headless mode (minimal dependencies)
python3 nse_simulator.py -t

# TUI mode (requires 'textual')
python3 nse_simulator.py

# Web mode (requires 'fastapi', 'uvicorn', 'websockets')
python3 nse_simulator.py --web
```

### Command Line Arguments

- `-t`, `--text`: Use headless mode (no TUI).
- `-p PORT`, `--port PORT`: AUX bus TCP port (default: 2000).
- `-s PORT`, `--stellarium PORT`: Stellarium TCP port (default: 10001).
- `--web`: Enable 3D Web Console (default: http://127.0.0.1:8080).
- `--perfect`: Disable all mechanical imperfections (backlash, PE, etc.).
- `-d`, `--debug`: Enable debug logging.

## Configuration

You can override default settings by creating a `config.toml` file in the simulator directory. See `config.default.toml` for available options.

### Example `config.toml`
```toml
[observer]
latitude = 52.2297
longitude = 21.0122
elevation = 100

[simulator.imperfections]
backlash_steps = 200
periodic_error_arcsec = 15.0
```
