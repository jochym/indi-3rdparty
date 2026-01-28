import unittest
import asyncio
import time
from .indi_client import INDIClient

DEVICE_NAME = "Celestron AUX"
INDI_PORT = 7624


class FullSystemTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = INDIClient(port=INDI_PORT)
        await self.client.connect()

    async def asyncTearDown(self):
        await self.client.disconnect()

    async def test_full_sequence(self):
        print(f"Starting Full System Test for {DEVICE_NAME}...")

        # 1. Connection
        await self.client.wait_for_property(DEVICE_NAME, "CONNECTION")
        if (
            self.client.get_property(DEVICE_NAME, "CONNECTION")["values"]["CONNECT"]
            == "Off"
        ):
            await self.client.set_switch(DEVICE_NAME, "CONNECTION", ["CONNECT"])
        await self.client.wait_for_state(DEVICE_NAME, "CONNECTION", "Ok")
        print("[OK] Connected.")

        # 2. Unpark
        prop_park = await self.client.wait_for_property(DEVICE_NAME, "TELESCOPE_PARK")
        if prop_park["values"]["PARK"] == "On":
            print("Unparking...")
            await self.client.set_switch(DEVICE_NAME, "TELESCOPE_PARK", ["UNPARK"])
            await asyncio.sleep(1)
        print("[OK] Unparked.")

        # 3. Location
        loc = await self.client.wait_for_property(DEVICE_NAME, "GEOGRAPHIC_COORD")
        print(
            f"[OK] Location verified: {loc['values']['LAT']}N, {loc['values']['LONG']}E"
        )

        # 4. Encoders & Movement
        prop_enc = await self.client.wait_for_property(
            DEVICE_NAME, "TELESCOPE_ENCODER_STEPS"
        )
        start_az = float(prop_enc["values"]["AXIS_AZ"])

        print("Testing movement scaling...")
        # Ensure we are in SLEW mode
        if "TELESCOPE_ON_COORD_SET" in self.client.devices[DEVICE_NAME]:
            await self.client.set_switch(
                DEVICE_NAME, "TELESCOPE_ON_COORD_SET", ["SLEW"]
            )
        elif "ON_COORD_SET" in self.client.devices[DEVICE_NAME]:
            await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["SLEW"])

        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_SLEW_RATE", ["SLEW_MAX"])
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_MOTION_WE", ["SLEW_EAST"])

        # Wait longer for motion to start and be polled
        await asyncio.sleep(3)

        # Check while moving
        prop_enc_mid = self.client.get_property(DEVICE_NAME, "TELESCOPE_ENCODER_STEPS")
        mid_az = float(prop_enc_mid["values"]["AXIS_AZ"])
        print(f"Encoders during motion: {mid_az}")

        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_MOTION_WE", [])
        await asyncio.sleep(1)

        prop_enc_final = self.client.get_property(
            DEVICE_NAME, "TELESCOPE_ENCODER_STEPS"
        )
        delta = float(prop_enc_final["values"]["AXIS_AZ"]) - start_az

        if delta < -8000000:
            delta += 16777216
        if delta > 8000000:
            delta -= 16777216
        print(f"[OK] Movement detected: {delta} steps.")
        self.assertGreater(abs(delta), 1000)

        # 5. Sync Accuracy
        eq = await self.client.wait_for_property(DEVICE_NAME, "EQUATORIAL_EOD_COORD")
        ra, dec = float(eq["values"]["RA"]), float(eq["values"]["DEC"])
        target_ra = (ra + 0.2) % 24.0

        print(f"Testing Sync to RA {target_ra:.4f}...")
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_ON_COORD_SET", ["SYNC"])
        await self.client.set_number(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD", {"RA": str(target_ra), "DEC": str(dec)}
        )
        await asyncio.sleep(2)

        eq_final = self.client.get_property(DEVICE_NAME, "EQUATORIAL_EOD_COORD")
        final_ra = float(eq_final["values"]["RA"])
        diff = abs(final_ra - target_ra)
        if diff > 12:
            diff = 24 - diff
        print(f"[OK] Sync Deviation: {diff:.6f} hours.")
        self.assertLess(diff, 0.001)

        print("Full System Test COMPLETED SUCCESSFULLY.")


if __name__ == "__main__":
    unittest.main()
