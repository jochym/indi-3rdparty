import unittest
import asyncio
from .indi_client import INDIClient

DEVICE_NAME = "Celestron AUX"
INDI_PORT = 7624


class TestGeometryProduction(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Do NOT start or kill any processes, just connect to existing ones
        self.client = INDIClient(port=INDI_PORT)
        await self.client.connect()

    async def asyncTearDown(self):
        await self.client.disconnect()

    async def test_production_alignment(self):
        """
        Verify that the production-run driver and simulator agree on the sky.
        """
        print(f"Connecting to existing {DEVICE_NAME} on port {INDI_PORT}...")
        await self.client.wait_for_property(DEVICE_NAME, "CONNECTION")
        # Assume already connected or wait for it
        conn = self.client.get_property(DEVICE_NAME, "CONNECTION")
        if conn["values"]["CONNECT"] == "Off":
            print("Driver not connected to mount, connecting...")
            await self.client.set_switch(DEVICE_NAME, "CONNECTION", ["CONNECT"])
            await self.client.wait_for_state(DEVICE_NAME, "CONNECTION", "Ok")

        # 1. Unpark and Read location to verify sync
        if "TELESCOPE_PARK" in self.client.devices[DEVICE_NAME]:
            park_prop = self.client.devices[DEVICE_NAME]["TELESCOPE_PARK"]
            if park_prop["values"]["PARK"] == "On":
                print("Mount is PARKED. Unparking...")
                await self.client.set_switch(DEVICE_NAME, "TELESCOPE_PARK", ["UNPARK"])
                await asyncio.sleep(1)

        loc = await self.client.wait_for_property(DEVICE_NAME, "GEOGRAPHIC_COORD")
        print(
            f"Driver Location: Lat {loc['values']['LAT']}, Lon {loc['values']['LONG']}"
        )

        # 2. Initialize Alignment Subsystem like KStars would
        print("Configuring Alignment Subsystem and Tracking...")

        # Select Nearest Math Plugin
        if "ALIGNMENT_SUBSYSTEM_MATH_PLUGINS" in self.client.devices[DEVICE_NAME]:
            await self.client.set_switch(
                DEVICE_NAME, "ALIGNMENT_SUBSYSTEM_MATH_PLUGINS", ["Nearest Math Plugin"]
            )

        # Enable Subsystem
        if "ALIGNMENT_SUBSYSTEM_ACTIVE" in self.client.devices[DEVICE_NAME]:
            await self.client.set_switch(
                DEVICE_NAME,
                "ALIGNMENT_SUBSYSTEM_ACTIVE",
                ["ALIGNMENT SUBSYSTEM ACTIVE"],
            )

        # Enable Tracking (Skipped if property is empty/broken in local build)
        if "TELESCOPE_TRACK_MODE" in self.client.devices[DEVICE_NAME]:
            track_prop = self.client.devices[DEVICE_NAME]["TELESCOPE_TRACK_MODE"]
            if track_prop.get("values"):
                print("Setting Tracking mode...")
                # We'll just try to pick the first available one if TRACK_SIDEREAL is missing
                mode = (
                    "TRACK_SIDEREAL"
                    if "TRACK_SIDEREAL" in track_prop["values"]
                    else list(track_prop["values"].keys())[0]
                )
                await self.client.set_switch(
                    DEVICE_NAME, "TELESCOPE_TRACK_MODE", [mode]
                )
            else:
                print("TELESCOPE_TRACK_MODE is empty. Skipping tracking config.")

        # Clear points to start fresh
        if "ALIGNMENT_CONFIG" in self.client.devices[DEVICE_NAME]:
            await self.client.set_switch(DEVICE_NAME, "ALIGNMENT_CONFIG", ["CLEAR_ALL"])

        await asyncio.sleep(2)

        # 3. Check current RA/Dec
        eq = await self.client.wait_for_property(DEVICE_NAME, "EQUATORIAL_EOD_COORD")
        ra = float(eq["values"]["RA"])
        dec = float(eq["values"]["DEC"])
        print(f"Initial RA: {ra:.4f}, Dec: {dec:.4f}")

        # 4. Perform Sync using standard INDI properties
        target_ra = (ra + 0.5) % 24.0
        print(
            f"Attempting Sync to RA={target_ra:.4f} using standard INDI properties..."
        )

        # Ensure mode is SYNC (Try both common property names)
        if "ON_COORD_SET" in self.client.devices[DEVICE_NAME]:
            await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["SYNC"])
        elif "TELESCOPE_ON_COORD_SET" in self.client.devices[DEVICE_NAME]:
            await self.client.set_switch(
                DEVICE_NAME, "TELESCOPE_ON_COORD_SET", ["SYNC"]
            )

        # Try writing to EQUATORIAL_EOD_COORD
        await self.client.set_number(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD", {"RA": str(target_ra), "DEC": str(dec)}
        )

        # Also try TELESCOPE_SYNC property directly if it exists
        if "TELESCOPE_SYNC" in self.client.devices[DEVICE_NAME]:
            print("Using TELESCOPE_SYNC trigger...")
            await self.client.set_number(
                DEVICE_NAME, "TELESCOPE_SYNC", {"RA": str(target_ra), "DEC": str(dec)}
            )

        await asyncio.sleep(2)
        eq_final = self.client.get_property(DEVICE_NAME, "EQUATORIAL_EOD_COORD")
        final_ra = float(eq_final["values"]["RA"])
        print(f"Post-Sync RA: {final_ra:.4f}")

        # Check alignment status to see if point was added
        if "ALIGNMENT_STATUS" in self.client.devices[DEVICE_NAME]:
            align = self.client.devices[DEVICE_NAME]["ALIGNMENT_STATUS"]
            print(
                f"Alignment Status: Points={align['values']['POINT_COUNT']}, RMS={align['values']['RMS_ERROR']}"
            )

        diff = abs(final_ra - target_ra)
        if diff > 12:
            diff = 24 - diff
        print(f"Sync Deviation: {diff:.6f} hours")

        self.assertLess(
            diff, 0.01, "Sync disagreement! Driver did not accept the alignment point."
        )


if __name__ == "__main__":
    unittest.main()
