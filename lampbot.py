import asyncio
import json
import logging
import os
import re
import socket
import struct
import sys
import tempfile
import time
from pathlib import Path

import httpx
import paho.mqtt.client as mqtt

log = logging.getLogger("lampbot")


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env(Path(__file__).with_name(".env"))

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ALLOWED_IDS = {int(x) for x in os.getenv("ALLOWED_IDS", "").replace(" ", "").split(",") if x}
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
HTTP_PORT = int(os.getenv("HTTP_PORT", "80"))
FW_VERSION = os.getenv("FW_VERSION", "6")
EMBEDDED_BROKER = os.getenv("EMBEDDED_BROKER", "1") == "1"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_LLM = os.getenv("GROQ_LLM", "openai/gpt-oss-20b")
AGENT = os.getenv("AGENT", "groq")
AGY_MODEL = os.getenv("AGY_MODEL", "gemini-3.8-flash-low")
AGY_EXE = os.getenv("AGY_EXE", "agy")
GROQ = "https://api.groq.com/openai/v1"
DNS_STUB = os.getenv("DNS_STUB", "0") == "1"
DNS_PORT = int(os.getenv("DNS_PORT", "53"))
DNS_UPSTREAM = os.getenv("DNS_UPSTREAM", "8.8.8.8")
LAN_IP = os.getenv("LAN_IP", "")
DNS_NAME = "intellect.properties"

MODES = [
    "Solid", "Solid 2", "Solid 3", "Percent", "Percent 2", "Strobe", "Rainbow", "Gradient",
    "Fireworks", "Meteor", "Fire", "Blends", "Random colors", "Plasma", "Sound reactive percent",
    "Sound reactive lighthouse", "Sound reactive fire", "Sound reactive equalizer",
    "Sound reactive strobe",
]

TOPIC_RE = re.compile(r"^(?P<prefix>.+?)/sweet-home/(?P<dev>[^/]+)/(?P<rest>.+)$")

COLORS = {
    "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
    "white": (255, 255, 255), "warm": (255, 147, 41), "yellow": (255, 200, 0),
    "orange": (255, 100, 0), "purple": (150, 0, 255), "pink": (255, 50, 150),
    "cyan": (0, 255, 255),
    "красный": (255, 0, 0), "зелёный": (0, 255, 0), "зеленый": (0, 255, 0),
    "синий": (0, 0, 255), "белый": (255, 255, 255), "тёплый": (255, 147, 41),
    "теплый": (255, 147, 41), "жёлтый": (255, 200, 0), "желтый": (255, 200, 0),
    "оранжевый": (255, 100, 0), "фиолетовый": (150, 0, 255),
    "розовый": (255, 50, 150), "голубой": (0, 255, 255),
    "червоний": (255, 0, 0), "зелений": (0, 255, 0), "синій": (0, 0, 255),
    "білий": (255, 255, 255), "теплий": (255, 147, 41), "жовтий": (255, 200, 0),
    "помаранчевий": (255, 100, 0), "фіолетовий": (150, 0, 255),
    "рожевий": (255, 50, 150), "блакитний": (0, 255, 255),
}


def find_mode(text: str):
    t = text.strip().lower()
    return next((m for m in MODES if m.lower() == t), None)


SCENES_FILE = Path(os.getenv("SCENES_FILE") or Path(__file__).with_name("scenes.json"))


def load_scenes() -> dict:
    try:
        return json.loads(SCENES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_scene(name: str, snap: dict) -> None:
    scenes = load_scenes()
    scenes[name] = snap
    SCENES_FILE.write_text(json.dumps(scenes, ensure_ascii=False, indent=1), encoding="utf-8")


def parse_hhmm(text: str):
    m = re.fullmatch(r"([01]?\d|2[0-3])[:.]([0-5]\d)", text.strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def parse_color(text: str):
    t = text.strip().lower()
    if t in COLORS:
        return COLORS[t]
    m = re.fullmatch(r"#?([0-9a-f]{6})", t)
    if m:
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    parts = re.split(r"[\s,;]+", t)
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        rgb = tuple(int(p) for p in parts)
        if all(0 <= c <= 255 for c in rgb):
            return rgb
    return None


class Lamp:
    ONLINE_SEC = 90

    def __init__(self, host: str = "127.0.0.1", port: int = 1883):
        self.host, self.port = host, port
        self.prefix = os.getenv("LAMP_PREFIX") or None
        self.dev = os.getenv("LAMP_DEVICE") or None
        self.state: dict[str, str] = {}
        self.last_seen = 0.0
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="lampbot")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def start(self) -> None:
        self.client.connect_async(self.host, self.port)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        log.info("mqtt client connected to broker (%s)", reason_code)
        client.subscribe("#")

    def _on_message(self, client, userdata, msg):
        m = TOPIC_RE.match(msg.topic)
        if not m or msg.topic.endswith("/set"):
            return
        if self.prefix is None or self.dev is None:
            self.prefix, self.dev = m["prefix"], m["dev"]
            log.info("lamp found: device %s", self.dev)
        rest = m["rest"]
        self.last_seen = time.time()
        if rest != "$heartbeat":
            self.state[rest] = msg.payload.decode("utf-8", "replace")

    @property
    def online(self) -> bool:
        return time.time() - self.last_seen < self.ONLINE_SEC

    @property
    def known(self) -> bool:
        return self.prefix is not None and self.dev is not None

    def send(self, prop: str, value, node: str = "led-module") -> bool:
        if not self.known:
            return False
        topic = f"{self.prefix}/sweet-home/{self.dev}/{node}/{prop}/set"
        log.info("-> %s = %s", prop, value)
        self.client.publish(topic, str(value), qos=1)
        return True

    def power(self, on: bool):
        return self.send("led-on", "true" if on else "false")

    def brightness(self, value: int):
        return self.send("led-brightness", max(1, min(100, int(value))))

    def color(self, rgb):
        return self.send("led-color-1", "%d,%d,%d" % tuple(rgb))

    def color_n(self, n: int, rgb):
        return self.send(f"led-color-{n}", "%d,%d,%d" % tuple(rgb))

    def prop(self, name: str, value: int):
        return self.send(name, max(0, min(100, int(value))))

    def mode(self, name: str):
        return self.send("led-mode", name)

    def summary(self) -> str:
        if not self.known:
            return "Waiting for the lamp to connect..."
        g = lambda k: self.state.get("led-module/" + k, "?")
        icon = "🟢" if g("led-on") == "true" else "⚫"
        return (f"{icon} {g('led-mode')}, brightness {g('led-brightness')}\n"
                f"color {g('led-color-1')}, speed {g('led-speed')}, intensity {g('led-intensity')}")

    def status_text(self) -> str:
        if not self.known:
            return "The lamp has not connected to the broker yet."
        g = lambda k: self.state.get("led-module/" + k, "?")
        ago = int(time.time() - self.last_seen)
        return (
            f"{'online' if self.online else 'offline'} (last signal {ago}s ago)\n"
            f"Power: {g('led-on')}\n"
            f"Brightness: {g('led-brightness')}\n"
            f"Color 1: {g('led-color-1')}\n"
            f"Color 2/3: {g('led-color-2')} / {g('led-color-3')}\n"
            f"Mode: {g('led-mode')}\n"
            f"Speed: {g('led-speed')}, intensity: {g('led-intensity')}\n"
            f"Sleep timer: {g('led-timer-time')} (left {g('led-timer-left')}, running {g('led-timer-start')})\n"
            f"Sunrise: {g('led-sunrise-time')} (enabled {g('led-sunrise-enabled')})\n"
            f"Fade time: {g('led-fade-time')}, eco: {g('power-limit')}\n"
            f"LEDs: {g('led-count')}, firmware: {self.state.get('status-control/firmware-version', '?')}\n"
            f"Wi-Fi: {self.state.get('$telemetry/signal', '?')}\n"
            f"Uptime: {self.state.get('status-control/system-uptime', '?')}"
        )

    def snapshot(self) -> dict:
        keys = ("led-mode", "led-color-1", "led-color-2", "led-color-3",
                "led-brightness", "led-speed", "led-intensity")
        return {k: self.state["led-module/" + k] for k in keys if "led-module/" + k in self.state}


async def run_broker():
    from amqtt.broker import Broker

    config = {
        "listeners": {"default": {"type": "tcp", "bind": f"0.0.0.0:{MQTT_PORT}"}},
        "sys_interval": 0,
        "auth": {"allow-anonymous": True, "plugins": ["auth_anonymous"]},
        "topic-check": {"enabled": False},
    }
    broker = Broker(config)
    await broker.start()
    log.info("mqtt broker listening on port %d", MQTT_PORT)
    return broker


async def run_http_stub():
    async def handle(reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            log.info("lamp http request: %s", head.split(b"\r\n", 1)[0].decode("latin1"))
            body = json.dumps({"firmware_version": FW_VERSION}).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                b"Content-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body
            )
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    try:
        server = await asyncio.start_server(handle, "0.0.0.0", HTTP_PORT)
        log.info("firmware version stub on port %d (answers %s)", HTTP_PORT, FW_VERSION)
        return server
    except OSError as e:
        log.warning("http stub not started on port %d (%s), the lamp may boot a bit slower", HTTP_PORT, e)
        return None


GROUPS = {
    "static": ("Static", MODES[:5]),
    "anim": ("Animated", MODES[5:14]),
    "sound": ("Sound reactive", MODES[14:]),
}


def group_of(mode: str) -> str:
    return next((k for k, (_, ms) in GROUPS.items() if mode in ms), "static")


def lan_ip() -> str:
    if LAN_IP:
        return LAN_IP
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]


def dns_question(data: bytes):
    i, labels = 12, []
    while data[i]:
        n = data[i]
        labels.append(data[i + 1:i + 1 + n].decode("ascii", "replace").lower())
        i += n + 1
    return ".".join(labels), struct.unpack(">H", data[i + 1:i + 3])[0], i + 5


def dns_answer(data: bytes, ip: str) -> bytes:
    _, qtype, end = dns_question(data)
    a_record = qtype == 1
    head = data[:2] + b"\x81\x80" + data[4:6] + (b"\x00\x01" if a_record else b"\x00\x00") + b"\x00\x00\x00\x00"
    answer = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + socket.inet_aton(ip) if a_record else b""
    return head + data[12:end] + answer


def dns_forward(data: bytes) -> bytes:
    host, _, port = DNS_UPSTREAM.partition(":")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(3)
        s.sendto(data, (host, int(port or 53)))
        return s.recv(4096)


class DnsStub(asyncio.DatagramProtocol):
    def __init__(self, ip: str):
        self.ip = ip

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        asyncio.get_running_loop().create_task(self.reply(data, addr))

    async def reply(self, data, addr):
        try:
            name, _, _ = dns_question(data)
            if name == DNS_NAME:
                out = dns_answer(data, self.ip)
            else:
                out = await asyncio.get_running_loop().run_in_executor(None, dns_forward, data)
            self.transport.sendto(out, addr)
        except Exception as e:
            log.debug("dns: %s", e)


async def run_dns_stub():
    ip = lan_ip()
    try:
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: DnsStub(ip), local_addr=("0.0.0.0", DNS_PORT))
    except OSError as e:
        log.warning("dns stub not started on port %d (%s)", DNS_PORT, e)
        return None
    log.info("dns stub on port %d: %s -> %s, everything else goes to %s", DNS_PORT, DNS_NAME, ip, DNS_UPSTREAM)
    return transport


AGENT_PROMPT = (
    "You control a smart RGB lamp. The user speaks Russian, Ukrainian or English. "
    "Answer with JSON only:\n"
    '{"actions":[{"a":"...","v":...}],"reply":"short answer or empty string"}\n'
    "Actions (a): on, off (no v); b brightness 1-100; s effect speed 0-100; i intensity 0-100; "
    'c, c2, c3 colors 1/2/3, v is "#rrggbb" (convert color names to hex yourself); '
    "m mode, v is the EXACT name from this list: " + ", ".join(MODES) + ". "
    'sleep timer: t with v "HH:MM" (turns the lamp off after that long) or "off"; '
    'sunrise alarm: sr with v "HH:MM" (wake up time, enables it), "on" or "off"; '
    'fade: fade with v "HH:MM" (fade duration); ms and mn microphone sensitivity and noise 0-100 for sound reactive modes; '
    'eco with v "on" or "off" (power saving, lower current limit); '
    "scene with v the name of a saved scene (a list of saved scenes may follow).\n"
    "Solid is one color. Meteor, Gradient, Plasma and some others use colors 1 and 2. "
    "Strobe and many effects depend on speed s. Sound reactive modes listen to the mic. "
    "You can chain actions, order matters (mode first, then colors). "
    "If the phrase is not about the lamp, return no actions and a short reply."
)


async def groq_transcribe(audio: bytes) -> str:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            f"{GROQ}/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": ("voice.ogg", audio, "audio/ogg")},
            data={"model": "whisper-large-v3-turbo"},
        )
        r.raise_for_status()
        return r.json()["text"].strip()


async def agy_ask(prompt: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        AGY_EXE, "-p", prompt, "--model", AGY_MODEL, cwd=tempfile.gettempdir(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 45)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return out.decode("utf-8", "replace")


async def groq_chat(system: str, text: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{GROQ}/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": GROQ_LLM,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}],
            },
        )
        r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


async def run_agent_llm(text: str, lamp: Lamp):
    scenes = ", ".join(load_scenes()) or "none"
    system = AGENT_PROMPT + f"\nSaved scenes: {scenes}" + ("\nCurrent state: " + lamp.status_text() if lamp.known else "")
    data = None
    if AGENT == "agy":
        try:
            raw = await agy_ask(f"{system}\nDo not use tools, answer with JSON only.\nPhrase: {text}")
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except Exception as e:
            log.warning("agy failed (%s), falling back to groq", e)
    if data is None:
        data = await groq_chat(system, text)
    allowed = ("on", "off", "b", "c", "c2", "c3", "s", "i", "m", "t", "sr", "fade", "ms", "mn", "eco", "scene")
    return [a for a in data.get("actions", []) if a.get("a") in allowed], data.get("reply", "")


def build_dispatcher(lamp: Lamp):
    from aiogram import Dispatcher, F
    from aiogram.filters import Command, CommandStart
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

    dp = Dispatcher()
    b = InlineKeyboardButton

    targets: dict[int, str] = {}
    palette = [("🔴", "red"), ("🟠", "orange"), ("🟡", "yellow"), ("🟢", "green"), ("🩵", "cyan"),
               ("🔵", "blue"), ("🟣", "purple"), ("🩷", "pink"), ("⚪", "white"), ("🕯", "warm")]

    def btn(text: str, data: str):
        return b(text=text, callback_data=data)

    def page(name: str, uid: int):
        head = lamp.summary()
        g = lambda k: lamp.state.get("led-module/" + k, "?")
        back = [btn("⬅ Back", "nav:main")]
        if name == "main":
            on = g("led-on") == "true"
            return head, [
                [btn("Turn off" if on else "Turn on", "off" if on else "on"), btn("Refresh", "nav:main")],
                [btn("🎨 Colors", "nav:colors"), btn("💡 Brightness", "nav:bright"), btn("✨ Modes", "nav:modes")],
                [btn("🎬 Scenes", "nav:scenes"), btn("⏱ Timers", "nav:timers"), btn("⚙ More", "nav:more")],
            ]
        if name == "colors":
            t = targets.get(uid, "1")
            return head + "\nPick a color", [
                [btn(e, f"c:{n}") for e, n in palette[:5]],
                [btn(e, f"c:{n}") for e, n in palette[5:]],
                [btn(f"Editing color {t}, tap to switch", "target")],
                back,
            ]
        if name == "bright":
            return head, [
                [btn(f"{v}%", f"b:{v}") for v in (10, 25, 50, 75, 100)],
                [btn("−10", "bd:-10"), btn("+10", "bd:10")],
                back,
            ]
        if name == "modes":
            return head + "\nPick a group", [
                [btn(label, f"nav:modes:{k}") for k, (label, _) in GROUPS.items()],
                [btn("Speed −", "sd:-10"), btn("Speed +", "sd:10"), btn("Intensity −", "id:-10"), btn("Intensity +", "id:10")],
                back,
            ]
        if name.startswith("modes:"):
            label, ms = GROUPS[name.split(":", 1)[1]]
            rows = [[btn(m, f"m:{m}") for m in ms[i:i + 2]] for i in range(0, len(ms), 2)]
            rows.append([btn("Speed −", "sd:-10"), btn("Speed +", "sd:10"), btn("Intensity −", "id:-10"), btn("Intensity +", "id:10")])
            rows.append([btn("⬅ Groups", "nav:modes")])
            return head + f"\n{label}", rows
        if name == "scenes":
            names = list(load_scenes())
            rows = [[btn(n, f"scene:{n}") for n in names[i:i + 3]] for i in range(0, len(names), 3)]
            return head + "\nSave the current look with /save name", rows + [back]
        if name == "timers":
            return (head + f"\nSleep timer: {g('led-timer-time')}, left {g('led-timer-left')}, running {g('led-timer-start')}"
                    f"\nSunrise: {g('led-sunrise-time')}, enabled {g('led-sunrise-enabled')}"
                    "\nExact time: /timer 00:45 and /sunrise 07:30"), [
                [btn("15 min", "t:00:15"), btn("30 min", "t:00:30"), btn("1 h", "t:01:00"), btn("2 h", "t:02:00")],
                [btn("Stop timer", "t:off"), btn("Sunrise on", "sr:on"), btn("Sunrise off", "sr:off")],
                back,
            ]
        return head + f"\nEco: {g('power-limit')}, mic sensitivity {g('led-mic-sens')}", [
            [btn("Eco on", "eco:on"), btn("Eco off", "eco:off")],
            [btn(f"Mic sens {v}", f"ms:{v}") for v in (30, 60, 90)],
            [btn("Full status", "status")],
            back,
        ]

    def panel(name: str, uid: int):
        text, rows = page(name, uid)
        return text, InlineKeyboardMarkup(inline_keyboard=rows)

    def page_after(action: str, arg: str) -> str:
        if action in ("c", "c2", "c3"):
            return "colors"
        if action in ("b", "bd"):
            return "bright"
        if action == "m":
            return "modes:" + group_of(arg)
        if action in ("s", "sd", "i", "id"):
            return "modes:" + group_of(lamp.state.get("led-module/led-mode", ""))
        if action == "scene":
            return "scenes"
        if action in ("t", "sr"):
            return "timers"
        if action in ("eco", "ms", "mn", "fade"):
            return "more"
        return "main"

    def allowed(user_id: int) -> bool:
        return user_id in ALLOWED_IDS

    async def deny(message: Message):
        await message.answer(
            f"Access denied. Your Telegram id: {message.from_user.id}\n"
            "Put it into ALLOWED_IDS in .env and restart the bot."
        )

    def apply(action: str, arg: str | None = None) -> str:
        arg = arg or ""
        if not lamp.known:
            return "The lamp has not connected yet, give it ~30s after power on."
        if action == "on":
            lamp.power(True)
            return "On"
        if action == "off":
            lamp.power(False)
            return "Off"
        if action == "b":
            if not arg.isdigit():
                return "Need a number 1-100"
            lamp.brightness(int(arg))
            return f"Brightness {arg}"
        if action == "c":
            rgb = parse_color(arg)
            if not rgb:
                return "Unknown color. Examples: red, #ff8800, 255 100 0"
            lamp.power(True)
            lamp.color(rgb)
            return f"Color {rgb}"
        if action in ("c2", "c3"):
            rgb = parse_color(arg)
            if not rgb:
                return "Unknown color. Examples: red, #ff8800, 255 100 0"
            lamp.color_n(int(action[1]), rgb)
            return f"Color {action[1]}: {rgb}"
        if action in ("s", "i"):
            if not arg.isdigit():
                return "Need a number 0-100"
            lamp.prop("led-speed" if action == "s" else "led-intensity", int(arg))
            return f"{'Speed' if action == 's' else 'Intensity'} {arg}"
        if action == "m":
            mode = find_mode(arg)
            if not mode:
                return "No such mode, see /modes"
            lamp.power(True)
            lamp.mode(mode)
            return f"Mode {mode}"
        if action in ("bd", "sd", "id"):
            key = {"bd": "led-brightness", "sd": "led-speed", "id": "led-intensity"}[action]
            try:
                value = int(lamp.state.get("led-module/" + key, 50)) + int(arg)
            except ValueError:
                return "?"
            value = max(1 if action == "bd" else 0, min(100, value))
            lamp.prop(key, value)
            return f"{key.split('-')[1].capitalize()} {value}"
        if action == "t":
            if arg.lower() in ("off", "stop"):
                lamp.send("led-timer-start", "false")
                return "Sleep timer stopped"
            t = parse_hhmm(arg)
            if not t:
                return "Need a time like 00:30 (hours:minutes)"
            lamp.send("led-timer-time", t)
            lamp.send("led-timer-start", "true")
            return f"Sleep timer {t}"
        if action == "sr":
            if arg.lower() in ("on", "off"):
                lamp.send("led-sunrise-enabled", arg.lower() == "on" and "true" or "false")
                return f"Sunrise {arg.lower()}"
            t = parse_hhmm(arg)
            if not t:
                return "Need a time like 07:30, or on / off"
            lamp.send("led-sunrise-time", t)
            lamp.send("led-sunrise-enabled", "true")
            return f"Sunrise at {t}"
        if action == "fade":
            t = parse_hhmm(arg)
            if not t:
                return "Need a time like 00:05"
            lamp.send("led-fade-time", t)
            return f"Fade time {t}"
        if action in ("ms", "mn"):
            if not arg.isdigit():
                return "Need a number 0-100"
            lamp.prop("led-mic-sens" if action == "ms" else "led-mic-noise", int(arg))
            return f"Mic {'sensitivity' if action == 'ms' else 'noise'} {arg}"
        if action == "eco":
            on = arg.lower() in ("on", "1", "true", "yes")
            lamp.send("power-limit", "Power saving" if on else "Default")
            return f"Eco {'on' if on else 'off'}"
        if action == "scene":
            snap = load_scenes().get(arg.strip().lower())
            if not snap:
                return f"No scene '{arg}', see /scenes"
            lamp.power(True)
            for k, v in snap.items():
                lamp.send(k, v)
            return f"Scene {arg.strip().lower()}"
        return "?"

    def guarded(handler):
        async def wrapper(message: Message):
            if not allowed(message.from_user.id):
                return await deny(message)
            return await handler(message)
        return wrapper

    def arg_of(message: Message) -> str:
        return ((message.text or "").split(maxsplit=1) + [""])[1].strip()

    @dp.message(CommandStart())
    @dp.message(Command("menu"))
    @guarded
    async def start(message: Message):
        text, markup = panel("main", message.from_user.id)
        await message.answer(text, reply_markup=markup)

    @dp.message(Command("on"))
    @guarded
    async def on(message: Message):
        await message.answer(apply("on"))

    @dp.message(Command("off"))
    @guarded
    async def off(message: Message):
        await message.answer(apply("off"))

    @dp.message(Command("status"))
    @guarded
    async def status(message: Message):
        await message.answer(lamp.status_text())

    @dp.message(Command("modes"))
    @guarded
    async def modes(message: Message):
        text, markup = panel("modes", message.from_user.id)
        await message.answer(text, reply_markup=markup)

    commands = {"brightness": "b", "speed": "s", "intensity": "i", "color": "c", "color2": "c2",
                "color3": "c3", "mode": "m", "timer": "t", "sunrise": "sr", "fade": "fade",
                "micsens": "ms", "micnoise": "mn", "eco": "eco", "scene": "scene"}

    @dp.message(Command(*commands))
    @guarded
    async def with_arg(message: Message):
        cmd = message.text.split()[0].lstrip("/").split("@")[0]
        await message.answer(apply(commands[cmd], arg_of(message)))

    @dp.message(Command("save"))
    @guarded
    async def save(message: Message):
        name = arg_of(message).lower()
        if not name or len(name) > 20:
            return await message.answer("Usage: /save name (up to 20 characters)")
        snap = lamp.snapshot()
        if not snap:
            return await message.answer("The lamp has not reported its state yet")
        save_scene(name, snap)
        await message.answer(f"Saved scene '{name}'")

    @dp.message(Command("scenes"))
    @guarded
    async def scenes(message: Message):
        text, markup = panel("scenes", message.from_user.id)
        await message.answer(text, reply_markup=markup)

    async def show(call: CallbackQuery, name: str):
        text, markup = panel(name, call.from_user.id)
        try:
            await call.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest:
            pass

    @dp.callback_query(F.data)
    async def cb(call: CallbackQuery):
        if not allowed(call.from_user.id):
            return await call.answer("No access", show_alert=True)
        uid = call.from_user.id
        action, _, arg = call.data.partition(":")
        if action == "nav":
            await show(call, arg)
            return await call.answer()
        if action == "target":
            targets[uid] = {"1": "2", "2": "3", "3": "1"}[targets.get(uid, "1")]
            await show(call, "colors")
            return await call.answer()
        if action == "status":
            await call.message.answer(lamp.status_text())
            return await call.answer()
        act = {"1": "c", "2": "c2", "3": "c3"}[targets.get(uid, "1")] if action == "c" else action
        await call.answer(apply(act, arg))
        await asyncio.sleep(0.5)
        await show(call, page_after(action, arg))

    async def run_agent(message: Message, text: str):
        try:
            acts, reply = await run_agent_llm(text, lamp)
        except Exception as e:
            log.exception("agent failed")
            return await message.answer(f"Agent failed: {e}")
        done = [apply(a.get("a", ""), str(a.get("v", ""))) for a in acts]
        await message.answer("\n".join(([reply] if reply else []) + done) or "Did not get it")

    @dp.message(F.voice)
    @guarded
    async def voice(message: Message):
        if not GROQ_API_KEY:
            return await message.answer("GROQ_API_KEY is not set in .env")
        file = await message.bot.get_file(message.voice.file_id)
        buf = await message.bot.download_file(file.file_path)
        try:
            text = await groq_transcribe(buf.read())
        except Exception as e:
            return await message.answer(f"Whisper failed: {e}")
        await message.answer(f"🎙 {text}")
        await run_agent(message, text)

    @dp.message(F.text & ~F.text.startswith("/"))
    @guarded
    async def free_text(message: Message):
        if not GROQ_API_KEY:
            return await message.answer("GROQ_API_KEY is not set in .env")
        await run_agent(message, message.text)

    dp["panel"], dp["apply"], dp["page_after"] = panel, apply, page_after
    return dp


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("transitions").setLevel(logging.WARNING)
    logging.getLogger("amqtt").setLevel(logging.WARNING)

    if not BOT_TOKEN:
        sys.exit("BOT_TOKEN is missing in .env (get one from @BotFather)")

    broker = await run_broker() if EMBEDDED_BROKER else None
    http = await run_http_stub()
    dns = await run_dns_stub() if DNS_STUB else None
    lamp = Lamp(port=MQTT_PORT)
    lamp.start()

    from aiogram import Bot

    bot = Bot(BOT_TOKEN)
    dp = build_dispatcher(lamp)
    if not ALLOWED_IDS:
        log.warning("ALLOWED_IDS is empty: the bot ignores everyone and only tells them their id")
    try:
        await dp.start_polling(bot)
    finally:
        await asyncio.get_running_loop().run_in_executor(None, lamp.stop)
        if http:
            http.close()
        if dns:
            dns.close()
        if broker:
            await broker.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
