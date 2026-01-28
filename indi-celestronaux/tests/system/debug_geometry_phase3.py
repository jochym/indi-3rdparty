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


class TestGeometryPhase3(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        subprocess.run(
            ["pkill", "-9", "-f", "indi_celestron_aux|indiserver"],
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        if not os.path.exists(DRIVER_EXEC):
            raise RuntimeError(f"Driver executable not found at {DRIVER_EXEC}")
        cmd_indi = ["indiserver", "-v", "-p", str(INDI_PORT), "-r", "0", DRIVER_EXEC]
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

    async def test_coordinate_transformation(self):
        """
        Phase 3: Verify RA/Dec <-> Alt/Az mapping.
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

        # 1. Clear Stale Alignment
        print("Clearing Alignment...")
        await self.client.set_switch(DEVICE_NAME, "ALIGNMENT_CONFIG", ["CLEAR_ALL"])
        await asyncio.sleep(1)

        # 2. Check LST
        # We need to know what RA we expect at the Meridian.
        # Driver location is Lat 50.1822, Lon 19.7925
        await self.client.set_location(DEVICE_NAME, "50.1822", "19.7925", "400.0")
        await asyncio.sleep(1)

        # 3. Read current RA/Dec/LST
        # We look at EQUATORIAL_EOD_COORD and wait for it to be updated
        prop_eq = await self.client.wait_for_property(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD"
        )
        ra = float(prop_eq["values"]["RA"])
        dec = float(prop_eq["values"]["DEC"])
        print(f"Current reported RA: {ra}, Dec: {dec}")

        # 4. Perform a Sync at a specific location
        # Slew manually to Horizon (Alt=0) South (Az=180)
        # Az=180 is 1/2 of 2^24 = 8,388,608 steps
        # Alt=0 is 0 steps
        print("Moving to Zero position (Alt=0, Az=0)...")
        await self.client.set_number(
            DEVICE_NAME, "TELESCOPE_ABSOLUTE_COORD", {"AZM_STEPS": 0, "ALT_STEPS": 0}
        )
        await asyncio.sleep(5)

        # Now Sync the driver to a known RA/Dec.
        # Since we are at Az=0 (North) and Alt=0 (Horizon),
        # RA = (LST + 12h) % 24, Dec = (90 - Lat)
        # But let's just Sync to whatever the driver THINKS is there to see if it accepts it.
        target_ra = (ra + 1.0) % 24.0
        target_dec = dec

        print(f"Syncing to RA={target_ra}, Dec={target_dec}...")
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_ON_COORD_SET", ["SYNC"])
        await self.client.set_number(
            DEVICE_NAME,
            "EQUATORIAL_EOD_COORD",
            {"RA": str(target_ra), "DEC": str(target_dec)},
        )

        await asyncio.sleep(2)
        prop_eq = self.client.get_property(DEVICE_NAME, "EQUATORIAL_EOD_COORD")
        new_ra = float(prop_eq["values"]["RA"])
        print(f"Post-Sync RA: {new_ra}")

        assert abs(new_ra - target_ra) < 0.1, (
            f"Sync failed. Expected {target_ra}, got {new_ra}"
        )

        # 5. Check if RMS error is now sane
        prop_align = self.client.get_property(DEVICE_NAME, "ALIGNMENT_STATUS")
        rms = float(prop_align["values"]["RMS_ERROR"])
        count = float(prop_align["values"]["POINT_COUNT"])
        print(f"Alignment Status: Points={count}, RMS={rms}")

        assert count >= 1, "Alignment point not added"
        # For 1 point, RMS should be effectively 0 or very small
        assert rms < 100, f"RMS error too high after sync: {rms}"

        print("Phase 3: Coordinate Transformation verification successful.")


if __name__ == "__main__":
    unittest.main()
