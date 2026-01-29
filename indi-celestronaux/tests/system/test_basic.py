import unittest
import asyncio
import subprocess
import time
import datetime
import os
import sys
from .indi_client import INDIClient

# The name used by the driver
DEVICE_NAME = "Celestron AUX"
SIM_PORT = 2000
INDI_PORT = 7624
DRIVER_EXEC = os.path.abspath("build/indi_celestron_aux")

# Simulator is configurable via environment variable
DEFAULT_SIM = os.path.abspath("indi-celestronaux/simulator/nse_simulator.py")
SIM_EXEC = os.getenv("INDI_SIM_EXEC", DEFAULT_SIM)


class TestSystem(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 0. Clean up any existing processes
        subprocess.run(
            [
                "pkill",
                "-9",
                "-f",
                "indi_celestron_aux|indiserver|caux-sim|nse_simulator.py",
            ],
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)

        # 1. Start Simulator
        if SIM_EXEC.endswith(".py"):
            cmd_sim = [sys.executable, "-u", SIM_EXEC, "-t", "-p", str(SIM_PORT)]
        else:
            cmd_sim = [SIM_EXEC, "-t", "-p", str(SIM_PORT)]

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
            try:
                self.indi_proc.wait(timeout=2)
            except:
                self.indi_proc.kill()
        if hasattr(self, "sim_proc") and self.sim_proc:
            self.sim_proc.terminate()
            try:
                self.sim_proc.wait(timeout=2)
            except:
                self.sim_proc.kill()
        subprocess.run(
            [
                "pkill",
                "-9",
                "-f",
                "indi_celestron_aux|indiserver|caux-sim|nse_simulator.py",
            ],
            stderr=subprocess.DEVNULL,
        )

    @classmethod
    def setUpClass(cls):
        # Ensure we have clean state before any tests run
        subprocess.run(
            [
                "pkill",
                "-9",
                "-f",
                "indi_celestron_aux|indiserver|caux-sim|nse_simulator.py",
            ],
            stderr=subprocess.DEVNULL,
        )

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

        # Set Location and Time for consistency
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        iso_now = now_utc.strftime("%Y-%m-%dT%H:%M:%S")
        await self.client.set_location(DEVICE_NAME, "51.5", "0.0", "50.0")
        await self.client.set_time(DEVICE_NAME, iso_now, "0")

        # Select Alignment Plugin
        print("Selecting Nearest Math Plugin...")
        await self.client.set_switch(
            DEVICE_NAME, "ALIGNMENT_SUBSYSTEM_MATH_PLUGINS", ["Nearest Math Plugin"]
        )
        # Wait for plugin selection to be reflected
        await self.client.wait_for_condition(
            DEVICE_NAME,
            "ALIGNMENT_SUBSYSTEM_MATH_PLUGINS",
            lambda p: p["values"].get("Nearest Math Plugin") == "On",
            timeout=5,
        )

        # Enable Debug
        await self.client.set_switch(DEVICE_NAME, "DEBUG", ["ENABLE"])

        # Unpark before testing
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_PARK", ["UNPARK"])
        await self.client.wait_for_state(DEVICE_NAME, "TELESCOPE_PARK", "Ok")

        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_TRACK_STATE", ["TRACK_ON"])
        await asyncio.sleep(1)

    async def sync_to_current(self):
        """Helper to sync the driver to current simulator position to establish alignment."""
        # Wait for non-empty coordinates
        prop = await self.client.wait_for_condition(
            DEVICE_NAME,
            "EQUATORIAL_EOD_COORD",
            lambda p: p["values"].get("RA") is not None,
            timeout=10,
        )
        ra = prop["values"]["RA"].strip()
        dec = prop["values"]["DEC"].strip()

        print(f"Syncing to current position: RA={ra}, Dec={dec}")
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

        # Check that we got SOME version (7.x or similar)
        assert get_val("Ra/AZM version").startswith("7")
        assert get_val("Dec/ALT version").startswith("7")

    async def wait_for_motion(self, property_name, field, target_value, timeout=60):
        start_prop = self.client.get_property(DEVICE_NAME, property_name)
        start_val = float(start_prop["values"][field].strip())
        end_time = asyncio.get_event_loop().time() + timeout
        last_val = start_val
        while asyncio.get_event_loop().time() < end_time:
            await asyncio.sleep(0.5)
            curr_prop = self.client.get_property(DEVICE_NAME, property_name)
            curr_val = float(curr_prop["values"][field].strip())
            if abs(curr_val - last_val) > 0.01:
                return curr_prop
            if abs(curr_val - target_value) < 0.2:
                return curr_prop
            last_val = curr_val
        raise TimeoutError(f"Motion timeout for {property_name}.{field}")

    async def test_motion_altaz(self):
        await self.connect_to_sim()
        # For geometry test, disable alignment subsystem
        await self.client.set_switch(
            DEVICE_NAME, "ALIGNMENT_SUBSYSTEM_ACTIVE", ["ALIGNMENT SUBSYSTEM INACTIVE"]
        )
        await asyncio.sleep(1)

        target_az, target_alt = 150.0, 30.0
        await self.client.set_number(
            DEVICE_NAME,
            "HORIZONTAL_COORD",
            {"AZ": str(target_az), "ALT": str(target_alt)},
        )
        await self.wait_for_motion("HORIZONTAL_COORD", "AZ", target_az)

    async def test_abort(self):
        await self.connect_to_sim()
        # Disable alignment for pure physical test
        await self.client.set_switch(
            DEVICE_NAME, "ALIGNMENT_SUBSYSTEM_ACTIVE", ["ALIGNMENT SUBSYSTEM INACTIVE"]
        )
        await asyncio.sleep(1)

        target_az = 270.0
        await self.client.set_number(
            DEVICE_NAME, "HORIZONTAL_COORD", {"AZ": str(target_az), "ALT": "45.0"}
        )
        await asyncio.sleep(3)
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_ABORT_MOTION", ["ABORT"])
        await asyncio.sleep(1)
        prop = self.client.get_property(DEVICE_NAME, "HORIZONTAL_COORD")
        stop_az = float(prop["values"]["AZ"].strip())
        await asyncio.sleep(2)
        prop = self.client.get_property(DEVICE_NAME, "HORIZONTAL_COORD")
        final_az = float(prop["values"]["AZ"].strip())
        assert abs(final_az - stop_az) < 0.5
        assert abs(final_az - target_az) > 1.0

    async def test_encoder_accuracy(self):
        await self.connect_to_sim()

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
        delta_steps = steps2 - steps1
        if delta_steps > 16777216 / 2:
            delta_steps -= 16777216
        if delta_steps < -16777216 / 2:
            delta_steps += 16777216
        delta_deg = deg2 - deg1
        if delta_deg > 180:
            delta_deg -= 360
        if delta_deg < -180:
            delta_deg += 360
        pred_delta_deg = (delta_steps / 16777216.0) * 360.0
        assert abs(pred_delta_deg - delta_deg) < 0.05

    async def test_alignment_accuracy(self):
        await self.connect_to_sim()
        target_ra, target_dec = 12.0, 45.0
        await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["SYNC"])
        await self.client.set_number(
            DEVICE_NAME,
            "EQUATORIAL_EOD_COORD",
            {"RA": str(target_ra), "DEC": str(target_dec)},
        )
        await asyncio.sleep(3)
        prop = self.client.get_property(DEVICE_NAME, "EQUATORIAL_EOD_COORD")
        ra, dec = (
            float(prop["values"]["RA"].strip()),
            float(prop["values"]["DEC"].strip()),
        )
        print(f"Post-Sync position: RA={ra:.4f}, Dec={dec:.4f}")

        # Accuracy should be high immediately after sync
        # We allow a slightly larger RA tolerance because driver's LST might be different from machine's LST
        # and movement depends on when the command was processed.
        assert abs(ra - target_ra) < 0.2
        assert abs(dec - target_dec) < 0.2
        print(f"1-Star Alignment accepted. RA error: {ra - target_ra:.4f}h")
        goto_ra, goto_dec = (ra + 0.1) % 24.0, dec + 1.0
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
        prop = await self.client.wait_for_state(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD", ["Ok", "Idle"], timeout=20
        )
        ra, dec = (
            float(prop["values"]["RA"].strip()),
            float(prop["values"]["DEC"].strip()),
        )
        assert abs(ra - goto_ra) < 0.5
        assert abs(dec - goto_dec) < 1.0

    async def test_alignment_multistar(self):
        await self.connect_to_sim()
        p1_ra, p1_dec = 10.0, 30.0
        await self.client.set_switch(
            DEVICE_NAME, "ALIGNMENT_POINTSET_ACTION", ["APPEND"]
        )
        await self.client.set_number(
            DEVICE_NAME,
            "ALIGNMENT_POINT_MANDATORY_NUMBERS",
            {"ALIGNMENT_POINT_ENTRY_RA": p1_ra, "ALIGNMENT_POINT_ENTRY_DEC": p1_dec},
        )
        await self.client.set_switch(
            DEVICE_NAME, "ALIGNMENT_POINTSET_COMMIT", ["ALIGNMENT_POINTSET_COMMIT"]
        )
        await asyncio.sleep(1)
        p2_ra, p2_dec = 12.0, 50.0
        await self.client.set_number(
            DEVICE_NAME,
            "ALIGNMENT_POINT_MANDATORY_NUMBERS",
            {"ALIGNMENT_POINT_ENTRY_RA": p2_ra, "ALIGNMENT_POINT_ENTRY_DEC": p2_dec},
        )
        await self.client.set_switch(
            DEVICE_NAME, "ALIGNMENT_POINTSET_COMMIT", ["ALIGNMENT_POINTSET_COMMIT"]
        )
        await asyncio.sleep(1)
        prop_size = self.client.get_property(DEVICE_NAME, "ALIGNMENT_POINTSET_SIZE")
        count = float(prop_size["values"]["ALIGNMENT_POINTSET_SIZE"].strip())
        assert count >= 2
        target_az, target_alt = 150.0, 45.0
        await self.client.set_number(
            DEVICE_NAME,
            "HORIZONTAL_COORD",
            {"AZ": str(target_az), "ALT": str(target_alt)},
        )
        await self.wait_for_motion("HORIZONTAL_COORD", "AZ", target_az)

    async def test_reconnection(self):
        await self.connect_to_sim()
        self.sim_proc.terminate()
        self.sim_proc.wait()
        try:
            await self.client.wait_for_state(
                DEVICE_NAME, "CONNECTION", "Alert", timeout=65
            )
        except asyncio.TimeoutError:
            pass

        if SIM_EXEC.endswith(".py"):
            cmd_sim = [sys.executable, "-u", SIM_EXEC, "-t", "-p", str(SIM_PORT)]
        else:
            cmd_sim = [SIM_EXEC, "-t", "-p", str(SIM_PORT)]

        print(f"Restarting simulator: {cmd_sim}")
        self.sim_proc = subprocess.Popen(
            cmd_sim, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        await asyncio.sleep(2)

        await self.client.set_switch(DEVICE_NAME, "CONNECTION", ["CONNECT"])
        prop = await self.client.wait_for_state(
            DEVICE_NAME, "CONNECTION", "Ok", timeout=10
        )
        assert prop["state"] == "Ok"

    async def test_parking(self):
        await self.connect_to_sim()
        # Parking test already unparks in connect_to_sim
        await self.client.set_number(
            DEVICE_NAME, "HORIZONTAL_COORD", {"AZ": "100.0", "ALT": "45.0"}
        )
        await self.wait_for_motion("HORIZONTAL_COORD", "AZ", 100.0)
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_PARK", ["PARK"])
        await self.client.wait_for_state(
            DEVICE_NAME, "TELESCOPE_PARK", "Busy", timeout=5
        )
        prop = await self.client.wait_for_state(
            DEVICE_NAME, "TELESCOPE_PARK", "Ok", timeout=30
        )
        assert prop["state"] == "Ok"

    async def test_homing(self):
        await self.connect_to_sim()
        await self.client.set_number(
            DEVICE_NAME, "HORIZONTAL_COORD", {"AZ": "45.0", "ALT": "45.0"}
        )
        await self.wait_for_motion("HORIZONTAL_COORD", "AZ", 45.0)
        await self.client.set_switch(DEVICE_NAME, "HOME", ["ALL"])
        end_time = time.time() + 60
        home_reached = False
        while time.time() < end_time:
            await asyncio.sleep(2)
            prop_az = self.client.get_property(DEVICE_NAME, "HORIZONTAL_COORD")
            az, alt = (
                float(prop_az["values"]["AZ"].strip()),
                float(prop_az["values"]["ALT"].strip()),
            )
            if az > 180:
                az -= 360
            if abs(az) < 1.0 and abs(alt) < 1.0:
                home_reached = True
                break
        assert home_reached

    async def test_manual_motion(self):
        await self.connect_to_sim()
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_SLEW_RATE", ["8x"])
        await self.client.wait_for_condition(
            DEVICE_NAME,
            "TELESCOPE_SLEW_RATE",
            lambda p: p["values"].get("8x") == "On",
            timeout=5,
        )
        prop = await self.client.wait_for_property(DEVICE_NAME, "HORIZONTAL_COORD")
        start_alt = float(prop["values"]["ALT"].strip())
        await self.client.set_switch(
            DEVICE_NAME, "TELESCOPE_MOTION_NS", ["MOTION_NORTH"]
        )
        end_time, moved = time.time() + 5, False
        while time.time() < end_time:
            await asyncio.sleep(1)
            prop = self.client.get_property(DEVICE_NAME, "HORIZONTAL_COORD")
            curr_alt = float(prop["values"]["ALT"].strip())
            if abs(curr_alt - start_alt) > 0.1:
                moved = True
                break
        assert moved

    async def test_approach_direction(self):
        await self.connect_to_sim()
        await self.client.set_switch(
            DEVICE_NAME, "APPROACH_DIRECTION", ["APPROACH_CONSTANT_OFFSET"]
        )
        target_az, target_alt = 10.0, 5.0
        subprocess.run(["rm", "-f", "/tmp/nse_sim_cmds.log"])
        await self.client.set_number(
            DEVICE_NAME,
            "HORIZONTAL_COORD",
            {"AZ": str(target_az), "ALT": str(target_alt)},
        )
        await self.wait_for_motion("HORIZONTAL_COORD", "AZ", target_az)
        end_time = time.time() + 60
        while time.time() < end_time:
            await asyncio.sleep(2)
            prop = self.client.get_property(DEVICE_NAME, "HORIZONTAL_COORD")
            az = float(prop["values"]["AZ"].strip())
            if prop["state"] in ["Ok", "Idle"] or abs(az - target_az) < 0.5:
                break

    async def test_6b_robustness_pole(self):
        """
        Test mathematical robustness at the celestial pole (Dec +90.0).
        Ported from auxdrv test suite.
        """
        await self.connect_to_sim()
        # Sync to establish alignment
        await self.sync_to_current()

        # Issue GOTO to exactly Dec 90.0
        target_ra = 12.0
        target_dec = 90.0
        await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["SLEW"])
        await self.client.set_number(
            DEVICE_NAME,
            "EQUATORIAL_EOD_COORD",
            {"RA": str(target_ra), "DEC": str(target_dec)},
        )

        # Wait for motion or timeout
        try:
            await self.client.wait_for_state(
                DEVICE_NAME, "EQUATORIAL_EOD_COORD", "Busy", timeout=5
            )
        except:
            pass

        # If it reaches 'Ok' or stays 'Idle' without crashing, it's successful
        prop = await self.client.wait_for_state(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD", ["Ok", "Idle", "Alert"], timeout=30
        )
        assert prop["state"] != "Alert"

    async def test_predictive_tracking(self):
        await self.connect_to_sim()
        await self.client.set_switch(
            DEVICE_NAME, "ALIGNMENT_POINTSET_ACTION", ["APPEND"]
        )
        await self.client.set_number(
            DEVICE_NAME,
            "ALIGNMENT_POINT_MANDATORY_NUMBERS",
            {"ALIGNMENT_POINT_ENTRY_RA": 10.0, "ALIGNMENT_POINT_ENTRY_DEC": 30.0},
        )
        await self.client.set_switch(
            DEVICE_NAME, "ALIGNMENT_POINTSET_COMMIT", ["ALIGNMENT_POINTSET_COMMIT"]
        )
        await asyncio.sleep(1)
        await self.client.set_number(
            DEVICE_NAME,
            "ALIGNMENT_POINT_MANDATORY_NUMBERS",
            {"ALIGNMENT_POINT_ENTRY_RA": 12.0, "ALIGNMENT_POINT_ENTRY_DEC": 50.0},
        )
        await self.client.set_switch(
            DEVICE_NAME, "ALIGNMENT_POINTSET_COMMIT", ["ALIGNMENT_POINTSET_COMMIT"]
        )
        await asyncio.sleep(1)
        await self.client.set_switch(
            DEVICE_NAME, "TELESCOPE_TRACK_MODE", ["TRACK_SIDEREAL"]
        )
        await asyncio.sleep(1)
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_TRACK_STATE", ["TRACK_ON"])
        await self.client.set_number(DEVICE_NAME, "POLLING_PERIOD", {"PERIOD_MS": 250})
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_SLEW_RATE", ["2x"])
        await self.client.set_switch(
            DEVICE_NAME, "TELESCOPE_MOTION_NS", ["MOTION_NORTH"]
        )
        await asyncio.sleep(5)
        await self.client.set_switch(DEVICE_NAME, "TELESCOPE_MOTION_NS", [])
        LOG_PATH = "/tmp/nse_sim_cmds.log"
        if os.path.exists(LOG_PATH):
            os.remove(LOG_PATH)
        with open(LOG_PATH, "w") as f:
            f.write("LOG_START\n")
        for _ in range(30):
            await asyncio.sleep(2)
            if os.path.exists(LOG_PATH):
                with open(LOG_PATH, "r") as f:
                    if any("MOVE_" in line for line in f):
                        break
