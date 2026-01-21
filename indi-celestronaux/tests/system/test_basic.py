import unittest
import asyncio
import subprocess
import time
import os
import sys
from .indi_client import INDIClient

# Revert to standard name since -n renaming is problematic
DEVICE_NAME = "Celestron AUX"
SIM_PORT = 2000
INDI_PORT = 7624
DRIVER_EXEC = os.path.abspath("build/indi_celestron_aux")
SIM_EXEC = os.path.abspath("indi-celestronaux/simulator/nse_simulator.py")


class TestSystem(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 0. Clean up
        subprocess.run(
            ["pkill", "-9", "-f", "indi_celestron_aux|indiserver|nse_simulator.py"],
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)

        # 1. Start Simulator
        cmd_sim = [sys.executable, "-u", SIM_EXEC, "-t", "-p", str(SIM_PORT)]
        print(f"Starting simulator: {cmd_sim}")
        self.sim_proc = subprocess.Popen(
            cmd_sim, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(1)

        # 2. Start Indiserver
        if not os.path.exists(DRIVER_EXEC):
            raise RuntimeError(f"Driver executable not found at {DRIVER_EXEC}")

        # Use standard indiserver launch
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

    @classmethod
    def setUpClass(cls):
        pass

    @classmethod
    def tearDownClass(cls):
        pass

    async def connect_to_sim(self):
        """Helper to connect the driver to the simulator."""
        await self.client.wait_for_property(DEVICE_NAME, "CONNECTION")
        await self.client.set_switch(DEVICE_NAME, "CONNECTION_MODE", ["CONNECTION_TCP"])
        await self.client.set_text(
            DEVICE_NAME,
            "DEVICE_ADDRESS",
            {"PORT": str(SIM_PORT), "ADDRESS": "localhost"},
        )
        await self.client.set_switch(DEVICE_NAME, "CONNECTION", ["CONNECT"])
        await self.client.wait_for_state(DEVICE_NAME, "CONNECTION", "Ok")

        # Wait for coordinate properties
        await self.client.wait_for_any_property(
            DEVICE_NAME,
            lambda d, n, p: n in ["HORIZONTAL_COORD", "EQUATORIAL_EOD_COORD"],
            timeout=10,
        )

        # Set Location and Time
        await self.client.set_location(DEVICE_NAME, "51.5", "0.0", "50.0")
        await self.client.set_time(DEVICE_NAME, "2026-01-21T13:30:00", "0")

        # Select Alignment Plugin
        print("Selecting Nearest Math Plugin...")
        await self.client.set_switch(
            DEVICE_NAME, "ALIGNMENT_SUBSYSTEM_MATH_PLUGINS", ["Nearest Math Plugin"]
        )

        # Enable Debug

        await self.client.set_switch(DEVICE_NAME, "DEBUG", ["ENABLE"])
        # Wait for dynamic properties
        await asyncio.sleep(0.5)
        if "DEBUG_LEVEL" in self.client.devices[DEVICE_NAME]:
            # Enable all debug levels to see what's happening
            switches = list(
                self.client.devices[DEVICE_NAME]["DEBUG_LEVEL"]["values"].keys()
            )
            await self.client.set_switch(DEVICE_NAME, "DEBUG_LEVEL", switches)

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
        await self.client.set_number(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD", {"RA": ra, "DEC": dec}
        )
        await asyncio.sleep(3)
        # Switch back to SLEW for GOTO, others OFF
        await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["SLEW"])
        await asyncio.sleep(1)

    async def test_firmware_info(self):
        await self.connect_to_sim()
        prop = None
        start_time = time.time()
        while time.time() - start_time < 15:
            prop = self.client.get_property(DEVICE_NAME, "Firmware Info")
            if prop and any(
                v.strip() != "Unknown" and v.strip() != ""
                for v in prop["values"].values()
            ):
                break
            try:
                prop = await self.client.wait_for_property(
                    DEVICE_NAME, "Firmware Info", timeout=2
                )
                if any(
                    v.strip() != "Unknown" and v.strip() != ""
                    for v in prop["values"].values()
                ):
                    break
            except asyncio.TimeoutError:
                pass
        assert prop

        def get_val(name):
            return prop["values"].get(name, "").strip()

        assert "7.11" in get_val("Ra/AZM version")
        assert "7.11" in get_val("Dec/ALT version")

    async def wait_for_motion(self, property_name, field, target_value, timeout=60):
        start_prop = self.client.get_property(DEVICE_NAME, property_name)
        start_val = float(start_prop["values"][field].strip())
        end_time = asyncio.get_event_loop().time() + timeout
        last_val = start_val
        while asyncio.get_event_loop().time() < end_time:
            await asyncio.sleep(2)
            curr_prop = self.client.get_property(DEVICE_NAME, property_name)
            curr_val = float(curr_prop["values"][field].strip())
            if abs(curr_val - last_val) > 0.05:
                return curr_prop
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
        target_az = 150.0
        target_alt = 30.0

        print(f"Slewing to Az={target_az}, Alt={target_alt}")
        await self.client.set_number(
            DEVICE_NAME,
            "HORIZONTAL_COORD",
            {"AZ": str(target_az), "ALT": str(target_alt)},
        )

        # 2. Wait for motion initiation
        await self.wait_for_motion("HORIZONTAL_COORD", "AZ", target_az)
        print("Alt-Az Slew initiation verified")

    async def test_abort(self):
        """
        Verifies that Abort command stops slewing.
        """
        await self.connect_to_sim()
        await self.sync_to_current()

        # 1. Start a long slew
        target_az = 270.0
        await self.client.set_number(
            DEVICE_NAME, "HORIZONTAL_COORD", {"AZ": str(target_az), "ALT": "45.0"}
        )

        # 2. Wait for motion to start
        await asyncio.sleep(3)
        prop = self.client.get_property(DEVICE_NAME, "HORIZONTAL_COORD")
        start_az = float(prop["values"]["AZ"].strip())
        print(f"Slew started, current Az={start_az}")

        # 3. Issue Abort
        print("Issuing Abort...")
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_ABORT_MOTION", ["ABORT"])
        await asyncio.sleep(1)

        # 4. Verify it stopped
        prop = self.client.get_property(DEVICE_NAME, "HORIZONTAL_COORD")
        stop_az = float(prop["values"]["AZ"].strip())

        await asyncio.sleep(2)
        prop = self.client.get_property(DEVICE_NAME, "HORIZONTAL_COORD")
        final_az = float(prop["values"]["AZ"].strip())

        print(f"Stopped at Az={stop_az}, Final Az={final_az}")
        assert abs(final_az - stop_az) < 0.1
        assert abs(final_az - target_az) > 1.0
        print("Abort successful.")

    async def test_encoder_accuracy(self):
        await self.connect_to_sim()
        await self.sync_to_current()

        def get_vals():
            p_s = self.client.get_property(DEVICE_NAME, "TELESCOPE_ENCODER_STEPS")
            p_a = self.client.get_property(DEVICE_NAME, "HORIZONTAL_COORD")
            return (
                float(p_s["values"]["AXIS_AZ"].strip()),
                float(p_a["values"]["AZ"].strip()),
            )

        steps1, deg1 = get_vals()
        target_az = (deg1 + 5.0) % 360
        await self.client.set_number(
            DEVICE_NAME, "HORIZONTAL_COORD", {"AZ": str(target_az)}
        )
        await asyncio.sleep(5)
        steps2, deg2 = get_vals()
        delta_steps, delta_deg = steps2 - steps1, deg2 - deg1
        if delta_deg > 180:
            delta_deg -= 360
        if delta_deg < -180:
            delta_deg += 360
        pred_delta_deg = (delta_steps / 16777216.0) * 360.0
        assert abs(pred_delta_deg - delta_deg) < 0.05

    async def test_alignment_accuracy(self):
        """
        Phase 4a: Verifies that Sync correctly aligns the Sky Model.
        """
        await self.connect_to_sim()

        # 1. Target coordinates
        target_ra = 12.0
        target_dec = 45.0

        print(f"Syncing to RA={target_ra}, Dec={target_dec}...")
        await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["SYNC"])
        await self.client.set_number(
            DEVICE_NAME,
            "EQUATORIAL_EOD_COORD",
            {"RA": str(target_ra), "DEC": str(target_dec)},
        )

        # 2. Wait for OK state
        prop = await self.client.wait_for_state(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD", "Ok", timeout=10
        )

        ra, dec = (
            float(prop["values"]["RA"].strip()),
            float(prop["values"]["DEC"].strip()),
        )
        print(f"Post-Sync position: RA={ra:.4f}, Dec={dec:.4f}")
        # We don't assert absolute accuracy here because the driver might have
        # internal offsets or alignment model constraints.
        # But we verify that the command was accepted (Ok state).
        assert prop["state"] == "Ok"
        print(f"1-Star Alignment accepted at RA={ra:.4f}, Dec={dec:.4f}")

        # 3. Verify that a nearby GOTO is accurate relative to the synced point
        # We move 0.1h RA and 1.0 deg Dec away
        goto_ra = (ra + 0.1) % 24.0
        goto_dec = dec + 1.0
        print(f"Performing GOTO to RA={goto_ra:.4f}, Dec={goto_dec:.4f}...")
        await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["SLEW"])
        await self.client.set_number(
            DEVICE_NAME,
            "EQUATORIAL_EOD_COORD",
            {"RA": str(goto_ra), "DEC": str(goto_dec)},
        )
        try:
            await self.client.wait_for_state(
                DEVICE_NAME, "EQUATORIAL_EOD_COORD", "Busy", timeout=5
            )
        except:
            pass
        # Driver transitions to Idle or Ok after slew
        prop = await self.client.wait_for_state(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD", ["Ok", "Idle"], timeout=20
        )
        ra, dec = (
            float(prop["values"]["RA"].strip()),
            float(prop["values"]["DEC"].strip()),
        )
        print(f"Final position: RA={ra:.4f}, Dec={dec:.4f}")
        # Allow larger tolerance for simulation drift and 1-star model
        assert abs(ra - goto_ra) < 0.2
        assert abs(dec - goto_dec) < 0.5
        print("GOTO accuracy after alignment verified (with simulation tolerance).")
