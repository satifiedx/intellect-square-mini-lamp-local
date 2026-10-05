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

    assert lampbot.parse_hhmm("7:30") == "07:30" and lampbot.parse_hhmm("00.05") == "00:05"
    assert lampbot.parse_hhmm("25:00") is None and lampbot.parse_hhmm("abc") is None

    import pathlib
    import socket
    import tempfile

    lampbot.SCENES_FILE = pathlib.Path(tempfile.mkdtemp()) / "scenes.json"
    lampbot.save_scene("evening", {"led-mode": "Meteor", "led-color-1": "1,2,3"})
    assert lampbot.load_scenes()["evening"]["led-mode"] == "Meteor"

    def dns_query(name, qtype, port):
        labels = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
        q = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + labels + qtype.to_bytes(2, "big") + b"\x00\x01"
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(3)
            s.sendto(q, ("127.0.0.1", port))
            return s.recv(4096)

    class Upstream(asyncio.DatagramProtocol):
        def connection_made(self, t):
            self.t = t

        def datagram_received(self, data, addr):
            self.t.sendto(b"UPSTREAM" + data[:2], addr)

    loop = asyncio.get_running_loop()
    up, _ = await loop.create_datagram_endpoint(Upstream, local_addr=("127.0.0.1", 15354))
    lampbot.DNS_UPSTREAM = "127.0.0.1:15354"
    dns = await loop.create_datagram_endpoint(lambda: lampbot.DnsStub("192.168.1.50"), local_addr=("127.0.0.1", 15353))
    ans = await loop.run_in_executor(None, dns_query, "intellect.properties", 1, 15353)
    assert ans[:2] == b"\x12\x34" and ans[-4:] == socket.inet_aton("192.168.1.50"), ans
    empty = await loop.run_in_executor(None, dns_query, "intellect.properties", 28, 15353)
    assert empty[6:8] == b"\x00\x00"
    other = await loop.run_in_executor(None, dns_query, "example.com", 1, 15353)
    assert other == b"UPSTREAM\x12\x34", other
    dns[0].close()
    up.close()

    broker = await lampbot.run_broker()
    http = await lampbot.run_http_stub()
    lamp = lampbot.Lamp(port=18830)
    lamp.start()
    dp = lampbot.build_dispatcher(lamp)

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
    lamp.send("led-timer-time", "00:30")
    await asyncio.sleep(1.5)
    assert ("led-timer-time", "00:30") in received
    assert ("led-on", "false") in received
    assert ("led-brightness", "1") in received
    assert ("led-color-1", "117,213,28") in received
    assert ("led-color-2", "1,2,3") in received
    assert ("led-speed", "100") in received
    assert ("led-mode", "Meteor") in received
    assert lamp.state.get("led-module/led-color-1") == "117,213,28"
    panel, apply = dp["panel"], dp["apply"]
    seen, todo, clicked = set(), ["main"], 0
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        text, markup = panel(name, 1)
        assert text
        for row in markup.inline_keyboard:
            for button in row:
                data = button.callback_data
                assert len(data.encode()) <= 64, data
                action, _, arg = data.partition(":")
                if action == "nav":
                    todo.append(arg)
                elif action not in ("target", "status"):
                    result = apply(action, arg)
                    assert not result.startswith(("?", "Need", "Unknown", "No such", "No scene")), (data, result)
                    clicked += 1
    assert {"main", "colors", "bright", "modes", "modes:static", "modes:anim", "modes:sound", "scenes", "timers", "more"} <= seen, seen
    print("menu OK:", len(seen), "pages,", clicked, "buttons")
    print("ALL OK")

    await asyncio.get_running_loop().run_in_executor(None, lamp.stop)
    await asyncio.get_running_loop().run_in_executor(None, fake.loop_stop)
    http.close()
    await broker.shutdown()


asyncio.run(main())
