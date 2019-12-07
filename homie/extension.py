from asyn import launch
from utime import time
from gc import mem_free
from uasyncio import get_event_loop, sleep_ms

from homie import __version__
from homie.constants import MAIN_DELAY
from homie.device import await_ready_state
from homie.utils import get_local_ip, get_local_mac


class Extension:
    def __init__(self):
        self.device = None


class LegacyFirmware(Extension):

    ext_id = b"org.homie.legacy-firmware:0.1.1:[4.x]"

    async def publish_properties(self):
        publish = self.device.publish
        await publish(b"$localip", get_local_ip())
        await publish(b"$mac", get_local_mac())
        await publish(b"$fw/name", b"Microhomie")
        await publish(b"$fw/version", __version__)


class LegacyStats(Extension):

    ext_id = b"org.homie.legacy-stats:0.1.1:[4.x]"

    def __init__(self, interval=60):
        super().__init__()
        self._interval = interval

        # Start stats coro
        launch(self.publish_stats, ())

    async def publish_properties(self):
        publish = self.device.publish
        await publish(b"$stats/interval", self._interval)

    @await_ready_state
    async def publish_stats(self):
        start_time = time()
        delay = self._interval * MAIN_DELAY
        publish = self.device.publish

        while True:
            uptime = time() - start_time
            await publish(b"$stats/uptime", uptime)
            await publish(b"$stats/freeheap", mem_free())
            await sleep_ms(delay)
