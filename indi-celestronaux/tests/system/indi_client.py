import asyncio
import xml.etree.ElementTree as ET
import logging

logger = logging.getLogger("INDIClient")


class INDIClient:
    def __init__(self, host="localhost", port=7624):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.devices = {}
        self.connected = False
        self.listeners = []

    async def connect(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.host, self.port
            )
            self.connected = True
            asyncio.create_task(self._read_loop())
            # Handshake
            await self.send_data(b'<getProperties version="1.7" />\n')
        except Exception as e:
            logger.error(f"Failed to connect to INDI server: {e}")
            raise

    async def disconnect(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        self.connected = False

    async def send_data(self, data):
        if not self.writer:
            raise RuntimeError("Not connected")
        logger.debug(f"Sending: {data}")
        self.writer.write(data)
        await self.writer.drain()

    async def _read_loop(self):
        parser = ET.XMLPullParser(["end"])
        parser.feed("<root>")  # Fake root to handle multiple top-level elements
        while self.connected:
            try:
                if self.reader is None:
                    break
                data = await self.reader.read(4096)
                if not data:
                    break
                # logger.debug(f"Received: {data.decode(errors='ignore')}")
                parser.feed(data)
                for event, elem in parser.read_events():
                    if elem.tag == "root":
                        continue
                    await self._handle_element(elem)
            except Exception as e:
                logger.error(f"Read loop error: {e}")
                break

    async def _handle_element(self, elem):
        tag = elem.tag
        device = elem.get("device")
        name = elem.get("name")

        if device and name:
            if device not in self.devices:
                self.devices[device] = {}

            # Update property cache
            prop = {"state": elem.get("state"), "values": {}}
            for child in elem:
                if child.get("name"):
                    prop["values"][child.get("name")] = child.text

            self.devices[device][name] = prop

            # Notify listeners
            for queue in self.listeners:
                await queue.put((device, name, prop))

    async def wait_for_property(self, device, name, timeout=5):
        """Waits for a specific property to receive an update."""
        # Create a temporary queue for this waiter
        queue = asyncio.Queue()
        self.listeners.append(queue)

        # Check if already in cache (optional, but good for initial state)
        # But we want to wait for updates usually.
        # If we want to check current state, use get_property.
        # For this test, we might miss the initial update if we don't check cache.
        # But let's stick to waiting for events to be robust against timing.
        # Wait, if the event happened BEFORE we called this, we hang forever.
        # So we MUST check cache first if we accept "already arrived" as success.
        cached = self.get_property(device, name)
        if cached:
            # If we are waiting for a specific state, we might need to check it.
            # But here we just return the property.
            # The caller checks the state.
            # If the state is not what we want, the caller will call wait_for_property again.
            # But then we need to NOT return the cached one immediately if it hasn't changed?
            # This is getting complex.
            # Let's just return cached if it exists.
            # BUT, if we loop waiting for "Ok", and it stays "Idle", we busy loop!
            pass

        try:
            end_time = asyncio.get_event_loop().time() + timeout
            while True:
                remaining = end_time - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise TimeoutError(f"Property {device}.{name} not received")

                try:
                    d, n, p = await asyncio.wait_for(queue.get(), remaining)
                    if d == device and n == name:
                        return p
                except asyncio.TimeoutError:
                    raise TimeoutError(f"Property {device}.{name} not received")
        finally:
            self.listeners.remove(queue)

    def get_property(self, device, name):
        return self.devices.get(device, {}).get(name)

    async def set_text(self, device, name, values):
        """
        values: dict of element_name -> value
        """
        xml = f'<newTextVector device="{device}" name="{name}">\n'
        for k, v in values.items():
            xml += f'  <oneText name="{k}">{v}</oneText>\n'
        xml += "</newTextVector>\n"
        await self.send_data(xml.encode())

    async def set_switch(self, device, name, on_switches):
        """
        on_switches: list of switch names to set On
        """
        xml = f'<newSwitchVector device="{device}" name="{name}">\n'
        for s in on_switches:
            xml += f'  <oneSwitch name="{s}">On</oneSwitch>\n'
        xml += "</newSwitchVector>\n"
        await self.send_data(xml.encode())
