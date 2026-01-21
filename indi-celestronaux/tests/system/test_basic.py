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

    async def connect_to_sim(self):
        """Helper to connect the driver to the simulator."""
        await self.client.wait_for_property(DEVICE_NAME, "CONNECTION_MODE")
        await self.client.set_switch(DEVICE_NAME, "CONNECTION_MODE", ["CONNECTION_TCP"])
        await self.client.set_text(
            DEVICE_NAME, "DEVICE_ADDRESS", {"PORT": "2000", "ADDRESS": "localhost"}
        )
        await self.client.set_switch(DEVICE_NAME, "CONNECTION", ["CONNECT"])
        await self.client.wait_for_state(DEVICE_NAME, "CONNECTION", "Ok")

        # Wait for the driver to define coordinates after handshake
        print("Waiting for coordinate properties...")
        try:
            await self.client.wait_for_any_property(
                DEVICE_NAME,
                lambda d, n, p: n in ["HORIZONTAL_COORD", "EQUATORIAL_EOD_COORD"],
                timeout=10,
            )
        except Exception as e:
            print(f"Warning: Coordinate properties not seen: {e}")

        # Ensure Tracking is ON
        print("Enabling tracking...")
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_TRACK_STATE", ["TRACK_ON"])
        await asyncio.sleep(1)

    async def sync_to_current(self):
        """Helper to sync the driver to current simulator position to establish alignment."""
        prop = self.client.get_property(DEVICE_NAME, "EQUATORIAL_EOD_COORD")
        ra = prop["values"]["RA"].strip()
        dec = prop["values"]["DEC"].strip()

        print(f"Syncing to RA={ra}, Dec={dec}")
        # Ensure ON_COORD_SET is SYNC
        await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["SYNC"])
        await self.client.set_text(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD", {"RA": ra, "DEC": dec}
        )
        await asyncio.sleep(2)
        # Switch back to SLEW for GOTO
        await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["SLEW"])
        await asyncio.sleep(1)

        # Ensure Tracking is ON
        print("Enabling tracking...")
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_TRACK_STATE", ["TRACK_ON"])
        await asyncio.sleep(1)

        # Ensure Tracking is ON
        print("Enabling tracking...")
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_TRACK_STATE", ["TRACK_ON"])
        await asyncio.sleep(1)

    async def sync_to_current(self):
        """Helper to sync the driver to current simulator position to establish alignment."""
        prop = self.client.get_property(DEVICE_NAME, "EQUATORIAL_EOD_COORD")
        ra = prop["values"]["RA"].strip()
        dec = prop["values"]["DEC"].strip()

        print(f"Syncing to RA={ra}, Dec={dec}")
        # Ensure ON_COORD_SET is SYNC, others OFF
        await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["SYNC"])
        await self.client.set_text(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD", {"RA": ra, "DEC": dec}
        )
        await asyncio.sleep(3)
        # Switch back to SLEW for GOTO, others OFF
        await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["SLEW"])
        await asyncio.sleep(1)

    async def test_firmware_info(self):
        """
        Verifies that the driver connects to the simulator and retrieves firmware info.
        """
        await self.connect_to_sim()

        # 5. Wait for Firmware Info
        # The driver reads this during Handshake
        prop = None
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

    async def wait_for_motion(self, property_name, field, target_value, timeout=60):
        """Helper to wait for motion towards a target since state might stay Idle."""
        start_prop = self.client.get_property(DEVICE_NAME, property_name)
        start_val = float(start_prop["values"][field].strip())

        print(
            f"Waiting for motion on {property_name}.{field} from {start_val} towards {target_value}..."
        )

        end_time = asyncio.get_event_loop().time() + timeout
        last_val = start_val
        while asyncio.get_event_loop().time() < end_time:
            await asyncio.sleep(2)
            curr_prop = self.client.get_property(DEVICE_NAME, property_name)
            curr_val = float(curr_prop["values"][field].strip())

            print(
                f"Motion check: {property_name}.{field} = {curr_val} (diff from start: {curr_val - start_val:.4f})"
            )

            # If we moved at least 0.05 degree from last check, we confirm motion
            if abs(curr_val - last_val) > 0.05:
                print("Motion confirmed.")
                return curr_prop

            # If we are close to target, we are done
            if abs(curr_val - target_value) < 0.5:
                return curr_prop

            last_val = curr_val

        raise TimeoutError(f"Motion timeout for {property_name}.{field}")

    async def test_motion_altaz(self):
        """
        Verifies Alt-Az slewing initiation.
        """
        await self.connect_to_sim()
        await self.sync_to_current()

        # 1. Set Alt-Az coordinates
        target_az = 100.0
        target_alt = 45.0

        print(f"Slewing to Az={target_az}, Alt={target_alt}")
        await self.client.set_text(
            DEVICE_NAME,
            "HORIZONTAL_COORD",
            {"AZ": str(target_az), "ALT": str(target_alt)},
        )

        # 2. Wait for motion initiation
        await self.wait_for_motion("HORIZONTAL_COORD", "AZ", target_az)
        print("Alt-Az Slew initiation verified")
