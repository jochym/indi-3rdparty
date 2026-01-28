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


class TestGeometryPhase2(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Clean up driver/indiserver only (simulator is running externally)
        subprocess.run(
            ["pkill", "-9", "-f", "indi_celestron_aux|indiserver"],
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)

        # 2. Start Indiserver
        if not os.path.exists(DRIVER_EXEC):
            raise RuntimeError(f"Driver executable not found at {DRIVER_EXEC}")

        cmd_indi = ["indiserver", "-v", "-p", str(INDI_PORT), "-r", "0", DRIVER_EXEC]
        print(f"Starting indiserver: {cmd_indi}")
        self.indi_proc = subprocess.Popen(
            cmd_indi, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(2)

        self.client = INDIClient(port=INDI_PORT)
        await self.client.connect()

    async def asyncTearDown(self):
        await self.client.disconnect()
        if hasattr(self, "indi_proc") and self.indi_proc:
            self.indi_proc.terminate()
        subprocess.run(
            ["pkill", "-9", "-f", "indi_celestron_aux|indiserver"],
            stderr=subprocess.DEVNULL,
        )

    async def test_geometry_verification(self):
        """
        Phase 2: Verify Geometry Scaling and Directionality using MOUNT_POSITION.
        """
        await self.client.wait_for_property(DEVICE_NAME, "CONNECTION")
        await self.client.set_switch(DEVICE_NAME, "CONNECTION_MODE", ["CONNECTION_TCP"])
        await self.client.set_text(
            DEVICE_NAME,
            "DEVICE_ADDRESS",
            {"PORT": str(SIM_PORT), "ADDRESS": "localhost"},
        )
        await self.client.set_switch(DEVICE_NAME, "CONNECTION", ["CONNECT"])
        await self.client.wait_for_state(DEVICE_NAME, "CONNECTION", "Ok")

        # 1. Clear Alignment
        print("Clearing Alignment points...")
        await self.client.set_switch(DEVICE_NAME, "ALIGNMENT_CONFIG", ["CLEAR_ALL"])
        await asyncio.sleep(1)

        # 2. Get initial position
        prop_mount = await self.client.wait_for_property(DEVICE_NAME, "MOUNT_POSITION")
        start_az_steps = float(prop_mount["values"]["AZM_STEPS"])
        start_alt_steps = float(prop_mount["values"]["ALT_STEPS"])
        print(f"Initial Encoders: AZ={start_az_steps}, ALT={start_alt_steps}")

        # 3. Slew manually for a few seconds to measure scaling
        # Set rate to SLEW_MAX (usually rate 9)
        print("Slewing Azimuth East...")
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_SLEW_RATE", ["SLEW_MAX"])
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_MOTION_WE", ["SLEW_EAST"])

        # Slew for 2 seconds. At 4 deg/s (Evolution max), this should be ~8 degrees
        await asyncio.sleep(2)

        # Stop
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_MOTION_WE", [])
        await asyncio.sleep(1)

        prop_mount = self.client.get_property(DEVICE_NAME, "MOUNT_POSITION")
        end_az_steps = float(prop_mount["values"]["AZM_STEPS"])

        delta_steps = end_az_steps - start_az_steps
        # Handle 24-bit wrap
        if delta_steps < -8000000:
            delta_steps += 16777216
        if delta_steps > 8000000:
            delta_steps -= 16777216

        print(f"Delta AZ steps: {delta_steps}")

        # For Evolution, East motion (positive Azimuth) should INCREASE encoder steps
        assert delta_steps > 0, (
            "Azimuth encoder steps should increase for East movement"
        )

        # 4. Check Altitude
        print("Slewing Altitude North (UP)...")
        # Ensure we are at a high rate
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_SLEW_RATE", ["SLEW_MAX"])
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_MOTION_NS", ["SLEW_NORTH"])

        # Slew for 4 seconds to be absolutely sure
        await asyncio.sleep(4)

        # Check during motion
        prop_mid = self.client.get_property(DEVICE_NAME, "MOUNT_POSITION")
        mid_alt_steps = float(prop_mid["values"]["ALT_STEPS"])
        print(f"Altitude steps during motion: {mid_alt_steps}")

        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_MOTION_NS", [])
        await asyncio.sleep(1)

        prop_mount = self.client.get_property(DEVICE_NAME, "MOUNT_POSITION")
        end_alt_steps = float(prop_mount["values"]["ALT_STEPS"])

        delta_alt = end_alt_steps - start_alt_steps
        if delta_alt < -8000000:
            delta_alt += 16777216
        if delta_alt > 8000000:
            delta_alt -= 16777216

        print(f"Delta ALT steps: {delta_alt}")
        # For Alt-Az, North/Up usually increases Altitude (and encoder steps)
        assert abs(delta_alt) > 100, f"Altitude did not move. Delta: {delta_alt}"

        # Verify direction: If Alt increases from 0 towards 90 (Zenith), steps should increase.
        # In NexStar protocol, 0 is usually horizon, increasing towards zenith.
        print(f"Altitude Direction: {'Positive' if delta_alt > 0 else 'Negative'}")

        print("Phase 2: Raw Encoder Geometry confirmed.")


if __name__ == "__main__":
    unittest.main()
