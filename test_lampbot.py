import asyncio
import os

os.environ["MQTT_PORT"] = "18830"
os.environ["HTTP_PORT"] = "18080"
os.environ["BOT_TOKEN"] = "123456:TEST"

import paho.mqtt.client as mqtt

import lampbot

PREFIX = "0f" * 32
DEV = "aa-bb-cc-dd-ee-ff"
BASE = f"{PREFIX}/sweet-home/{DEV}"
received = []


def make_fake_lamp():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fake-lamp")
    c.username_pw_set("user", "pass")

    def on_connect(cl, u, f, rc, p=None):
        cl.subscribe(f"{BASE}/led-module/+/set", qos=1)

    def on_message(cl, u, msg):
        received.append((msg.topic.split("/")[-2], msg.payload.decode()))
        cl.publish(msg.topic[:-4], msg.payload, qos=1)

    c.on_connect, c.on_message = on_connect, on_message
    c.connect("127.0.0.1", 18830)
    c.loop_start()
    return c


async def main():
    assert lampbot.parse_color("red") == (255, 0, 0)
    assert lampbot.parse_color("#ff8800") == (255, 136, 0)
    assert lampbot.parse_color("117,213,28") == (117, 213, 28)
    assert lampbot.parse_color("1 2 300") is None
    assert lampbot.parse_color("зелений") == (0, 255, 0)
    assert lampbot.find_mode("sound reactive FIRE") == "Sound reactive fire"
    assert lampbot.find_mode("nope") is None

    broker = await lampbot.run_broker()
    http = await lampbot.run_http_stub()
    lamp = lampbot.Lamp(port=18830)
    lamp.start()
    lampbot.build_dispatcher(lamp)

    r, w = await asyncio.open_connection("127.0.0.1", 18080)
    w.write(b"GET /firmwares/v1/products/1/firmware-version HTTP/1.1\r\nHost: x\r\n\r\n")
    data = await r.read(1000)
    assert b'{"firmware_version": "6"}' in data, data

    fake = make_fake_lamp()
    await asyncio.sleep(1)
    fake.publish(f"{BASE}/$heartbeat", "p")
    fake.publish(f"{BASE}/led-module/led-on", "true")
    fake.publish(f"{BASE}/$telemetry/signal", "58")
    await asyncio.sleep(1)
    assert lamp.known and lamp.dev == DEV and lamp.prefix == PREFIX, (lamp.prefix, lamp.dev)
    assert lamp.online

    lamp.power(False)
    lamp.brightness(0)
    lamp.color((117, 213, 28))
    lamp.color_n(2, (1, 2, 3))
    lamp.prop("led-speed", 250)
    lamp.mode("Meteor")
    await asyncio.sleep(1.5)
    assert ("led-on", "false") in received
    assert ("led-brightness", "1") in received
    assert ("led-color-1", "117,213,28") in received
    assert ("led-color-2", "1,2,3") in received
    assert ("led-speed", "100") in received
    assert ("led-mode", "Meteor") in received
    assert lamp.state.get("led-module/led-color-1") == "117,213,28"
    print("ALL OK")

    lamp.stop()
    fake.loop_stop()
    http.close()
    await broker.shutdown()


asyncio.run(main())
