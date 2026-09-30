import asyncio
import json
import logging
import os
import re
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

    def send(self, prop: str, value) -> bool:
        if not self.known:
            return False
        topic = f"{self.prefix}/sweet-home/{self.dev}/led-module/{prop}/set"
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
            f"Wi-Fi: {self.state.get('$telemetry/signal', '?')}\n"
            f"Uptime: {self.state.get('status-control/system-uptime', '?')}"
        )


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


AGENT_PROMPT = (
    "You control a smart RGB lamp. The user speaks Russian, Ukrainian or English. "
    "Answer with JSON only:\n"
    '{"actions":[{"a":"...","v":...}],"reply":"short answer or empty string"}\n'
    "Actions (a): on, off (no v); b brightness 1-100; s effect speed 0-100; i intensity 0-100; "
    'c, c2, c3 colors 1/2/3, v is "#rrggbb" (convert color names to hex yourself); '
    "m mode, v is the EXACT name from this list: " + ", ".join(MODES) + ".\n"
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
    system = AGENT_PROMPT + ("\nCurrent state: " + lamp.status_text() if lamp.known else "")
    data = None
    if AGENT == "agy":
        try:
            raw = await agy_ask(f"{system}\nDo not use tools, answer with JSON only.\nPhrase: {text}")
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except Exception as e:
            log.warning("agy failed (%s), falling back to groq", e)
    if data is None:
        data = await groq_chat(system, text)
    allowed = ("on", "off", "b", "c", "c2", "c3", "s", "i", "m")
    return [a for a in data.get("actions", []) if a.get("a") in allowed], data.get("reply", "")


def build_dispatcher(lamp: Lamp):
    from aiogram import Dispatcher, F
    from aiogram.filters import Command, CommandStart
    from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

    dp = Dispatcher()
    b = InlineKeyboardButton

    def kb() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [b(text="On", callback_data="on"), b(text="Off", callback_data="off"),
             b(text="Status", callback_data="status")],
            [b(text="🔴", callback_data="c:red"), b(text="🟠", callback_data="c:orange"),
             b(text="🟡", callback_data="c:yellow"), b(text="🟢", callback_data="c:green"),
             b(text="🔵", callback_data="c:blue"), b(text="🟣", callback_data="c:purple")],
            [b(text="White", callback_data="c:white"), b(text="Warm", callback_data="c:warm"),
             b(text="Pink", callback_data="c:pink")],
            [b(text="10%", callback_data="b:10"), b(text="30%", callback_data="b:30"),
             b(text="60%", callback_data="b:60"), b(text="100%", callback_data="b:100")],
            [b(text="All modes", callback_data="modes")],
        ])

    def modes_kb() -> InlineKeyboardMarkup:
        rows = [[b(text=m, callback_data=f"m:{m}") for m in MODES[i:i + 2]] for i in range(0, len(MODES), 2)]
        rows.append([b(text="speed 20", callback_data="s:20"), b(text="speed 50", callback_data="s:50"),
                     b(text="speed 90", callback_data="s:90")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

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
        await message.answer("Lamp remote:", reply_markup=kb())

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
        await message.answer("Modes:", reply_markup=modes_kb())

    @dp.message(Command("brightness", "speed", "intensity", "color", "color2", "color3", "mode"))
    @guarded
    async def with_arg(message: Message):
        cmd = message.text.split()[0].lstrip("/").split("@")[0]
        act = {"brightness": "b", "speed": "s", "intensity": "i", "color": "c",
               "color2": "c2", "color3": "c3", "mode": "m"}[cmd]
        await message.answer(apply(act, arg_of(message)))

    @dp.callback_query(F.data)
    async def cb(call: CallbackQuery):
        if not allowed(call.from_user.id):
            return await call.answer("No access", show_alert=True)
        data = call.data
        if data == "modes":
            await call.message.answer("Modes:", reply_markup=modes_kb())
            return await call.answer()
        if data == "status":
            await call.message.answer(lamp.status_text())
            return await call.answer()
        action, _, arg = data.partition(":")
        await call.answer(apply(action, arg))

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

    return dp


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("transitions").setLevel(logging.WARNING)
    logging.getLogger("amqtt").setLevel(logging.WARNING)

    if not BOT_TOKEN:
        sys.exit("BOT_TOKEN is missing in .env (get one from @BotFather)")

    broker = await run_broker() if EMBEDDED_BROKER else None
    http = await run_http_stub()
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
        lamp.stop()
        if http:
            http.close()
        if broker:
            await broker.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
