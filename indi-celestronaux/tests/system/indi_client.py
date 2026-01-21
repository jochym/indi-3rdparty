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
                events = parser.read_events()
                for event, elem in events:
                    if event == "end":
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
            # logger.info(f"Property update: {device}.{name} = {prop['state']}")

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

    async def wait_for_state(self, device, name, states, timeout=5):
        """Waits for a property to reach one of the specified states."""
        if isinstance(states, str):
            states = [states]

        def condition(prop):
            return prop["state"] in states

        return await self.wait_for_condition(device, name, condition, timeout)

    async def wait_for_any_property(self, device, condition, timeout=5):
        """Waits for any property on a device to satisfy a condition."""
        queue = asyncio.Queue()
        self.listeners.append(queue)

        # Check cache
        if device in self.devices:
            for name, prop in self.devices[device].items():
                if condition(device, name, prop):
                    self.listeners.remove(queue)
                    return name, prop

        try:
            end_time = asyncio.get_event_loop().time() + timeout
            while True:
                remaining = end_time - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise TimeoutError(f"Timeout waiting for property on {device}")

                try:
                    d, n, p = await asyncio.wait_for(queue.get(), remaining)
                    if d == device and condition(d, n, p):
                        return n, p
                except asyncio.TimeoutError:
                    raise TimeoutError(f"Timeout waiting for property on {device}")
        finally:
            if queue in self.listeners:
                self.listeners.remove(queue)

    async def wait_for_condition(self, device, name, condition, timeout=5):
        """Waits for a property to satisfy a condition function."""
        queue = asyncio.Queue()
        self.listeners.append(queue)

        cached = self.get_property(device, name)
        if cached and condition(cached):
            self.listeners.remove(queue)
            return cached

        try:
            end_time = asyncio.get_event_loop().time() + timeout
            while True:
                remaining = end_time - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Timeout waiting for condition on {device}.{name}"
                    )

                try:
                    d, n, p = await asyncio.wait_for(queue.get(), remaining)
                    if d == device and n == name and condition(p):
                        return p
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"Timeout waiting for condition on {device}.{name}"
                    )
        finally:
            if queue in self.listeners:
                self.listeners.remove(queue)

    def get_property(self, device, name):
        return self.devices.get(device, {}).get(name)

    async def send_def_switch(
        self, device, name, label, group, switches, permission="rw", rule="1ofMany"
    ):
        """Sends a defSwitchVector."""
        xml = f'<defSwitchVector device="{device}" name="{name}" label="{label}" group="{group}" state="Idle" perm="{permission}" rule="{rule}">\n'
        for s_name, s_label, s_state in switches:
            xml += f'  <defSwitch name="{s_name}" label="{s_label}">{s_state}</defSwitch>\n'
        xml += "</defSwitchVector>\n"
        await self.send_data(xml.encode())

    async def send_new_switch(self, device, name, on_switches):
        """Sends a newSwitchVector even if the property is not yet known or marked RO."""
        xml = f'<newSwitchVector device="{device}" name="{name}">\n'
        for s in on_switches:
            xml += f'  <oneSwitch name="{s}">On</oneSwitch>\n'
        xml += "</newSwitchVector>\n"
        await self.send_data(xml.encode())

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
        on_switches: list of switch names to set On, others in vector will be Off
        """
        prop = self.get_property(device, name)
        if not prop:
            # If property not known yet, just send the ones requested
            xml = f'<newSwitchVector device="{device}" name="{name}">\n'
            for s in on_switches:
                xml += f'  <oneSwitch name="{s}">On</oneSwitch>\n'
            xml += "</newSwitchVector>\n"
        else:
            xml = f'<newSwitchVector device="{device}" name="{name}">\n'
            for s_name in prop["values"].keys():
                val = "On" if s_name in on_switches else "Off"
                xml += f'  <oneSwitch name="{s_name}">{val}</oneSwitch>\n'
            xml += "</newSwitchVector>\n"

        # print(f"DEBUG: Sending Switch XML:\n{xml}")
        await self.send_data(xml.encode())
