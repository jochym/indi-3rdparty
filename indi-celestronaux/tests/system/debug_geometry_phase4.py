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


class TestGeometryPhase4(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        subprocess.run(
            ["pkill", "-9", "-f", "indi_celestron_aux|indiserver"],
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
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

    async def test_calibration_reset(self):
        """
        Phase 4: Reset all internal offsets and verify Sync.
        """
        await self.client.wait_for_property(DEVICE_NAME, "CONNECTION")
        await self.client.set_switch(DEVICE_NAME, "CONNECTION", ["CONNECT"])
        await self.client.wait_for_state(DEVICE_NAME, "CONNECTION", "Ok")

        # 1. Clear Alignment and Calibration
        print("Clearing Alignment...")
        await self.client.set_switch(DEVICE_NAME, "ALIGNMENT_CONFIG", ["CLEAR_ALL"])

        # 2. Reset Calibration Params (Cone error, Non-perp, Alt Offset)
        print("Resetting Calibration Parameters...")
        if "CALIBRATION_PARAMS" in self.client.devices[DEVICE_NAME]:
            await self.client.set_number(
                DEVICE_NAME,
                "CALIBRATION_PARAMS",
                {"CONE_ERROR": "0.0", "NON_PERP": "0.0", "ALT_OFFSET": "0.0"},
            )

        await asyncio.sleep(2)

        # 3. Move to 0,0 encoders
        print("Moving to Zero steps...")
        await self.client.set_number(
            DEVICE_NAME, "TELESCOPE_ABSOLUTE_COORD", {"AZM_STEPS": 0, "ALT_STEPS": 0}
        )
        await asyncio.sleep(5)

        # 4. Attempt Sync again
        prop_eq = await self.client.wait_for_property(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD"
        )
        ra = float(prop_eq["values"]["RA"])
        target_ra = (ra + 1.0) % 24.0

        print(f"Attempting Sync to RA={target_ra} after calibration reset...")
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_ON_COORD_SET", ["SYNC"])
        await self.client.set_number(
            DEVICE_NAME,
            "EQUATORIAL_EOD_COORD",
            {"RA": str(target_ra), "DEC": str(prop_eq["values"]["DEC"])},
        )

        await asyncio.sleep(2)
        prop_eq_final = self.client.get_property(DEVICE_NAME, "EQUATORIAL_EOD_COORD")
        final_ra = float(prop_eq_final["values"]["RA"])
        print(f"Final RA: {final_ra}")

        assert abs(final_ra - target_ra) < 0.1, (
            f"Sync still failing. Expected {target_ra}, got {final_ra}"
        )
        print("Phase 4: Calibration reset successfully allowed a valid Sync.")


if __name__ == "__main__":
    unittest.main()
