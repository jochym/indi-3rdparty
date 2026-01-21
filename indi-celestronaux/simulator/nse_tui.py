"""
Textual-based TUI for the Celestron AUX Simulator.
"""

from datetime import datetime, timezone
from collections import deque
from typing import Deque, Any, Dict
import ephem
from math import pi
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Log
from textual.containers import Horizontal, Vertical
from textual.binding import Binding

try:
    from .nse_telescope import NexStarScope, repr_angle
except ImportError:
    from nse_telescope import NexStarScope, repr_angle


class SimulatorApp(App):
    """Textual application for the NexStar AUX Simulator."""

    CSS = """
    Screen {
        background: #1a1b26;
    }
    
    #main-layout {
        height: 100%;
    }
    
    #left-panel {
        width: 30%;
        border: solid #414868;
        padding: 1;
    }
    
    #right-panel {
        width: 70%;
        border: solid #414868;
        padding: 1;
    }
    
    .panel-title {
        text-style: bold;
        color: #7aa2f7;
        margin-bottom: 1;
    }
    
    .cyan { color: #7dcfff; }
    .yellow { color: #e0af68; }
    .blue { color: #7aa2f7; }
    .green { color: #9ece6a; }
    .magenta { color: #bb9af7; }
    .red { color: #f7768e; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("p", "park", "Park", show=True),
        Binding("u", "unpark", "Unpark", show=True),
    ]

    def __init__(
        self,
        tel: NexStarScope,
        obs: ephem.Observer,
        args: Any,
        obs_cfg: Dict[str, Any],
    ) -> None:
        super().__init__()
        self.telescope = tel
        self.obs = obs
        self.args = args
        self.obs_cfg = obs_cfg
        self.ra_samples: Deque[float] = deque(maxlen=10)
        self.dec_samples: Deque[float] = deque(maxlen=10)
        self.time_samples: Deque[datetime] = deque(maxlen=10)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-layout"):
            with Vertical(id="left-panel"):
                yield Static("MOUNT POSITION", classes="panel-title")
                yield Static(id="pos-alt")
                yield Static(id="pos-azm")
                yield Static(id="vel-alt")
                yield Static(id="vel-azm")
                yield Static("")
                yield Static(id="pos-ra")
                yield Static(id="pos-dec")
                yield Static(id="vel-ra")
                yield Static(id="vel-dec")
                yield Static("")
                yield Static("STATUS & TELEMETRY", classes="panel-title")
                yield Static(id="status-mode")
                yield Static(id="status-tracking")
                yield Static(id="status-battery")
                yield Static("")
                yield Static("IMPERFECTIONS", classes="panel-title")
                yield Static(id="imp-backlash")
                yield Static(id="imp-pe")
                yield Static(id="imp-cone")
                yield Static(id="imp-jitter")
                yield Static(id="imp-nonperp")
                yield Static(id="imp-drift")

            with Vertical(id="right-panel"):
                yield Static("AUX BUS LOG", classes="panel-title")
                yield Log(id="aux-log")
                yield Static("")
                yield Static("SYSTEM MESSAGES", classes="panel-title")
                yield Log(id="sys-messages")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.1, self.update_stats)
        self.log_sys(f"Simulator started on port {self.args.port}")
        self.log_sys(f"Stellarium server on port {self.args.stellarium}")
        self.log_sys(f"Location: {self.obs_cfg.get('name', 'Default')}")

    def update_stats(self) -> None:
        alt_str = repr_angle(self.telescope.alt, signed=True)
        azm_str = repr_angle(self.telescope.azm)

        v_alt = self.telescope.alt_rate * 360.0
        v_azm = self.telescope.azm_rate * 360.0

        now = datetime.now(timezone.utc)
        self.obs.date = ephem.Date(now)
        self.obs.epoch = self.obs.date
        sky_azm, sky_alt = self.telescope.get_sky_altaz()
        rajnow, decjnow = self.obs.radec_of(sky_azm * 2 * pi, sky_alt * 2 * pi)

        self.ra_samples.append(float(rajnow))
        self.dec_samples.append(float(decjnow))
        self.time_samples.append(now)

        v_ra = 0.0
        v_dec = 0.0
        if len(self.time_samples) > 1:
            dt = (self.time_samples[-1] - self.time_samples[0]).total_seconds()
            if dt > 0:
                d_ra = self.ra_samples[-1] - self.ra_samples[0]
                if d_ra > pi:
                    d_ra -= 2 * pi
                if d_ra < -pi:
                    d_ra += 2 * pi
                d_dec = self.dec_samples[-1] - self.dec_samples[0]
                v_ra = (d_ra * (180.0 / pi)) / dt
                v_dec = (d_dec * (180.0 / pi)) / dt

        mode = (
            "SLEWING"
            if self.telescope.slewing
            else ("GUIDING" if self.telescope.guiding else "IDLE")
        )
        tracking = "ON" if self.telescope.guiding else "OFF"
        battery = f"{self.telescope.bat_voltage / 1e6:.2f}V"

        self.query_one("#pos-alt", Static).update(f"Alt: [cyan]{alt_str}[/cyan]")
        self.query_one("#pos-azm", Static).update(f"Azm: [cyan]{azm_str}[/cyan]")
        self.query_one("#vel-alt", Static).update(f"vAlt: [blue]{v_alt:+.4f}°/s[/blue]")
        self.query_one("#vel-azm", Static).update(f"vAzm: [blue]{v_azm:+.4f}°/s[/blue]")

        self.query_one("#pos-ra", Static).update(f"RA:  [yellow]{rajnow}[/yellow]")
        self.query_one("#pos-dec", Static).update(f"Dec: [yellow]{decjnow}[/yellow]")
        self.query_one("#vel-ra", Static).update(
            f'vRA:  [blue]{v_ra * 3600:+.2f}"/s[/blue]'
        )
        self.query_one("#vel-dec", Static).update(
            f'vDec: [blue]{v_dec * 3600:+.2f}"/s[/blue]'
        )

        self.query_one("#status-mode", Static).update(f"Mode: [green]{mode}[/green]")
        self.query_one("#status-tracking", Static).update(
            f"Tracking: [magenta]{tracking}[/magenta]"
        )
        self.query_one("#status-battery", Static).update(
            f"Battery: [red]{battery}[/red]"
        )

        self.query_one("#imp-backlash", Static).update(
            f"Backlash: [cyan]{self.telescope.backlash_steps}[/cyan] steps"
        )
        pe_arcsec = self.telescope.pe_amplitude * 360 * 3600
        self.query_one("#imp-pe", Static).update(
            f'Periodic Error: [cyan]{pe_arcsec:.1f}[/cyan]"'
        )
        cone_arcmin = self.telescope.cone_error * 360 * 60
        self.query_one("#imp-cone", Static).update(
            f"Cone Error: [cyan]{cone_arcmin:.1f}[/cyan]'"
        )
        jitter_steps = self.telescope.jitter_sigma * 16777216
        self.query_one("#imp-jitter", Static).update(
            f"Jitter: [cyan]{jitter_steps:.1f}[/cyan] steps"
        )
        nonperp_arcmin = self.telescope.non_perp * 360 * 60
        self.query_one("#imp-nonperp", Static).update(
            f"Non-perp: [cyan]{nonperp_arcmin:.1f}[/cyan]'"
        )
        self.query_one("#imp-drift", Static).update(
            f"Clock Drift: [cyan]{self.telescope.clock_drift * 100:.3f}%[/cyan]"
        )

        while self.telescope.cmd_log:
            entry = self.telescope.cmd_log.popleft()
            self.query_one("#aux-log", Log).write_line(
                f"[blue]{datetime.now().strftime('%H:%M:%S')}[/blue] {entry}"
            )

        while self.telescope.msg_log:
            msg = self.telescope.msg_log.popleft()
            self.log_sys(msg)

    def log_sys(self, message: str) -> None:
        self.query_one("#sys-messages", Log).write_line(
            f"[blue]{datetime.now().strftime('%H:%M:%S')}[/blue] {message}"
        )

    async def action_park(self) -> None:
        self.log_sys("Parking request...")
        self.telescope.trg_alt = 0
        self.telescope.trg_azm = 0
        self.telescope.slewing = self.telescope.goto = True

    async def action_unpark(self) -> None:
        self.log_sys("Unparking...")
        self.telescope.slewing = self.telescope.goto = False
