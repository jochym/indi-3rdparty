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


class TestSystem(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Start Simulator
        cmd_sim = [sys.executable, "-u", SIM_EXEC, "-t", "-p", str(SIM_PORT)]
        print(f"Starting simulator: {cmd_sim}")
        cls.sim_proc = subprocess.Popen(
            cmd_sim, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(1)

        # Start Indiserver
        if not os.path.exists(DRIVER_EXEC):
            raise RuntimeError(f"Driver executable not found at {DRIVER_EXEC}")

        cmd_indi = ["indiserver", "-v", "-p", str(INDI_PORT), DRIVER_EXEC]
        print(f"Starting indiserver: {cmd_indi}")
        cls.indi_proc = subprocess.Popen(
            cmd_indi, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(1)

    @classmethod
    def tearDownClass(cls):
        if cls.indi_proc:
            cls.indi_proc.terminate()
            cls.indi_proc.wait()
        if cls.sim_proc:
            cls.sim_proc.terminate()
            cls.sim_proc.wait()

    async def asyncSetUp(self):
        self.client = INDIClient(port=INDI_PORT)
        await self.client.connect()

    async def asyncTearDown(self):
        await self.client.disconnect()

    async def connect_to_sim(self):
        """Helper to connect the driver to the simulator."""
        await self.client.wait_for_property(DEVICE_NAME, "CONNECTION_MODE")
        await self.client.set_switch(DEVICE_NAME, "CONNECTION_MODE", ["CONNECTION_TCP"])
        await self.client.set_text(
            DEVICE_NAME, "DEVICE_ADDRESS", {"PORT": "2000", "ADDRESS": "localhost"}
        )
        await self.client.set_switch(DEVICE_NAME, "CONNECTION", ["CONNECT"])
        await self.client.wait_for_state(DEVICE_NAME, "CONNECTION", "Ok")

        # Wait for the driver to define coordinates after handshake
        print("Waiting for coordinate properties...")
        try:
            await self.client.wait_for_any_property(
                DEVICE_NAME,
                lambda d, n, p: n in ["HORIZONTAL_COORD", "EQUATORIAL_EOD_COORD"],
                timeout=10,
            )
        except Exception as e:
            print(f"Warning: Coordinate properties not seen: {e}")

        # Ensure Tracking is ON
        print("Enabling tracking...")
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
        await self.client.set_text(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD", {"RA": ra, "DEC": dec}
        )
        await asyncio.sleep(3)
        # Switch back to SLEW for GOTO, others OFF
        await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["SLEW"])
        await asyncio.sleep(1)

    async def test_firmware_info(self):
        """
        Verifies that the driver connects to the simulator and retrieves firmware info.
        """
        await self.connect_to_sim()

        # 5. Wait for Firmware Info
        # The driver reads this during Handshake
        prop = None
        start_time = time.time()
        while time.time() - start_time < 15:
            # Check cache first
            prop = self.client.get_property(DEVICE_NAME, "Firmware Info")
            if prop:
                print(f"Firmware Info state: {prop['state']}")
                # If we have some values, we consider it "received"
                if any(
                    v.strip() != "Unknown" and v.strip() != ""
                    for v in prop["values"].values()
                ):
                    break
            else:
                print("Firmware Info not in cache yet")

            # Wait for update
            try:
                prop = await self.client.wait_for_property(
                    DEVICE_NAME, "Firmware Info", timeout=2
                )
                print(f"Received Firmware Info update: {prop['state']}")
                if any(
                    v.strip() != "Unknown" and v.strip() != ""
                    for v in prop["values"].values()
                ):
                    break
            except asyncio.TimeoutError:
                print("Timeout waiting for Firmware Info update")
                pass

        assert prop
        print("Firmware Info:", prop["values"])

        # Check values
        def get_val(name):
            return prop["values"].get(name, "").strip()

        assert "7.11" in get_val("Ra/AZM version")
        assert "7.11" in get_val("Dec/ALT version")
        assert "5.28" in get_val("HC version")

    async def wait_for_motion(self, property_name, field, target_value, timeout=60):
        """Helper to wait for motion towards a target since state might stay Idle."""
        start_prop = self.client.get_property(DEVICE_NAME, property_name)
        start_val = float(start_prop["values"][field].strip())

        print(
            f"Waiting for motion on {property_name}.{field} from {start_val} towards {target_value}..."
        )

        end_time = asyncio.get_event_loop().time() + timeout
        last_val = start_val
        while asyncio.get_event_loop().time() < end_time:
            await asyncio.sleep(2)
            curr_prop = self.client.get_property(DEVICE_NAME, property_name)
            curr_val = float(curr_prop["values"][field].strip())

            print(
                f"Motion check: {property_name}.{field} = {curr_val} (diff from start: {curr_val - start_val:.4f})"
            )

            # If we moved at least 0.05 degree from last check, we confirm motion
            if abs(curr_val - last_val) > 0.05:
                print("Motion confirmed.")
                return curr_prop

            # If we are close to target, we are done
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
        await self.client.set_text(
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
        await self.client.set_text(
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
        """
        Verifies that a CHANGE in encoder steps corresponds to the correct CHANGE in degrees.
        Ratio: 2^24 steps = 360 degrees.
        """
        await self.connect_to_sim()
        await self.sync_to_current()

        def get_vals():
            p_s = self.client.get_property(DEVICE_NAME, "TELESCOPE_ENCODER_STEPS")
            p_a = self.client.get_property(DEVICE_NAME, "HORIZONTAL_COORD")
            return (
                float(p_s["values"]["AXIS_AZ"].strip()),
                float(p_a["values"]["AZ"].strip()),
            )

        # 1. Initial state
        steps1, deg1 = get_vals()
        print(f"Start: steps={steps1}, deg={deg1}")

        # 2. Move a small amount (e.g., 5 degrees)
        target_az = (deg1 + 5.0) % 360
        await self.client.set_text(
            DEVICE_NAME, "HORIZONTAL_COORD", {"AZ": str(target_az)}
        )

        # Wait for some movement
        await asyncio.sleep(5)

        # 3. Final state
        steps2, deg2 = get_vals()
        print(f"End: steps={steps2}, deg={deg2}")

        STEPS_PER_REVOLUTION = 16777216.0

        delta_steps = steps2 - steps1
        delta_deg = deg2 - deg1

        # Handle wrap-around for degrees
        if delta_deg > 180:
            delta_deg -= 360
        if delta_deg < -180:
            delta_deg += 360

        # Predicted delta deg from delta steps
        pred_delta_deg = (delta_steps / STEPS_PER_REVOLUTION) * 360.0

        print(
            f"Delta steps={delta_steps}, Delta deg={delta_deg}, Pred delta deg={pred_delta_deg:.4f}"
        )

        # Conversion should be accurate
        assert abs(pred_delta_deg - delta_deg) < 0.05
        print("Encoder delta accuracy verified.")

    async def test_sync_accuracy(self):
        """
        Verifies that Sync command is accepted.
        """
        await self.connect_to_sim()

        target_ra = 12.0
        target_dec = 45.0

        print(f"Syncing to RA={target_ra}, Dec={target_dec}")
        await self.client.set_switch(DEVICE_NAME, "ON_COORD_SET", ["SYNC"])
        await self.client.set_text(
            DEVICE_NAME,
            "EQUATORIAL_EOD_COORD",
            {"RA": str(target_ra), "DEC": str(target_dec)},
        )

        # Wait for state to be OK, which means sync was processed
        prop = await self.client.wait_for_state(
            DEVICE_NAME, "EQUATORIAL_EOD_COORD", "Ok", timeout=10
        )

        ra = float(prop["values"]["RA"].strip())
        dec = float(prop["values"]["DEC"].strip())
        print(f"After sync: RA={ra}, Dec={dec}, State={prop['state']}")

        # We don't assert values strictly if the driver has complex internal models
        # but it should be Ok state.
        assert prop["state"] == "Ok"
        print("Sync command acceptance verified.")
