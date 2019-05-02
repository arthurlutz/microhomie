from gc import collect, mem_free
from sys import platform

from asyn import Event
from homie import __version__, utils
from homie.constants import DEVICE_STATE, MAIN_DELAY, QOS, RESTORE_DELAY, SLASH
from mqtt_as import MQTTClient
from uasyncio import get_event_loop, sleep_ms
from utime import time


_EVENT = Event()
def await_ready_state(func):
    def new_gen(*args, **kwargs):
        await _EVENT
        await func(*args, **kwargs)
    return new_gen


class HomieDevice:

    """MicroPython implementation of the Homie MQTT convention for IoT."""

    def __init__(self, settings):
        self._state = "init"
        self._stime = time()

        self.stats_interval = settings.DEVICE_STATS_INTERVAL

        self.nodes = []
        self.callback_topics = {}

        self.device_name = settings.DEVICE_NAME

        self.btopic = settings.MQTT_BASE_TOPIC
        self.dtopic = SLASH.join(
            (settings.MQTT_BASE_TOPIC, settings.DEVICE_ID)
        )

        # setup networking
        utils.setup_network(settings.WIFI_PASSWORD)
        utils.wifi_connect(settings.WIFI_SSID)

        self.mqtt = MQTTClient(
            client_id=settings.DEVICE_ID,
            server=settings.MQTT_BROKER,
            port=settings.MQTT_PORT,
            user=settings.MQTT_USERNAME,
            password=settings.MQTT_PASSWORD,
            keepalive=settings.MQTT_KEEPALIVE,
            ssl=settings.MQTT_SSL,
            ssl_params=settings.MQTT_SSL_PARAMS,
            subs_cb=self.sub_cb,
            connect_coro=self.connection_handler,
            will=(SLASH.join((self.dtopic, DEVICE_STATE)), b"lost", True, QOS),
        )

        # Start coros
        loop = get_event_loop()
        loop.create_task(self.publish_stats())

    def add_node(self, node):
        """add a node class of Homie Node to this device"""
        node.device = self
        self.nodes.append(node)
        loop = get_event_loop()
        loop.create_task(node.publish_data())
        collect()

    def format_topic(self, topic):
        return SLASH.join((self.dtopic, topic))

    async def subscribe(self, topic):
        topic = self.format_topic(topic)
        # print("MQTT SUBSCRIBE: {}".format(topic))
        await self.mqtt.subscribe(topic, QOS)

    async def unsubscribe(self, topic):
        topic = self.format_topic(topic)
        # print("MQTT UNSUBSCRIBE: {}".format(topic))
        await self.mqtt.unsubscribe(topic)

    async def connection_handler(self, client):
        """subscribe to all registered device and node topics"""
        subscribe = self.subscribe
        unsubscribe = self.unsubscribe

        # device topics
        await self.mqtt.subscribe(
            SLASH.join((self.btopic, b"$broadcast/#")), QOS
        )

        # node topics
        nodes = self.nodes
        for n in nodes:
            props = n._properties
            for p in props:
                is_array = p.range > 1
                if p.settable:
                    self.callback_topics[n.id.encode()] = n.callback
                    # subscribe topic to restore retained messages
                    if p.restore:
                        if is_array:
                            r = range(p.range)
                            for i in r:
                                t = b"{}_{}/{}".format(n.id, i, p.id)
                                await subscribe(t)
                                await sleep_ms(RESTORE_DELAY)
                                await unsubscribe(t)
                        else:
                            t = b"{}/{}".format(n.id, p.id)
                            await subscribe(t)
                            await sleep_ms(RESTORE_DELAY)
                            await unsubscribe(t)

                    # final subscribe to /set topic
                    if is_array:
                        r = range(p.range)
                        for i in r:
                            t = b"{}_{}/{}/set".format(n.id, i, p.id)
                            await subscribe(t)
                    else:
                        t = b"{}/{}/set".format(n.id, p.id)
                        await subscribe(t)

        await self.publish_properties()
        await self.set_state("ready")

    def sub_cb(self, topic, msg, retained):
        # print("MQTT MESSAGE: {} --> {}, {}".format(topic, msg, retained))

        # broadcast callback passed to nodes
        if b"/$broadcast" in topic:
            nodes = self.nodes
            for n in nodes:
                n.broadcast_callback(topic, msg, retained)
        else:
            # node property callbacks
            nt = topic.split(SLASH)
            node = nt[len(self.dtopic.split(SLASH))]
            if b"_" in node:
                node = node.split(b"_")[0]
            if node in self.callback_topics:
                self.callback_topics[node](topic, msg, retained)

    async def publish(self, topic, payload, retain=True):
        if not isinstance(payload, bytes):
            payload = bytes(str(payload), "utf-8")

        t = SLASH.join((self.dtopic, topic))
        # print('MQTT PUBLISH: {} --> {}'.format(t, payload))
        await self.mqtt.publish(t, payload, retain, QOS)

    async def broadcast(self, payload):
        if not isinstance(payload, bytes):
            payload = bytes(str(payload), "utf-8")

        topic = SLASH.join((self.btopic, b"$broadcast"))
        # print("MQTT BROADCAST: {} --> {}".format(topic, payload))
        await self.mqtt.publish(topic, payload, retain=False, qos=QOS)

    async def publish_properties(self):
        """publish device and node properties"""
        publish = self.publish

        # device properties
        await publish(b"$homie", b"3.0.1")
        await publish(b"$name", self.device_name)
        await publish(DEVICE_STATE, b"init")
        await publish(b"$fw/name", b"Microhomie")
        await publish(b"$fw/version", __version__)
        await publish(b"$implementation", bytes(platform, "utf-8"))
        await publish(b"$localip", utils.get_local_ip())
        await publish(b"$mac", utils.get_local_mac())
        await publish(b"$stats", b"interval,uptime,freeheap")
        await publish(
            b"$nodes", b",".join([n.id.encode() for n in self.nodes])
        )

        # node properties
        nodes = self.nodes
        for n in nodes:
            await n.publish_properties()

    @await_ready_state
    async def publish_stats(self):
        delay = self.stats_interval * MAIN_DELAY
        publish = self.publish
        while True:
            uptime = time() - self._stime
            # re-publish interval for some controller (i.e. openhab)
            await publish(b"$stats/interval", self.stats_interval)
            await publish(b"$stats/uptime", uptime)
            await publish(b"$stats/freeheap", mem_free())
            await sleep_ms(delay)

    async def set_state(self, val):
        if val in ["ready", "disconnected", "sleeping", "alert"]:
            self._state = val
            await self.publish(DEVICE_STATE, val)
            if val == "ready":
                _EVENT.set()
                await sleep_ms(MAIN_DELAY)
                _EVENT.clear()

    async def run(self):
        try:
            await self.mqtt.connect()
        except OSError:
            print("ERROR: can not connect to MQTT")

        while True:
            await sleep_ms(MAIN_DELAY)

    def start(self):
        loop = get_event_loop()
        loop.run_until_complete(self.run())
