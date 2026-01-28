import unittest
import asyncio
import subprocess
import time
import os
import sys
from datetime import datetime, timezone
from .indi_client import INDIClient

DEVICE_NAME = "Celestron AUX"
SIM_PORT = 2000
INDI_PORT = 7624
DRIVER_EXEC = os.path.abspath("build/indi_celestron_aux")


class TestGeometryFinal(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        subprocess.run(
            ["pkill", "-9", "-f", "indi_celestron_aux|indiserver"],
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        self.indi_proc = subprocess.Popen(
            ["indiserver", "-v", "-p", str(INDI_PORT), "-r", "0", DRIVER_EXEC],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(2)
        self.client = INDIClient(port=INDI_PORT)
        await self.client.connect()

    async def asyncTearDown(self):
        await self.client.disconnect()
        self.indi_proc.terminate()

    async def test_lst_alignment(self):
        """
        Final Check: Verify if snap-back RA matches calculated sky position for 0,0 encoders.
        """
        await self.client.wait_for_property(DEVICE_NAME, "CONNECTION")
        await self.client.set_switch(DEVICE_NAME, "CONNECTION", ["CONNECT"])
        await self.client.wait_for_state(DEVICE_NAME, "CONNECTION", "Ok")

        # 1. Ensure Location is set
        lat, lon = 50.1822, 19.7925
        await self.client.set_location(DEVICE_NAME, str(lat), str(lon), "400.0")

        # 2. Move to 0,0
        await self.client.set_number(
            DEVICE_NAME, "TELESCOPE_ABSOLUTE_COORD", {"AZM_STEPS": 0, "ALT_STEPS": 0}
        )
        await asyncio.sleep(5)

        # 3. Read RA and compare with system LST
        prop_eq = await self.client.wait_for_property(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD"
        )
        reported_ra = float(prop_eq["values"]["RA"])

        # Simple LST approx: (UTC_Hours + Lon/15) mod 24
        # (This is rough but should be within minutes)
        now_utc = datetime.now(timezone.utc)
        utc_hours = now_utc.hour + now_utc.minute / 60.0 + now_utc.second / 3600.0
        approx_lst = (utc_hours + lon / 15.0) % 24.0

        # For Az=0, Alt=0 (North Horizon)
        # Expected RA should be roughly (approx_lst + 12) % 24
        expected_ra = (approx_lst + 12.0) % 24.0

        print(f"UTC Time: {utc_hours:.4f}")
        print(f"Approx LST: {approx_lst:.4f}")
        print(f"Expected RA (at North Horizon): {expected_ra:.4f}")
        print(f"Driver Reported RA: {reported_ra:.4f}")
        print(f"Difference: {abs(reported_ra - expected_ra):.4f} hours")

        # If difference is ~12 hours, then Az=0 is South in driver.
        # If difference is huge, then longitude or time is inverted.

        assert (
            abs(reported_ra - expected_ra) < 1.0
            or abs(reported_ra - (expected_ra + 12) % 24) < 1.0
        ), "Driver RA is completely unrelated to local sky geometry!"


if __name__ == "__main__":
    unittest.main()
