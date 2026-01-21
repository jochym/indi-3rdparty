"""
Web-based 3D visualization console for the Celestron AUX Simulator.
"""

import asyncio
import json
import math
from typing import Set, Dict, Any, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn
import os
import ephem

try:
    from .nse_telescope import NexStarScope
except ImportError:
    from nse_telescope import NexStarScope

app = FastAPI()

# Connected WebSocket clients
clients: Set[WebSocket] = set()
# Global geometry config
mount_geometry: Dict[str, Any] = {}


class WebConsole:
    def __init__(
        self,
        telescope: NexStarScope,
        obs: ephem.Observer,
        host: str = "127.0.0.1",
        port: int = 8080,
    ) -> None:
        self.telescope = telescope
        self.obs = obs
        self.host = host
        self.port = port
        self.server_task: Optional[asyncio.Task] = None

        # Load geometry from telescope config
        global mount_geometry
        mount_geometry = self.telescope.config.get("simulator", {}).get(
            "geometry",
            {
                "base_height": 0.18,
                "fork_height": 0.42,
                "fork_width": 0.22,
                "arm_thickness": 0.1,
                "ota_radius": 0.125,
                "ota_length": 0.43,
                "camera_length": 0.12,
            },
        )

    async def broadcast_state(self) -> None:
        """Broadcasts telescope state to all connected clients."""
        from math import pi, degrees, cos, radians

        while True:
            if clients:
                # Update observer time
                self.obs.date = ephem.now()
                self.obs.epoch = self.obs.date

                sky_azm, sky_alt = self.telescope.get_sky_altaz()
                ra, dec = self.obs.radec_of(sky_azm * 2 * pi, sky_alt * 2 * pi)

                # Get nearby stars for schematic sky view
                stars = []
                fov_deg = 30.0  # 30 degree field of view
                for name, body in [
                    ("Polaris", ephem.star("Polaris")),
                    ("Sirius", ephem.star("Sirius")),
                    ("Vega", ephem.star("Vega")),
                    ("Arcturus", ephem.star("Arcturus")),
                    ("Capella", ephem.star("Capella")),
                    ("Rigel", ephem.star("Rigel")),
                    ("Betelgeuse", ephem.star("Betelgeuse")),
                    ("Procyon", ephem.star("Procyon")),
                    ("Altair", ephem.star("Altair")),
                    ("Deneb", ephem.star("Deneb")),
                    ("Spica", ephem.star("Spica")),
                    ("Antares", ephem.star("Antares")),
                    ("Pollux", ephem.star("Pollux")),
                    ("Castor", ephem.star("Castor")),
                ]:
                    try:
                        body.compute(self.obs)
                        # Check if within FOV
                        dist = ephem.separation(
                            (body.az, body.alt), (sky_azm * 2 * pi, sky_alt * 2 * pi)
                        )
                        if dist < radians(fov_deg):
                            # Calculate relative X, Y in FOV [-1, 1]
                            dx = (degrees(body.az) - sky_azm * 360.0) * cos(body.alt)
                            dy = degrees(body.alt) - sky_alt * 360.0
                            stars.append(
                                {
                                    "name": name,
                                    "x": dx / (fov_deg / 2),
                                    "y": dy / (fov_deg / 2),
                                    "mag": body.mag,
                                }
                            )
                    except Exception:
                        continue

                state = {
                    "azm": sky_azm * 360.0,
                    "alt": sky_alt * 360.0,
                    "ra": str(ra),
                    "dec": str(dec),
                    "v_azm": (self.telescope.azm_rate + self.telescope.azm_guiderate)
                    * 360.0,
                    "v_alt": (self.telescope.alt_rate + self.telescope.alt_guiderate)
                    * 360.0,
                    "slewing": self.telescope.slewing,
                    "guiding": self.telescope.guiding,
                    "voltage": self.telescope.bat_voltage / 1e6,
                    "current": 0.2 + (1.0 if self.telescope.slewing else 0.0),
                    "timestamp": self.telescope.sim_time,
                    "stars": stars,
                }
                message = json.dumps(state)
                disconnected = set()
                for client in clients:
                    try:
                        await client.send_text(message)
                    except Exception:
                        disconnected.add(client)

                for d in disconnected:
                    clients.remove(d)

            await asyncio.sleep(0.1)

    def run(self) -> None:
        """Starts the uvicorn server in the background."""
        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="error")
        server = uvicorn.Server(config)
        self.server_task = asyncio.create_task(server.serve())
        asyncio.create_task(self.broadcast_state())


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        clients.remove(websocket)


@app.get("/")
async def get():
    # Inject geometry into the HTML
    html = INDEX_HTML.replace("MOUNT_GEOMETRY_PLACEHOLDER", json.dumps(mount_geometry))
    return HTMLResponse(content=html)


INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Celestron AUX 3D Console</title>
    <style>
        body { margin: 0; overflow: hidden; background: #1a1b26; color: #7aa2f7; font-family: monospace; }
        #info { position: absolute; top: 1vh; left: 1vw; background: rgba(26, 27, 38, 0.8); padding: 1.5vh; border: 1px solid #414868; border-radius: 4px; pointer-events: none; width: 25vw; min-width: 250px; font-size: 1.1vw; }
        #sky-view { position: absolute; top: 1vh; right: 1vw; background: rgba(0, 0, 0, 0.8); border: 1px solid #414868; width: 30vh; height: 30vh; border-radius: 50%; overflow: hidden; }
        #zoom-view { position: absolute; bottom: 1vh; right: 1vw; background: rgba(0, 0, 0, 0.9); border: 2px solid #f7768e; width: 30vh; height: 30vh; border-radius: 4px; overflow: hidden; }
        #controls { position: absolute; bottom: 1vh; left: 1vw; color: #565f89; font-size: 1vw; }
        canvas { display: block; }
        .warning { color: #f7768e; font-weight: bold; }
        .cyan { color: #7dcfff; }
        .green { color: #9ece6a; }
        .blue { color: #7aa2f7; }
        .yellow { color: #e0af68; }
        .magenta { color: #bb9af7; }
        .telemetry-row { display: flex; justify-content: space-between; margin-bottom: 0.5vh; }
        .sky-label { position: absolute; bottom: 1vh; width: 100%; text-align: center; font-size: 1.2vh; color: #565f89; pointer-events: none; }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
</head>
<body>
    <div id="info">
        <h2 style="margin-top:0; border-bottom: 1px solid #414868; padding-bottom: 5px; font-size: 1.5vw;">AUX Digital Twin</h2>
        <div id="telemetry">
            <div class="telemetry-row"><span>AZM:</span> <span id="azm" class="cyan">0.00</span>° (<span id="v_azm" class="blue">0.0</span>°/s)</div>
            <div class="telemetry-row"><span>ALT:</span> <span id="alt" class="cyan">0.00</span>° (<span id="v_alt" class="blue">0.0</span>°/s)</div>
            <div class="telemetry-row"><span>RA:</span> <span id="ra" class="yellow">00:00:00</span></div>
            <div class="telemetry-row"><span>DEC:</span> <span id="dec" class="yellow">+00:00:00</span></div>
            <div class="telemetry-row"><span>Power:</span> <span id="pwr" class="magenta">0.0V</span></div>
            <div class="telemetry-row"><span>Status:</span> <span id="status" class="green">IDLE</span></div>
        </div>
        <div id="collision" class="warning" style="display:none; margin-top:10px">
            ⚠️ POTENTIAL COLLISION DETECTED
        </div>
    </div>
    <div id="sky-view">
        <canvas id="sky-canvas"></canvas>
        <div class="sky-label">FOV 30°</div>
    </div>
    <div id="zoom-view">
        <canvas id="zoom-canvas"></canvas>
        <div class="sky-label">FOV 1°</div>
    </div>
    <div id="controls">Mouse: Rotate | Scroll: Zoom | Right Click: Pan</div>
    <script>
        const geo = MOUNT_GEOMETRY_PLACEHOLDER;
        
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(window.innerWidth, window.innerHeight);
        document.body.appendChild(renderer.domElement);

        const controls = new THREE.OrbitControls(camera, renderer.domElement);

        // Lighting
        const light = new THREE.DirectionalLight(0xffffff, 1);
        light.position.set(5, 10, 5).normalize();
        scene.add(light);
        scene.add(new THREE.AmbientLight(0x404040));

        // Grid & Axis
        scene.add(new THREE.GridHelper(10, 20, 0x414868, 0x24283b));
        
        // --- Utility for text labels ---
        function createLabel(text, color = '#7aa2f7', fontSize = 72, scale = 0.4) {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            canvas.width = 256;
            canvas.height = 256;
            ctx.fillStyle = color;
            ctx.font = `bold ${fontSize}px monospace`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(text, 128, 128);
            const texture = new THREE.CanvasTexture(canvas);
            const spriteMaterial = new THREE.SpriteMaterial({ map: texture });
            const sprite = new THREE.Sprite(spriteMaterial);
            sprite.scale.set(scale, scale, 1);
            return sprite;
        }

        // --- Mount Model ---
        const mountMaterial = new THREE.MeshPhongMaterial({ color: 0x414868 });
        const otaMaterial = new THREE.MeshPhongMaterial({ color: 0x7aa2f7 });
        const cameraMaterial = new THREE.MeshPhongMaterial({ color: 0xbb9af7 });
        const scaleMaterial = new THREE.LineBasicMaterial({ color: 0x565f89 });
        const indicatorMaterial = new THREE.MeshBasicMaterial({ color: 0xf7768e });

        // Base
        const base = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.4, geo.base_height, 32), mountMaterial);
        base.position.y = geo.base_height / 2;
        scene.add(base);

        // Azimuth Scale (Stationary)
        const azScale = new THREE.Group();
        for (let i = 0; i < 360; i += 10) {
            const isMajor = i % 30 === 0;
            const length = isMajor ? 0.08 : 0.04;
            const rad = THREE.MathUtils.degToRad(i);
            const tickGeom = new THREE.BufferGeometry().setFromPoints([
                new THREE.Vector3(Math.sin(rad) * 0.45, 0, Math.cos(rad) * 0.45),
                new THREE.Vector3(Math.sin(rad) * (0.45 + length), 0, Math.cos(rad) * (0.45 + length))
            ]);
            const tick = new THREE.Line(tickGeom, scaleMaterial);
            // Azimuth 0 is North (Z+)
            tick.rotation.y = THREE.MathUtils.degToRad(-i);
            azScale.add(tick);
            
            if (isMajor) {
                const label = createLabel(i.toString(), '#565f89', 72, 0.4);
                label.position.set(Math.sin(rad) * 0.65, 0, Math.cos(rad) * 0.65);
                azScale.add(label);
            }
        }
        azScale.position.y = geo.base_height;
        scene.add(azScale);

        // Azimuth Group (Rotates around Y)
        const azmGroup = new THREE.Group();
        azmGroup.position.y = geo.base_height;
        scene.add(azmGroup);

        // Azimuth Indicator Dot (Red - Viewing Direction Z+)
        const azDot = new THREE.Mesh(new THREE.SphereGeometry(0.02), indicatorMaterial);
        azDot.position.set(0, 0.02, 0.45);
        azmGroup.add(azDot);

        // Cardinal points
        const cardinalN = createLabel("N", "#f7768e", 48, 0.3); cardinalN.position.set(0, geo.base_height, 0.8); scene.add(cardinalN);
        const cardinalS = createLabel("S", "#7aa2f7", 48, 0.3); cardinalS.position.set(0, geo.base_height, -0.8); scene.add(cardinalS);
        const cardinalE = createLabel("E", "#7aa2f7", 48, 0.3); cardinalE.position.set(0.9, geo.base_height, 0); scene.add(cardinalE);
        const cardinalW = createLabel("W", "#7aa2f7", 48, 0.3); cardinalW.position.set(-0.9, geo.base_height, 0); scene.add(cardinalW);

        // Fork Arm
        const arm = new THREE.Mesh(new THREE.BoxGeometry(geo.arm_thickness, geo.fork_height, 0.2), mountMaterial);
        arm.position.set(geo.fork_width, geo.fork_height/2, 0);
        azmGroup.add(arm);

        // Pivot Axis
        const pivot = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, geo.fork_width, 16), mountMaterial);
        pivot.rotation.z = Math.PI / 2;
        pivot.position.set(geo.fork_width/2, geo.fork_height * 0.8, 0);
        azmGroup.add(pivot);

        // Altitude Scale (Vertical radial lines stationary on the fork)
        const altScale = new THREE.Group();
        const altRadius = 0.35;
        for (let i = -20; i <= 90; i += 10) {
            const isMajor = i % 30 === 0;
            const length = isMajor ? 0.08 : 0.04;
            const rad = THREE.MathUtils.degToRad(i);
            const tickGeom = new THREE.BufferGeometry().setFromPoints([
                new THREE.Vector3(0, Math.sin(rad) * altRadius, Math.cos(rad) * altRadius),
                new THREE.Vector3(0, Math.sin(rad) * (altRadius + length), Math.cos(rad) * (altRadius + length))
            ]);
            const tick = new THREE.Line(tickGeom, scaleMaterial);
            altScale.add(tick);
            
            if (isMajor) {
                const label = createLabel(i.toString(), '#565f89', 72, 0.4);
                label.position.set(0.05, Math.sin(rad) * (altRadius + 0.15), Math.cos(rad) * (altRadius + 0.15));
                altScale.add(label);
            }
        }
        altScale.position.set(geo.fork_width + geo.arm_thickness/2, geo.fork_height * 0.8, 0);
        azmGroup.add(altScale);

        // Altitude Group (Rotates around X)
        const altGroup = new THREE.Group();
        altGroup.position.set(0, geo.fork_height * 0.8, 0);
        azmGroup.add(altGroup);

        // Altitude Indicator Dot (Moves with OTA)
        const altDot = new THREE.Mesh(new THREE.SphereGeometry(0.02), indicatorMaterial);
        altDot.position.set(geo.fork_width + geo.arm_thickness/2 + 0.02, 0, altRadius);
        altGroup.add(altDot);

        // OTA
        const ota = new THREE.Mesh(new THREE.CylinderGeometry(geo.ota_radius, geo.ota_radius, geo.ota_length, 32), otaMaterial);
        ota.rotation.x = Math.PI / 2;
        altGroup.add(ota);

        // Visual Back / Camera
        const cam = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.12, geo.camera_length), cameraMaterial);
        cam.position.set(0, 0, -geo.ota_length/2 - geo.camera_length/2);
        altGroup.add(cam);

        camera.position.set(2, 2, 2);
        controls.target.set(0, 0.5, 0);
        controls.update();

        // Sky View Canvas
        const skyCanvas = document.getElementById('sky-canvas');
        const skyCtx = skyCanvas.getContext('2d');
        const zoomCanvas = document.getElementById('zoom-canvas');
        const zoomCtx = zoomCanvas.getContext('2d');

        function resizeSky() {
            const skyCont = document.getElementById('sky-view');
            skyCanvas.width = skyCont.clientWidth;
            skyCanvas.height = skyCont.clientHeight;
            const zoomCont = document.getElementById('zoom-view');
            zoomCanvas.width = zoomCont.clientWidth;
            zoomCanvas.height = zoomCont.clientHeight;
        }
        window.addEventListener('resize', resizeSky);
        resizeSky();

        function drawSkyView(ctx, canvas, stars, fov, isZoom = false) {
            const w = canvas.width;
            const h = canvas.height;
            const center = w / 2;
            
            ctx.fillStyle = 'black';
            ctx.fillRect(0, 0, w, h);
            
            ctx.strokeStyle = isZoom ? '#f7768e' : '#414868';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(center, center - center*0.2); ctx.lineTo(center, center + center*0.2);
            ctx.moveTo(center - center*0.2, center); ctx.lineTo(center + center*0.2, center);
            ctx.stroke();

            if (isZoom) {
                ctx.setLineDash([5, 5]);
                ctx.beginPath(); ctx.arc(center, center, center * (10/60), 0, Math.PI*2); ctx.stroke();
                ctx.beginPath(); ctx.arc(center, center, center * (30/60), 0, Math.PI*2); ctx.stroke();
                ctx.setLineDash([]);
            }

            stars.forEach(s => {
                const scale = 30.0 / fov;
                const px = center + s.x * center * scale;
                const py = center - s.y * center * scale;
                const dist = Math.sqrt(Math.pow(px-center, 2) + Math.pow(py-center, 2));
                if (dist > center) return;

                const size = Math.max(1, (isZoom ? 10 : 7 - s.mag) * (w/600));
                ctx.fillStyle = 'white';
                ctx.beginPath();
                ctx.arc(px, py, size, 0, Math.PI*2);
                ctx.fill();
                if (s.mag < (isZoom ? 4 : 2.5)) {
                    ctx.font = (12 * (w/600)) + 'px monospace';
                    ctx.fillText(s.name, px + 8, py + 8);
                }
            });
        }

        function animate() {
            requestAnimationFrame(animate);
            renderer.render(scene, camera);
        }
        animate();

        const ws = new WebSocket('ws://' + window.location.host + '/ws');
        ws.onmessage = function(event) {
            const data = JSON.parse(event.data);
            document.getElementById('azm').innerText = data.azm.toFixed(2);
            document.getElementById('v_azm').innerText = data.v_azm.toFixed(4);
            document.getElementById('alt').innerText = data.alt.toFixed(2);
            document.getElementById('v_alt').innerText = data.v_alt.toFixed(4);
            document.getElementById('ra').innerText = data.ra;
            document.getElementById('dec').innerText = data.dec;
            document.getElementById('pwr').innerText = data.voltage.toFixed(1) + 'V (' + data.current.toFixed(1) + 'A)';
            document.getElementById('status').innerText = data.slewing ? 'SLEWING' : (data.guiding ? 'TRACKING' : 'IDLE');

            azmGroup.rotation.y = -THREE.MathUtils.degToRad(data.azm);
            altGroup.rotation.x = -THREE.MathUtils.degToRad(data.alt);

            const worldPos = new THREE.Vector3();
            cam.getWorldPosition(worldPos);
            const isCollision = (worldPos.y < geo.base_height + 0.05);
            document.getElementById('collision').style.display = isCollision ? 'block' : 'none';
            otaMaterial.color.setHex(isCollision ? 0xf7768e : 0x7aa2f7);

            drawSkyView(skyCtx, skyCanvas, data.stars || [], 30.0, false);
            drawSkyView(zoomCtx, zoomCanvas, data.stars || [], 1.0, true);
        };

        window.addEventListener('resize', () => {
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight);
        });
    </script>
</body>
</html>
"""
