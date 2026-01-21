"""
NexStar Telescope Emulation Core

This module provides the `NexStarScope` class which emulates the behavior
of a Celestron mount's Motor Controllers (MC) and other devices on the AUX bus.
It handles motion physics, command processing, and state management.
"""

import struct
import sys
import random
from math import pi, sin
import curses
from collections import deque
import binascii
from typing import List, Tuple, Dict, Any, Optional, Union, Deque

# ID tables from Celestron AUX Protocol
targets = {
    "ANY": 0x00,
    "MB": 0x01,  # Main Board
    "HC": 0x04,  # Hand Controller
    "UKN1": 0x05,
    "HC+": 0x0D,
    "AZM": 0x10,  # Azimuth / RA Motor
    "ALT": 0x11,  # Altitude / Dec Motor
    "APP": 0x20,  # Software Application
    "GPS": 0xB0,
    "UKN2": 0xB4,
    "WiFi": 0xB5,
    "BAT": 0xB6,
    "CHG": 0xB7,
    "LIGHT": 0xBF,
}
trg_names = {value: key for key, value in targets.items()}

commands = {
    "MC_GET_POSITION": 0x01,
    "MC_GOTO_FAST": 0x02,
    "MC_SET_POSITION": 0x04,
    "MC_GET_MODEL": 0x05,
    "MC_SET_POS_GUIDERATE": 0x06,
    "MC_SET_NEG_GUIDERATE": 0x07,
    "MC_LEVEL_START": 0x0B,
    "MC_SET_POS_BACKLASH": 0x10,
    "MC_SET_NEG_BACKLASH": 0x11,
    "MC_SLEW_DONE": 0x13,
    "MC_GOTO_SLOW": 0x17,
    "MC_AT_INDEX": 0x18,
    "MC_SEEK_INDEX": 0x19,
    "MC_SET_MAXRATE": 0x20,
    "MC_GET_MAXRATE": 0x21,
    "MC_ENABLE_MAXRATE": 0x22,
    "MC_MAXRATE_ENABLED": 0x23,
    "MC_MOVE_POS": 0x24,
    "MC_MOVE_NEG": 0x25,
    "MC_ENABLE_CORDWRAP": 0x38,
    "MC_DISABLE_CORDWRAP": 0x39,
    "MC_SET_CORDWRAP_POS": 0x3A,
    "MC_POLL_CORDWRAP": 0x3B,
    "MC_GET_CORDWRAP_POS": 0x3C,
    "MC_GET_POS_BACKLASH": 0x40,
    "MC_GET_NEG_BACKLASH": 0x41,
    "MC_GET_AUTOGUIDE_RATE": 0x47,
    "MC_GET_APPROACH": 0xFC,
    "MC_SET_APPROACH": 0xFD,
    "SIM_GET_SKY_POSITION": 0xFF,
    "GET_VER": 0xFE,
}
cmd_names = {value: key for key, value in commands.items()}

# Commands that trigger an immediate ACK (return same command)
ACK_CMDS = [0x02, 0x04, 0x06, 0x24]

# Slew rates mapping (index 0-9 to deg/sec)
RATES = {
    0: 0.0,
    1: 0.008 / 360,  # ~2x sidereal
    2: 0.017 / 360,  # ~4x sidereal
    3: 0.033 / 360,  # ~8x sidereal
    4: 0.067 / 360,  # ~16x sidereal
    5: 0.133 / 360,  # ~32x sidereal
    6: 0.5 / 360,  # 0.5 deg/s
    7: 1.0 / 360,  # 1.0 deg/s
    8: 2.0 / 360,  # 2.0 deg/s
    9: 4.0 / 360,  # 4.0 deg/s (Max for Evolution)
}


def decode_command(cmd: bytes) -> Tuple[int, int, int, int, bytes, int]:
    """Decodes a raw AUX packet into its components."""
    return (cmd[3], cmd[1], cmd[2], cmd[0], cmd[4:-1], cmd[-1])


def split_cmds(data: bytes) -> List[bytes]:
    """Splits a stream of bytes into individual AUX packets based on start byte ';'."""
    cmds = []
    b = 0
    while True:
        try:
            p = data.index(b";", b)
            length = abs(int(data[p + 1]))
            cmds.append(data[p + 1 : p + length + 3])
            b = p + length + 3
        except (ValueError, IndexError):
            return cmds


def make_checksum(data: bytes) -> int:
    """Calculates 2's complement checksum for AUX packet."""
    return (~sum([c for c in bytes(data)]) + 1) & 0xFF


def f2dms(f: float) -> Tuple[int, int, float]:
    """Converts fraction of rotation [0,1] to (Degrees, Minutes, Seconds)."""
    d = 360 * abs(f)
    dd = int(d)
    mm = int((d - dd) * 60)
    ss = (d - dd - mm / 60) * 3600
    return dd, mm, ss


def repr_angle(a: float, signed: bool = False) -> str:
    """Returns a string representation of an angle in DMS format."""
    deg = a * 360.0
    if signed:
        if deg > 180:
            deg -= 360.0
        elif deg < -180:
            deg += 360.0
    else:
        deg = deg % 360.0

    sign = "-" if deg < 0 else " "
    d = abs(deg)
    dd = int(d)
    mm = int((d - dd) * 60)
    ss = (d - dd - mm / 60) * 3600
    return "%s%03d°%02d'%04.1f\"" % (sign if signed else "", dd, mm, ss)


def pack_int3(f: float) -> bytes:
    """Packs a float [0,1] into 3 bytes big-endian (NexStar format)."""
    return struct.pack("!i", int((f % 1.0) * (2**24)))[1:]


def unpack_int3(d: bytes) -> float:
    """Unpacks 3 bytes into a float [0,1]."""
    return struct.unpack("!i", b"\x00" + d[:3])[0] / 2**24


def unpack_int2(d: bytes) -> int:
    """Unpacks 2 bytes into an integer."""
    return struct.unpack("!i", b"\x00\x00" + d[:2])[0]


class NexStarScope:
    """
    Simulated NexStar Telescope Mount.

    Handles physics of movement, command handlers for motor controllers,
    and optional TUI display.
    """

    __mcfw_ver = (7, 11, 5100 // 256, 5100 % 256)
    __hcfw_ver = (5, 28, 5300 // 256, 5300 % 256)
    __mbfw_ver = (1, 0, 0, 1)

    def __init__(
        self,
        ALT: float = 0.0,
        AZM: float = 0.0,
        tui: bool = True,
        stdscr: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.tui = tui
        self.config = config or {}
        self.alt = ALT
        self.azm = AZM

        # Imperfections state
        imp = self.config.get("simulator", {}).get("imperfections", {})
        self.backlash_steps = imp.get("backlash_steps", 0)
        self.pe_amplitude = imp.get("periodic_error_arcsec", 0.0) / (360.0 * 3600.0)
        self.pe_period = imp.get("periodic_error_period_sec", 480.0)
        self.cone_error = imp.get("cone_error_arcmin", 0.0) / (360.0 * 60.0)
        self.non_perp = imp.get("non_perpendicularity_arcmin", 0.0) / (360.0 * 60.0)
        self.refraction_enabled = imp.get("refraction_enabled", False)
        self.jitter_sigma = imp.get("encoder_jitter_steps", 0) / 16777216.0
        self.clock_drift = imp.get("clock_drift", 0.0)  # e.g. 0.001 for 0.1% drift
        self.sim_time = 0.0

        # Backlash management
        self.azm_last_dir = 0  # 1 for pos, -1 for neg
        self.alt_last_dir = 0
        self.azm_backlash_rem = 0.0
        self.alt_backlash_rem = 0.0

        self.trg_alt = self.alt
        self.trg_azm = self.azm
        self.alt_rate = 0.0
        self.azm_rate = 0.0
        self.alt_approach = 0
        self.azm_approach = 0
        self.last_cmd = ""
        self.slewing = False
        self.guiding = False
        self.goto = False
        self.alt_guiderate = 0.0
        self.azm_guiderate = 0.0
        self.alt_maxrate = 10000  # 10.0 deg/s
        self.azm_maxrate = 10000
        self.use_maxrate = False

        self.cmd_log: Deque[str] = deque(maxlen=30)
        self.msg_log: Deque[str] = deque(maxlen=10)
        self.bat_current = 2468
        self.bat_voltage = 12345678
        self.lt_logo = 64
        self.lt_tray = 128
        self.lt_wifi = 255
        self.charge = False
        self.cordwrap = False
        self.cordwrap_pos = 0.0
        self.alt_min = -22.5 / 360.0  # Default limits for a typical mount
        self.alt_max = 90.0 / 360.0
        self.focus_pos = 100000
        self.gps_lat: Union[List[int], Tuple[int, ...]] = [
            50,
            10,
            56,
            0,
        ]  # 50d 10' 56" N
        self.gps_lon: Union[List[int], Tuple[int, ...]] = [
            19,
            47,
            33,
            0,
        ]  # 19d 47' 33" E
        self.gps_linked = True

        self._other_handlers = {
            0x10: self.cmd_0x10,
            0x18: self.cmd_0x18,
            0xFE: self.fw_version,
        }
        self._mc_handlers = {
            0x01: self.get_position,
            0x02: self.goto_fast,
            0x04: self.set_position,
            0x05: self.get_model,
            0x06: self.set_pos_guiderate,
            0x07: self.set_neg_guiderate,
            0x0B: self.level_start,
            0x13: self.slew_done,
            0x17: self.goto_slow,
            0x18: self.at_index,
            0x19: self.seek_index,
            0x20: self.set_maxrate,
            0x21: self.get_maxrate,
            0x22: self.enable_maxrate,
            0x23: self.maxrate_enabled,
            0x24: self.move_pos,
            0x25: self.move_neg,
            0x38: self.enable_cordwrap,
            0x39: self.disable_cordwrap,
            0x3A: self.set_cordwrap_pos,
            0x3B: self.get_cordwrap,
            0x3C: self.get_cordwrap_pos,
            0xFC: self.get_approach,
            0xFD: self.set_approach,
            0xFF: self.get_sky_position_aux,
            0xFE: self.fw_version,
        }
        self._focuser_handlers = {
            0x01: self.get_focus_position,
            0x02: self.goto_focus_fast,
            0xFE: self.fw_version,
        }
        self._gps_handlers = {
            0x01: self.get_gps_lat,
            0x02: self.get_gps_long,
            0x31: self.set_gps_lat,
            0x32: self.set_gps_long,
            0x33: self.get_gps_time,
            0x34: self.set_gps_time,
            0x36: self.get_gps_time_valid,
            0x37: self.get_gps_linked,
            0x38: self.get_gps_sats,
            0x3B: self.get_gps_date,
            0x3C: self.set_gps_date,
            0xFE: self.fw_version,
        }
        self._power_handlers = {
            0x01: self.get_pwr_voltage,
            0x02: self.get_pwr_current,
            0x03: self.get_pwr_status,
            0xFE: self.fw_version,
        }
        if tui:
            self.init_dsp(stdscr)

    def set_maxrate(self, data: bytes, snd: int, rcv: int) -> bytes:
        if rcv == 0x11:
            self.alt_maxrate = unpack_int2(data)
        else:
            self.azm_maxrate = unpack_int2(data)
        return b""

    def get_maxrate(self, data: bytes, snd: int, rcv: int) -> bytes:
        return bytes.fromhex("0fa01194")

    def enable_maxrate(self, data: bytes, snd: int, rcv: int) -> bytes:
        self.use_maxrate = bool(data[0])
        return b""

    def maxrate_enabled(self, data: bytes, snd: int, rcv: int) -> bytes:
        return b"\x01" if self.use_maxrate else b"\x00"

    def cmd_0x10(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Generic handler for 0x10 command (Lighting, Battery, Charging)."""
        if rcv == 0xBF:  # LIGHT
            if len(data) == 2:
                if data[0] == 0:
                    self.lt_tray = data[1]
                elif data[0] == 1:
                    self.lt_logo = data[1]
                else:
                    self.lt_wifi = data[1]
                return b""
            elif len(data) == 1:
                if data[0] == 0:
                    return bytes([int(self.lt_tray % 256)])
                elif data[0] == 1:
                    return bytes([int(self.lt_logo % 256)])
                else:
                    return bytes([int(self.lt_wifi % 256)])
        elif rcv == 0xB7:  # CHG
            if len(data):
                self.charge = bool(data[0])
                return b""
            else:
                return bytes([int(self.charge)])
        elif rcv == 0xB6:  # BAT
            self.bat_voltage = int(self.bat_voltage * 0.99)
            return bytes.fromhex("0102") + struct.pack("!i", int(self.bat_voltage))
        return b""

    def cmd_0x18(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Generic handler for 0x18 command (Battery current)."""
        if rcv == 0xB6:  # BAT
            if len(data):
                i = data[0] * 256 + data[1]
                self.bat_current = max(2000, min(5000, i))
            return struct.pack("!i", int(self.bat_current))[-2:]
        return b""

    def get_position(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Returns current MC position as 3-byte fraction with optional jitter."""
        pos = self.alt if rcv == 0x11 else self.azm

        # Add encoder jitter
        if self.jitter_sigma > 0:
            pos += random.gauss(0, self.jitter_sigma)

        return pack_int3(pos)

    def get_sky_altaz(self) -> Tuple[float, float]:
        """
        Returns the actual pointing position in the sky (fraction of 360)
        considering mechanical and optical imperfections.
        """
        sky_alt = self.alt
        sky_azm = self.azm

        # 1. Cone error (Alt offset)
        sky_alt += self.cone_error

        # 2. Non-perpendicularity
        # Affects Azm depending on Alt
        import math

        sky_azm += (
            self.non_perp
            * math.tan(math.radians(max(-80.0, min(80.0, self.alt * 360.0))))
            / 360.0
        )

        # 3. Periodic Error (RA/Azm only)
        if self.pe_period > 0:
            sky_azm += self.pe_amplitude * sin(2 * pi * self.sim_time / self.pe_period)

        # 4. Atmospheric Refraction (Approximate formula)
        if self.refraction_enabled:
            # Simple Bennett's formula for refraction in arcmin:
            # R = 1 / tan(h + 7.31/(h + 4.4))
            h = max(0.1, sky_alt * 360.0)  # degrees
            ref_arcmin = 1.0 / math.tan(math.radians(h + 7.31 / (h + 4.4)))
            sky_alt += ref_arcmin / (60.0 * 360.0)

        return sky_azm % 1.0, sky_alt

    def goto_fast(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Starts a high-speed GOTO movement."""
        self.last_cmd = "GOTO_FAST"
        self.slewing = self.goto = True
        self.guiding = False
        self.alt_guiderate = self.azm_guiderate = 0.0
        r = (self.alt_maxrate if rcv == 0x11 else self.azm_maxrate) / (360e3)
        a = unpack_int3(data)
        if rcv == 0x11:
            # For Altitude, treat values > 0.5 as negative
            if a > 0.5:
                a -= 1.0
            self.trg_alt = a
            self.alt_rate = r if a > self.alt else -r
        else:
            self.trg_azm = a % 1.0
            diff = self.trg_azm - self.azm
            if diff > 0.5:
                diff -= 1.0
            if diff < -0.5:
                diff += 1.0
            self.azm_rate = r if diff > 0 else -r
        return b""

    def set_position(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Sets the internal MC position (Sync)."""
        a = unpack_int3(data)
        if rcv == 0x11:
            if a > 0.5:
                a -= 1.0
            self.alt = self.trg_alt = a
        else:
            self.azm = self.trg_azm = a % 1.0
        return b""

    def get_model(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Returns simulated mount model ID (Evolution)."""
        return bytes.fromhex("1687")

    def _set_guiderate(self, data: bytes, snd: int, rcv: int, factor: int) -> bytes:
        """Helper to set guiding rates."""
        # val is in units of (STEPS_PER_REVOLUTION / (360*3600*1024)) steps/sec
        # We want guiderate in rotations/sec
        val = unpack_int3(data) * (2**24)
        # rate_steps_per_sec = val * (STEPS_PER_REVOLUTION / (360*3600*1024))
        # rate_rot_per_sec = rate_steps_per_sec / STEPS_PER_REVOLUTION = val / (360*3600*1024)
        a = (val * factor) / (360.0 * 3600.0 * 1024.0)
        self.guiding = abs(a) > 0
        if rcv == 0x11:
            self.alt_guiderate = a
        else:
            self.azm_guiderate = a
        return b""

    def set_pos_guiderate(self, data: bytes, snd: int, rcv: int) -> bytes:
        return self._set_guiderate(data, snd, rcv, 1)

    def set_neg_guiderate(self, data: bytes, snd: int, rcv: int) -> bytes:
        return self._set_guiderate(data, snd, rcv, -1)

    def level_start(self, data: bytes, snd: int, rcv: int) -> bytes:
        return b""

    def goto_slow(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Starts a low-speed precision GOTO movement."""
        self.last_cmd = "GOTO_SLOW"
        self.slewing = self.goto = True
        self.guiding = False
        r = 0.5 / 360  # 0.5 deg/s (Precision approach)
        a = unpack_int3(data)

        if rcv == 0x11:
            if a > 0.5:
                a -= 1.0
            self.trg_alt = a
            self.alt_rate = r if a > self.alt else -r
        else:
            self.trg_azm = a % 1.0
            diff = self.trg_azm - self.azm
            if diff > 0.5:
                diff -= 1.0
            if diff < -0.5:
                diff += 1.0
            self.azm_rate = r if diff > 0 else -r
        return b""

    def slew_done(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Checks if slew movement is finished."""
        rate = self.alt_rate if rcv == 0x11 else self.azm_rate
        # Use epsilon check to match tick() logic
        eps = 1e-6 if self.last_cmd != "GOTO_FAST" else 1e-4
        return b"\x00" if abs(rate) > eps else b"\xff"

    def at_index(self, data: bytes, snd: int, rcv: int) -> bytes:
        return b"\x00"

    def seek_index(self, data: bytes, snd: int, rcv: int) -> bytes:
        return b""

    def move_pos(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Starts a constant-rate positive movement."""
        self.last_cmd = "MOVE_POS"
        self.slewing = True
        self.goto = False
        r = RATES[int(data[0])]
        if rcv == 0x11:
            self.alt_rate = r
        else:
            self.azm_rate = r
        return b""

    def move_neg(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Starts a constant-rate negative movement."""
        self.last_cmd = "MOVE_NEG"
        self.slewing = True
        self.goto = False
        r = RATES[int(data[0])]
        if rcv == 0x11:
            self.alt_rate = -r
        else:
            self.azm_rate = -r
        return b""

    def enable_cordwrap(self, data: bytes, snd: int, rcv: int) -> bytes:
        self.cordwrap = True
        return b""

    def disable_cordwrap(self, data: bytes, snd: int, rcv: int) -> bytes:
        self.cordwrap = False
        return b""

    def set_cordwrap_pos(self, data: bytes, snd: int, rcv: int) -> bytes:
        self.cordwrap_pos = unpack_int3(data)
        return b""

    def get_cordwrap(self, data: bytes, snd: int, rcv: int) -> bytes:
        return b"\xff" if self.cordwrap else b"\x00"

    def get_cordwrap_pos(self, data: bytes, snd: int, rcv: int) -> bytes:
        return pack_int3(self.cordwrap_pos)

    def get_autoguide_rate(self, data: bytes, snd: int, rcv: int) -> bytes:
        return b"\xf0"

    def get_focus_position(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Returns simulated focuser position."""
        return pack_int3(self.focus_pos / 16777216.0)

    def goto_focus_fast(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Moves simulated focuser."""
        self.focus_pos = int(unpack_int3(data) * 16777216.0)
        return b""

    def get_gps_lat(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Returns simulated GPS latitude."""
        return bytes(self.gps_lat)

    def get_gps_long(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Returns simulated GPS longitude."""
        return bytes(self.gps_lon)

    def set_gps_lat(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Sets simulated GPS latitude."""
        self.gps_lat = list(data)
        return b""

    def set_gps_long(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Sets simulated GPS longitude."""
        self.gps_lon = list(data)
        return b""

    def get_gps_time_valid(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Checks if GPS time is valid."""
        return b"\x01"

    def get_gps_linked(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Checks if GPS is linked."""
        return b"\x01" if self.gps_linked else b"\x00"

    def get_gps_sats(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Returns simulated GPS satellite count."""
        return b"\x0c"  # 12 satellites

    def get_gps_time(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Returns simulated GPS time [HH, MM, SS]."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        return bytes([now.hour, now.minute, now.second])

    def set_gps_time(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Sets simulated GPS time."""
        # For simulation, we just acknowledge
        return b""

    def get_gps_date(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Returns simulated GPS date [MM, DD, YY]."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        return bytes([now.month, now.day, now.year % 100])

    def set_gps_date(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Sets simulated GPS date."""
        return b""

    def get_pwr_voltage(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Returns simulated battery voltage in millivolts."""
        # self.bat_voltage is already in microvolts in existing code
        return pack_int3(self.bat_voltage / 1000.0)

    def get_pwr_current(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Returns simulated current in milliamps."""
        # Simulate some current consumption
        current = 200.0  # mA idle
        if self.slewing:
            current += 1000.0  # mA slewing
        return pack_int3(current)

    def get_pwr_status(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Returns power status (0=Discharging, 1=Charging)."""
        return b"\x01" if self.charge else b"\x00"

    def get_approach(self, data: bytes, snd: int, rcv: int) -> bytes:
        return bytes((self.alt_approach if rcv == 0x11 else self.azm_approach,))

    def set_approach(self, data: bytes, snd: int, rcv: int) -> bytes:
        if rcv == 0x11:
            self.alt_approach = data[0]
        else:
            self.azm_approach = data[0]
        return b""

    def get_sky_position_aux(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Returns the actual sky position (with imperfections) as 3-byte fraction."""
        sky_azm, sky_alt = self.get_sky_altaz()
        pos = sky_alt if rcv == 0x11 else sky_azm
        return pack_int3(pos)

    def fw_version(self, data: bytes, snd: int, rcv: int) -> bytes:
        """Returns firmware version bytes for the target device."""
        if rcv in (0x10, 0x11):
            return bytes(NexStarScope.__mcfw_ver)
        if rcv == 0x01:
            return bytes(NexStarScope.__mbfw_ver)
        if rcv in (0x04, 0x0D):
            return bytes(NexStarScope.__hcfw_ver)
        return b""

    def init_dsp(self, stdscr: Optional[Any]) -> None:
        """Initializes curses-based display windows."""
        self.scr = stdscr
        if stdscr:
            self.cmd_log_w = curses.newwin(32, 60, 0, 50)
            self.state_w = curses.newwin(1, 80, 0, 0)
            self.pos_w = curses.newwin(4, 25, 1, 0)
            self.trg_w = curses.newwin(4, 25, 1, 25)
            self.rate_w = curses.newwin(4, 25, 5, 0)
            self.guide_w = curses.newwin(4, 25, 5, 25)
            self.other_w = curses.newwin(8, 50, 9, 0)
            self.msg_w = curses.newwin(12, 50, 17, 0)
            stdscr.refresh()

    def update_dsp(self) -> None:
        """Updates curses display with current telescope state."""
        if not self.scr:
            return
        mode = "Slewing" if self.slewing else ("Guiding" if self.guiding else "Idle")
        self.state_w.clear()
        self.state_w.addstr(0, 1, "State: %8s" % mode)
        self.state_w.refresh()

        self.pos_w.clear()
        self.pos_w.border()
        self.pos_w.addstr(1, 3, "Alt: " + repr_angle(self.alt, signed=True))
        self.pos_w.addstr(2, 3, "Azm: " + repr_angle(self.azm))
        self.pos_w.refresh()

        self.trg_w.clear()
        self.trg_w.border()
        self.trg_w.addstr(1, 3, "Alt: " + repr_angle(self.trg_alt, signed=True))
        self.trg_w.addstr(2, 3, "Azm: " + repr_angle(self.trg_azm))
        self.trg_w.refresh()

        self.rate_w.clear()
        self.rate_w.border()
        self.rate_w.addstr(1, 3, "Alt: %+8.4f °/s" % (self.alt_rate * 360))
        self.rate_w.addstr(2, 3, "Azm: %+8.4f °/s" % (self.azm_rate * 360))
        self.rate_w.refresh()

        self.other_w.clear()
        self.other_w.border()
        self.other_w.addstr(1, 3, "BAT: %9.6f V" % (self.bat_voltage / 1e6))
        self.other_w.addstr(6, 3, "Cordwrap: %3s" % ("On" if self.cordwrap else "Off"))
        self.other_w.refresh()

        self.cmd_log_w.clear()
        self.cmd_log_w.border()
        for n, cmd in enumerate(self.cmd_log):
            self.cmd_log_w.addstr(n + 1, 1, str(cmd)[:58])
        self.cmd_log_w.refresh()

    def tick(self, interval: float) -> None:
        """Physical model update called on every timer tick."""
        interval *= 1.0 + self.clock_drift
        self.sim_time += interval
        eps = 1e-6 if self.last_cmd != "GOTO_FAST" else 1e-4
        maxrate = 4.5 / 360.0  # Max rate slightly above max GoTo rate

        # 1. Update Azm with backlash
        azm_move = (self.azm_rate + self.azm_guiderate) * interval
        if abs(azm_move) > 1e-15:
            move_dir = 1 if azm_move > 0 else -1
            if move_dir != self.azm_last_dir:
                self.azm_backlash_rem = float(self.backlash_steps) / 16777216.0
                self.azm_last_dir = move_dir

            if self.azm_backlash_rem > 0:
                consumed = min(abs(azm_move), self.azm_backlash_rem)
                self.azm_backlash_rem -= consumed
                if azm_move > 0:
                    azm_move = max(0.0, azm_move - consumed)
                else:
                    azm_move = min(0.0, azm_move + consumed)

        self.azm = (self.azm + azm_move) % 1.0

        # 2. Update Alt with backlash
        alt_move = (self.alt_rate + self.alt_guiderate) * interval
        if abs(alt_move) > 1e-15:
            move_dir = 1 if alt_move > 0 else -1
            if move_dir != self.alt_last_dir:
                self.alt_backlash_rem = float(self.backlash_steps) / 16777216.0
                self.alt_last_dir = move_dir

            if self.alt_backlash_rem > 0:
                consumed = min(abs(alt_move), self.alt_backlash_rem)
                self.alt_backlash_rem -= consumed
                if alt_move > 0:
                    alt_move = max(0.0, alt_move - consumed)
                else:
                    alt_move = min(0.0, alt_move + consumed)

        self.alt += alt_move

        # Enforce limits and zero rate if hitting them
        if self.alt < self.alt_min:
            self.alt = self.alt_min
            if self.alt_rate < 0:
                self.alt_rate = 0.0
        elif self.alt > self.alt_max:
            self.alt = self.alt_max
            if self.alt_rate > 0:
                self.alt_rate = 0.0

        if self.slewing and self.goto:
            for axis in ["azm", "alt"]:
                cur = getattr(self, axis)
                trg = getattr(self, f"trg_{axis}")
                rate_attr = f"{axis}_rate"
                diff = trg - cur
                if axis == "azm":
                    if diff > 0.5:
                        diff -= 1.0
                    elif diff < -0.5:
                        diff += 1.0

                # Special case: If we are at a limit and target is beyond it, we are done
                at_limit = False
                if axis == "alt":
                    if (cur <= self.alt_min + 1e-9 and trg < self.alt_min) or (
                        cur >= self.alt_max - 1e-9 and trg > self.alt_max
                    ):
                        at_limit = True

                if abs(diff) < eps or at_limit:
                    setattr(self, rate_attr, 0.0)
                else:
                    s = 1 if diff > 0 else -1
                    r = min(maxrate, abs(float(getattr(self, rate_attr))))
                    # Use full speed to target if within reach, avoiding oscillations
                    if r * interval >= abs(diff):
                        r = abs(diff) / interval
                    setattr(self, rate_attr, s * r)

        if abs(self.azm_rate) < eps and abs(self.alt_rate) < eps:
            self.slewing = self.goto = False

        if self.tui:
            self.update_dsp()

    def print_msg(self, msg: str) -> None:
        """Adds a message to the internal log deque."""
        if not self.msg_log or msg != self.msg_log[-1]:
            self.msg_log.append(msg)
        if not self.tui:
            print(f"MSG: {msg}")

    def handle_msg(self, msg: bytes) -> bytes:
        """Main entry point for incoming AUX data stream."""
        # self.print_msg(f"Received raw: {msg.hex()}")
        responses = []
        for cmd in split_cmds(msg):
            try:
                c, f, t, l, d, s = decode_command(cmd)
                if make_checksum(cmd[:-1]) != s:
                    self.print_msg(f"Checksum error in cmd: {cmd.hex()}")
                    continue

                # Always echo
                echo = b";" + cmd
                responses.append(echo)

                # Log command
                c_name = cmd_names.get(c, f"0x{c:02x}")
                t_name = trg_names.get(t, f"0x{t:02x}")
                self.cmd_log.append(f"{t_name}: {c_name}")

                if t in (0x10, 0x11):
                    handlers = self._mc_handlers
                elif t == 0x12:
                    handlers = self._focuser_handlers
                elif t == 0xB0:
                    handlers = self._gps_handlers
                elif t in (0xB6, 0xB7):
                    handlers = self._power_handlers
                else:
                    handlers = self._other_handlers

                if c in handlers:
                    resp_data = handlers[c](d, f, t)
                    header = bytes((len(resp_data) + 3, t, f, c))
                    resp_payload = (
                        b";"
                        + header
                        + resp_data
                        + bytes((make_checksum(header + resp_data),))
                    )
                    responses.append(resp_payload)
                else:
                    # self.print_msg(f"No handler for cmd {hex(c)} to {hex(t)}")
                    pass
            except Exception as e:
                self.print_msg(f"Error handling cmd: {e}")
                import traceback

                traceback.print_exc()

        return b"".join(responses)
