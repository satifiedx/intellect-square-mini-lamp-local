# INTELLECT Square Mini Lamp, local control

[Українська версія](README.uk.md)

Run the INTELLECT Square Mini Lamp without the vendor cloud. A small script pretends to be the manufacturer's server, the lamp connects to it, and you drive the lamp from a Telegram bot with buttons, text or voice messages.

Unofficial project, not affiliated with INTELLECT. Use at your own risk.

## How it works

The lamp has an ESP32 class chip with closed firmware. Nothing listens on its ports, but it is very chatty on boot. I sniffed it on the router with tcpdump and found out:

1. It resolves `intellect.properties` through your normal DNS.
2. It asks `GET /firmwares/v1/products/<id>/firmware-version` over plain HTTP on port 80 and expects `{"firmware_version":"6"}`.
3. It connects to that host on port 1883 with plain MQTT, no TLS. Login and password are sent but any are accepted by a broker you run yourself.
4. Everything is Homie convention topics: `<64 hex prefix>/sweet-home/<mac>/led-module/led-on` and friends. Write to the same topic with `/set` appended to control it.

So the trick is simple: make `intellect.properties` point to your own machine, run an MQTT broker there, and talk to the lamp by publishing to its `/set` topics. `lampbot.py` does all of it in one process:

- embedded MQTT broker (amqtt) on port 1883
- tiny HTTP stub on port 80 that answers the firmware version check
- MQTT client that discovers the lamp prefix and mac by itself
- Telegram bot (aiogram) with an allowlist
- optional voice and free text control through Groq (Whisper for speech, an LLM to turn a phrase into lamp commands)

Full topic list and value ranges: [docs/protocol.md](docs/protocol.md).

## What you need

- Python 3.10+
- a machine in your LAN that is always on when you want to use the lamp (PC, Raspberry Pi, mini server)
- a router or DNS server where you can override one hostname (OpenWrt, Pi-hole, AdGuard Home, plain dnsmasq, most custom firmwares)
- a Telegram bot token from @BotFather
- optional: a free Groq API key from console.groq.com for voice and text commands

## Setup

```
git clone https://github.com/satifiedx/intellect-square-mini-lamp-local
cd intellect-square-mini-lamp-local
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env`:

```
BOT_TOKEN=123456:your-token
ALLOWED_IDS=
GROQ_API_KEY=
```

Run it:

```
python lampbot.py
```

Port 80 needs admin rights on Linux and macOS (`sudo`), or set `HTTP_PORT=8080` in `.env`, but then the lamp will not reach the stub. The stub is optional, the lamp just boots a bit slower without it.

On Windows allow Python through the firewall for private networks, otherwise the lamp cannot reach ports 1883 and 80.

Now write `/start` to your bot. It answers with your Telegram id, put it into `ALLOWED_IDS` (comma separated for several people) and restart the bot. Until the list is filled the bot refuses everyone.

## Point the lamp at your machine

Give the machine running the bot a static IP or a DHCP reservation first, then override the hostname `intellect.properties` to that IP.

OpenWrt:

```
uci add_list dhcp.@dnsmasq[0].address='/intellect.properties/192.168.1.50'
uci commit dhcp
/etc/init.d/dnsmasq restart
```

Plain dnsmasq:

```
address=/intellect.properties/192.168.1.50
```

Pi-hole: Local DNS, DNS Records, add `intellect.properties` with the IP.

AdGuard Home: Filters, DNS rewrites, add `intellect.properties` with the IP.

Check from any PC: `nslookup intellect.properties` must return your machine. Then unplug the lamp and plug it back. In the bot log you should see the http request and then `lamp found`.

To undo it, remove the override (on OpenWrt `uci del_list dhcp.@dnsmasq[0].address='/intellect.properties/192.168.1.50'`, commit, restart dnsmasq) and replug the lamp.

## Using the bot

| Command | What it does |
| --- | --- |
| `/menu` | button remote |
| `/on`, `/off` | power |
| `/status` | state, colors, mode, speed, wifi signal, uptime |
| `/brightness 1-100` | brightness |
| `/color red`, `/color #ff8800`, `/color 255 100 0` | color 1 (also turns the lamp on) |
| `/color2 ...`, `/color3 ...` | colors 2 and 3 |
| `/mode Meteor` | effect by name, `/modes` shows buttons for all of them |
| `/speed 0-100`, `/intensity 0-100` | effect speed and intensity |

Color names work in English, Russian and Ukrainian.

### Voice and free text

If `GROQ_API_KEY` is set, just send a voice message or plain text, no command needed:

- "turn on meteor, blue and purple, full speed"
- "make it warm and dim"
- "вмикай веселку повільніше"

Voice goes to Groq Whisper, the text goes to an LLM with a short prompt that returns a JSON list of actions, the bot applies them and replies what it did. The LLM is `openai/gpt-oss-20b` on Groq by default, change it with `GROQ_LLM` in `.env` if Groq renames or retires it (`GET https://api.groq.com/openai/v1/models` lists what you have).

If you have the Antigravity CLI (`agy`) installed you can use it as the brain instead: set `AGENT=agy` and optionally `AGY_MODEL` and `AGY_EXE`. It is slower (5 to 20 seconds per phrase) and falls back to Groq if it fails or takes longer than 45 seconds.

## Modes

The lamp reports the full list itself:

Solid, Solid 2, Solid 3, Percent, Percent 2, Strobe, Rainbow, Gradient, Fireworks, Meteor, Fire, Blends, Random colors, Plasma, Sound reactive percent, Sound reactive lighthouse, Sound reactive fire, Sound reactive equalizer, Sound reactive strobe.

What I saw in the official app traffic: Solid modes use color 1, Gradient and Plasma also use color 2, Meteor uses two colors, Strobe depends on speed, the sound reactive ones use `led-mic-sens` and `led-mic-noise`. I did not verify every mode, so if you find out more, open an issue or a PR.

## Good to know

- While the DNS override is on, the official app cannot see the lamp on your home Wi-Fi, because the app talks to the cloud and the lamp talks to you. Remove the override to go back.
- The machine with the bot must be on, otherwise the lamp has no broker.
- The broker listens on `0.0.0.0:1883` and accepts anything. Keep it in your LAN, never forward that port to the internet.
- The Telegram bot only obeys ids from `ALLOWED_IDS`.
- Wi-Fi tips if the lamp is flaky: the chip is 2.4 GHz only, use a fixed channel (1, 6 or 11), 20 MHz width, WPA2-PSK, and turn off 802.11w and 802.11r for that network.
- Tested with firmware `20230815_2.0.0`.

## Tests

```
python test_lampbot.py
```

Spins up the broker and a fake lamp that speaks the same topics, then checks discovery and commands. No Telegram and no real lamp needed.

## License

MIT
