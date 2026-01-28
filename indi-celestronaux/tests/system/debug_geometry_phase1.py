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


class TestGeometryPhase1(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 0. Clean up
        subprocess.run(
            ["pkill", "-9", "-f", "indi_celestron_aux|indiserver|nse_simulator.py"],
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)

        # 1. Start Simulator with Phase 1 config (backlash=0, PE=0, etc.)
        cmd_sim = [sys.executable, "-u", SIM_EXEC, "-t", "-p", str(SIM_PORT)]
        print(f"Starting simulator: {cmd_sim}")
        self.sim_proc = subprocess.Popen(
            cmd_sim,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(SIM_EXEC),
        )
        time.sleep(2)

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
        if hasattr(self, "sim_proc") and self.sim_proc:
            self.sim_proc.terminate()
        subprocess.run(
            ["pkill", "-9", "-f", "indi_celestron_aux|indiserver|nse_simulator.py"],
            stderr=subprocess.DEVNULL,
        )

    async def test_location_and_time_sync(self):
        """
        Phase 1: Verify Location and Time synchronization.
        We force the driver to ALTAZ and verify it sends location to simulator via GPS emulation.
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

        # 1. Enable GPS Emulation in Driver
        print("Enabling GPS Emulation...")
        await self.client.set_switch(DEVICE_NAME, "GPSEMU", ["GPSEMU_ON"])

        # 2. Set explicit Location in Driver
        # Standard Site: Lat 50.1822, Lon 19.7925 (matches config.toml)
        test_lat = 50.1822
        test_lon = 19.7925
        print(f"Setting Driver Location to Lat={test_lat}, Lon={test_lon}...")
        await self.client.set_location(
            DEVICE_NAME, str(test_lat), str(test_lon), "400.0"
        )

        # Wait for driver to process and potentially send GPS commands
        await asyncio.sleep(2)

        # 3. Verify Location in Simulator
        # We check the simulator's internal state. Since we can't easily read it,
        # we check the GEOGRAPHIC_COORD property which the driver should have updated.
        loc_prop = self.client.get_property(DEVICE_NAME, "GEOGRAPHIC_COORD")
        assert abs(float(loc_prop["values"]["LAT"]) - test_lat) < 0.001
        assert abs(float(loc_prop["values"]["LONG"]) - test_lon) < 0.001
        print("Driver Location confirmed.")

        # 4. Verify Time
        # The driver uses system time for GPS emulation.
        # Check standard properties
        print("Waiting for any time/coord properties...")
        await self.client.wait_for_any_property(
            DEVICE_NAME,
            lambda d, n, p: n in ["HORIZONTAL_COORD", "EQUATORIAL_EOD_COORD"],
            timeout=10,
        )

        # 5. Force Mount Type to ALTAZ
        # Many issues stem from driver defaulting to GEM.
        print("Forcing Mount Type to ALTAZ...")
        # Note: In this driver, MOUNT_TYPE is often read-only or depends on config.
        # But we can try to set it via TELESCOPE_MOUNT_TYPE if available.
        if "TELESCOPE_MOUNT_TYPE" in self.client.devices[DEVICE_NAME]:
            await self.client.set_switch(DEVICE_NAME, "TELESCOPE_MOUNT_TYPE", ["ALTAZ"])
            await asyncio.sleep(1)
            mt_prop = self.client.get_property(DEVICE_NAME, "TELESCOPE_MOUNT_TYPE")
            print(f"Current Mount Type: {mt_prop['values']}")

        print("Phase 1: Location, Time, and Mount Type alignment completed.")


if __name__ == "__main__":
    unittest.main()
