import pytest
import asyncio
import subprocess
import time
import os
import sys
from .indi_client import INDIClient

SIM_PORT = 2000
INDI_PORT = 7624
DRIVER_EXEC = os.path.abspath("build/indi_celestron_aux")
SIM_EXEC = os.path.abspath("indi-celestronaux/simulator/nse_simulator.py")


@pytest.fixture(scope="session")
def simulator():
    """Launches the simulator."""
    # Ensure simulator is executable or run with python
    cmd = [sys.executable, "-u", SIM_EXEC, "-t", "-p", str(SIM_PORT)]
    print(f"Starting simulator: {cmd}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(1)  # Wait for startup
    yield proc
    proc.terminate()
    proc.wait()


@pytest.fixture(scope="session")
def indiserver(simulator):
    """Launches indiserver with the driver."""
    # Check if driver exists
    if not os.path.exists(DRIVER_EXEC):
        pytest.fail(
            f"Driver executable not found at {DRIVER_EXEC}. Please build first."
        )

    # Run indiserver
    # We need to tell the driver where to connect (localhost:2000)
    # The driver uses connection plugins. Default is usually Serial.
    # We might need to start it and then configure it via properties?
    # Or pass arguments? indi_celestron_aux doesn't seem to take args for connection.
    # It defaults to Serial 19200 or TCP.
    # We will configure it via INDI client in the test.

    cmd = ["indiserver", "-v", "-p", str(INDI_PORT), DRIVER_EXEC]
    print(f"Starting indiserver: {cmd}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(1)
    yield proc
    proc.terminate()
    proc.wait()
