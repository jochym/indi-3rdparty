import unittest
import asyncio
from .indi_client import INDIClient

DEVICE_NAME = "Celestron AUX"
INDI_PORT = 7624


class TestLocalDriver(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = INDIClient(port=INDI_PORT)
        await self.client.connect()

    async def asyncTearDown(self):
        await self.client.disconnect()

    async def test_sync_on_local_build(self):
        print(f"Testing Local Driver Build on port {INDI_PORT}...")
        await self.client.wait_for_property(DEVICE_NAME, "CONNECTION")

        # 1. Connect
        conn = self.client.get_property(DEVICE_NAME, "CONNECTION")
        if conn["values"]["CONNECT"] == "Off":
            await self.client.set_switch(DEVICE_NAME, "CONNECTION", ["CONNECT"])
            await self.client.wait_for_state(DEVICE_NAME, "CONNECTION", "Ok")

        # 2. UNPARK - CRITICAL
        print("Ensuring mount is UNPARKED...")
        if "TELESCOPE_PARK" in self.client.devices[DEVICE_NAME]:
            await self.client.set_switch(DEVICE_NAME, "TELESCOPE_PARK", ["UNPARK"])
            await asyncio.sleep(1)

        # 3. Configure Alignment fresh
        print("Resetting Alignment Subsystem...")
        if "ALIGNMENT_SUBSYSTEM_MATH_PLUGINS" in self.client.devices[DEVICE_NAME]:
            await self.client.set_switch(
                DEVICE_NAME, "ALIGNMENT_SUBSYSTEM_MATH_PLUGINS", ["Nearest Math Plugin"]
            )
        if "ALIGNMENT_CONFIG" in self.client.devices[DEVICE_NAME]:
            await self.client.set_switch(DEVICE_NAME, "ALIGNMENT_CONFIG", ["CLEAR_ALL"])
        await asyncio.sleep(1)

        # 4. Get Current Position
        eq = await self.client.wait_for_property(DEVICE_NAME, "EQUATORIAL_EOD_COORD")
        ra, dec = float(eq["values"]["RA"]), float(eq["values"]["DEC"])
        print(f"Initial RA: {ra:.4f}")

        # 5. Perform Sync
        target_ra = (ra + 0.2) % 24.0
        print(f"Syncing to RA: {target_ra:.4f}...")

        sync_prop = (
            "ON_COORD_SET"
            if "ON_COORD_SET" in self.client.devices[DEVICE_NAME]
            else "TELESCOPE_ON_COORD_SET"
        )
        await self.client.set_switch(DEVICE_NAME, sync_prop, ["SYNC"])
        await self.client.set_number(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD", {"RA": str(target_ra), "DEC": str(dec)}
        )

        await asyncio.sleep(2)
        eq_final = self.client.get_property(DEVICE_NAME, "EQUATORIAL_EOD_COORD")
        final_ra = float(eq_final["values"]["RA"])
        print(f"Post-Sync RA: {final_ra:.4f}")

        diff = abs(final_ra - target_ra)
        if diff > 12:
            diff = 24 - diff

        self.assertLess(
            diff, 0.01, f"Sync failed on local build! Deviation: {diff:.6f}h"
        )
        print("[OK] Local build PASSED synchronization test.")


if __name__ == "__main__":
    unittest.main()
