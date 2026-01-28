import unittest
import asyncio
import time
import os
from .indi_client import INDIClient

DEVICE_NAME = "Celestron AUX"
INDI_PORT = 7624

# Targets near North for Lat 50N, LST ~22.5h (RA ~10.5h at North Horizon)
STARS = [
    {"name": "Dubhe", "ra": 11.06, "dec": 61.75},
    {"name": "Alioth", "ra": 12.90, "dec": 55.96},
    {"name": "Alkaid", "ra": 13.79, "dec": 49.31},
]


class TestFunctionalGOTO(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = INDIClient(port=INDI_PORT)
        await self.client.connect()

    async def asyncTearDown(self):
        await self.client.disconnect()

    async def test_goto_tracking_sequence(self):
        print(f"\nStarting Functional GOTO (TRACKING) Test for {DEVICE_NAME}...")

        # 1. Connection check
        await self.client.wait_for_property(DEVICE_NAME, "CONNECTION")
        conn_prop = self.client.get_property(DEVICE_NAME, "CONNECTION")
        if conn_prop["values"]["CONNECT"] == "Off":
            print("Connecting to device...")
            await self.client.set_switch(DEVICE_NAME, "CONNECTION", ["CONNECT"])
            await self.client.wait_for_state(DEVICE_NAME, "CONNECTION", "Ok")
        print("[OK] Connected.")

        # 2. Unpark
        print("Checking mount park status...")
        park_prop = await self.client.wait_for_property(DEVICE_NAME, "TELESCOPE_PARK")
        # In INDI, a switch is active if its value is 'On'
        if park_prop["values"].get("PARK") == "On":
            print("Mount is PARKED. Unparking...")
            await self.client.set_switch(DEVICE_NAME, "TELESCOPE_PARK", ["UNPARK"])
            await self.client.wait_for_state(DEVICE_NAME, "TELESCOPE_PARK", "Ok")
            print("[OK] Unparked.")
        elif park_prop["values"].get("UNPARK") == "On":
            print("[OK] Mount already UNPARKED.")
        else:
            # Fallback if names are different or state is ambiguous
            print(
                f"Current Park Property values: {park_prop['values']}. Attempting UNPARK just in case..."
            )
            await self.client.set_switch(DEVICE_NAME, "TELESCOPE_PARK", ["UNPARK"])
            await self.client.wait_for_state(DEVICE_NAME, "TELESCOPE_PARK", "Ok")
            print("[OK] Unparked.")

        # 3. Disable Alignment Subsystem (Pure Geometry Test)
        print("Disabling Alignment Subsystem...")
        if "ALIGNMENT_SUBSYSTEM_ACTIVE" in self.client.devices[DEVICE_NAME]:
            await self.client.set_switch(
                DEVICE_NAME,
                "ALIGNMENT_SUBSYSTEM_ACTIVE",
                ["ALIGNMENT SUBSYSTEM INACTIVE"],
            )
            await asyncio.sleep(1)

        # 4. Enable Tracking state
        print("Enabling Tracking state...")
        # CRITICAL: Setting ON_COORD_SET to TRACK before issuing coordinates
        await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["TRACK"])

        # Explicitly force TRACK_ON
        if "TELESCOPE_TRACK_STATE" in self.client.devices[DEVICE_NAME]:
            await self.client.set_switch(
                DEVICE_NAME, "TELESCOPE_TRACK_STATE", ["TRACK_ON"]
            )

        await asyncio.sleep(1)
        ts = self.client.get_property(DEVICE_NAME, "TELESCOPE_TRACK_STATE")
        print(f"Initial Tracking state: {ts['values']}")

        # 5. GOTO 3 Stars
        for star in STARS:
            print(
                f"\nExecuting GOTO: {star['name']} (RA: {star['ra']}, Dec: {star['dec']})..."
            )

            # Ensure mode is TRACK for the duration of the command
            await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["TRACK"])

            # Send coordinates
            await self.client.set_number(
                DEVICE_NAME,
                "EQUATORIAL_EOD_COORD",
                {"RA": str(star["ra"]), "DEC": str(star["dec"])},
            )

            # Wait for slew to start
            print("Motion started...")
            await asyncio.sleep(5)

            # Wait for slew to complete
            print("Waiting for arrival (monitoring EQUATORIAL_EOD_COORD state)...")
            prop_final = await self.client.wait_for_state(
                DEVICE_NAME, "EQUATORIAL_EOD_COORD", "Ok", timeout=600
            )

            final_ra = float(prop_final["values"]["RA"])
            final_dec = float(prop_final["values"]["DEC"])
            print(
                f"[OK] Arrived at {star['name']}. RA: {final_ra:.4f}, Dec: {final_dec:.4f}"
            )

            # Verify tracking state at destination
            ts_check = self.client.get_property(DEVICE_NAME, "TELESCOPE_TRACK_STATE")
            print(f"Destination Tracking state: {ts_check['values']}")

            if ts_check["values"]["TRACK_OFF"] == "On":
                print("Warning: Tracking is OFF. Retrying TRACK_ON...")
                await self.client.set_switch(
                    DEVICE_NAME, "TELESCOPE_TRACK_STATE", ["TRACK_ON"]
                )
                await asyncio.sleep(1)

        # 6. Park
        print("\nParking mount...")
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_PARK", ["PARK"])
        await self.client.wait_for_state(
            DEVICE_NAME, "TELESCOPE_PARK", "Ok", timeout=300
        )
        print("[OK] Mount Parked.")

        print("\nFunctional GOTO Test COMPLETED SUCCESSFULLY.")


if __name__ == "__main__":
    unittest.main()
