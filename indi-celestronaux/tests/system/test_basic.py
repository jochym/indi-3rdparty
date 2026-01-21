import unittest
import asyncio
import subprocess
import time
import os
import sys
from .indi_client import INDIClient

DEVICE_NAME = "Celestron AUX"
SIM_PORT = 2000
INDI_PORT = 7624
DRIVER_EXEC = os.path.abspath("build/indi_celestron_aux")
SIM_EXEC = os.path.abspath("indi-celestronaux/simulator/nse_simulator.py")


class TestSystem(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Start Simulator
        cmd_sim = [sys.executable, "-u", SIM_EXEC, "-t", "-p", str(SIM_PORT)]
        print(f"Starting simulator: {cmd_sim}")
        cls.sim_proc = subprocess.Popen(
            cmd_sim, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(1)

        # Start Indiserver
        if not os.path.exists(DRIVER_EXEC):
            raise RuntimeError(f"Driver executable not found at {DRIVER_EXEC}")

        cmd_indi = ["indiserver", "-v", "-p", str(INDI_PORT), DRIVER_EXEC]
        print(f"Starting indiserver: {cmd_indi}")
        cls.indi_proc = subprocess.Popen(
            cmd_indi, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(1)

    @classmethod
    def tearDownClass(cls):
        if cls.indi_proc:
            cls.indi_proc.terminate()
            cls.indi_proc.wait()
        if cls.sim_proc:
            cls.sim_proc.terminate()
            cls.sim_proc.wait()

    async def asyncSetUp(self):
        self.client = INDIClient(port=INDI_PORT)
        await self.client.connect()

    async def asyncTearDown(self):
        await self.client.disconnect()

    async def test_firmware_info(self):
        """
        Verifies that the driver connects to the simulator and retrieves firmware info.
        """
        # 1. Configure Connection Mode to TCP
        # Wait for definition
        prop = await self.client.wait_for_property(DEVICE_NAME, "CONNECTION_MODE")
        # print(f"CONNECTION_MODE: {prop}")

        # Set TCP
        # Standard INDI switch name for TCP is usually "CONNECTION_TCP"
        await self.client.set_switch(DEVICE_NAME, "CONNECTION_MODE", ["CONNECTION_TCP"])

        # 2. Configure Host/Port
        await self.client.set_text(
            DEVICE_NAME, "DEVICE_ADDRESS", {"PORT": "2000", "ADDRESS": "localhost"}
        )

        # 3. Connect
        await self.client.set_switch(DEVICE_NAME, "CONNECTION", ["CONNECT"])

        # 4. Wait for Connection Success
        # It might transition Idle -> Busy -> Ok/Alert
        # We wait for final state
        while True:
            prop = await self.client.wait_for_property(DEVICE_NAME, "CONNECTION")
            print(f"CONNECTION state: {prop['state']}")
            if prop["state"] in ["Ok", "Alert"]:
                break

        if prop["state"] == "Alert":
            # Print messages if any
            # We don't capture messages yet in client
            pass

        assert prop["state"] == "Ok"

        # 5. Wait for Firmware Info
        # The driver reads this during Handshake
        start_time = time.time()
        while time.time() - start_time < 15:
            # Check cache first
            prop = self.client.get_property(DEVICE_NAME, "Firmware Info")
            if prop:
                print(f"Firmware Info state: {prop['state']}")
                # If we have some values, we consider it "received"
                if any(
                    v.strip() != "Unknown" and v.strip() != ""
                    for v in prop["values"].values()
                ):
                    break
            else:
                print("Firmware Info not in cache yet")

            # Wait for update
            try:
                prop = await self.client.wait_for_property(
                    DEVICE_NAME, "Firmware Info", timeout=2
                )
                print(f"Received Firmware Info update: {prop['state']}")
                if any(
                    v.strip() != "Unknown" and v.strip() != ""
                    for v in prop["values"].values()
                ):
                    break
            except asyncio.TimeoutError:
                print("Timeout waiting for Firmware Info update")
                pass

        assert prop
        print("Firmware Info:", prop["values"])

        # Check values
        def get_val(name):
            return prop["values"].get(name, "").strip()

        assert "7.11" in get_val("Ra/AZM version")
        assert "7.11" in get_val("Dec/ALT version")
        assert "5.28" in get_val("HC version")
