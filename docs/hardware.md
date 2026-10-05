# Hardware inside the lamp

[Українська](hardware.uk.md)

What is under the plastic of the INTELLECT Square Mini Lamp (50 cm, 5 V / 3 A). Everything marked "verified" was checked on a real lamp, the rest is stated as a guess.

## The controller

The controller sits in a black box at one end of the lamp. It is glued, so opening it means breaking it open. Inside is a small PCB with:

- an **ESP-07S module**, which is an **ESP8266** (not an ESP32), shielded can with an IPEX antenna connector next to it (verified: printed on the shield, and the boot ROM banner is the ESP8266 one)
- three big pads for the LED strip, labelled **G**, **DI**, **5V** (ground, data in, power)
- a few SMD parts around the module (level shifting and power, not traced)
- 4 MB of flash (verified by the boot log: `SPI Flash Size : 4MB`, QIO mode, 40 MHz)

The strip is WS2812B, the firmware reports `led-count = 37` LEDs.

The firmware drives the strip with I2S DMA (`Setting i2s clock div to: 5000000 / 1 / 50` in the boot log). On an ESP8266 the I2S data output is physically **GPIO3**, the same pin as the **RXD** pad of the module. So the LED data line and the UART RX pin are the same pin (verified by the boot log, deduced for the pin number).

## ESP-07S pads

The module has castellated pads in two rows of 8, pitch 2 mm. With the antenna connector on the right, as seen from the board side, the **bottom row** from the antenna to the left is:

```
TXD   RXD   IO5   IO4   IO0   IO2   IO15   GND
```

and the **top row** from the antenna to the left is:

```
RST   ADC   EN   IO16   IO14   IO12   IO13   VCC
```

Verified on a real board: the leftmost pad of the bottom row beeps with the strip's G pad (so it is GND), TXD prints the boot messages, grounding IO0 at power on gives `boot mode:(1,x)` (UART download mode). The rest comes from the ESP-07S datasheet pinout.

## UART access

You need a 3.3 V USB UART adapter (CP2102, CH340, FT232). Wire only three signals, plus IO0 when you want download mode:

| Lamp pad | Adapter |
| --- | --- |
| GND | GND |
| TXD | RXD |
| RXD | TXD |
| IO0 | GND only while powering on (download mode) |

Power the lamp from its own 5 V supply. Do **not** connect the 3V3 or 5V pin of the adapter to the board while the lamp supply is plugged in.

Settings: **74880 baud** (the ESP8266 boot ROM and this firmware both print at 74880, the crystal is most likely 26 MHz), 8N1. Reset the lamp by unplugging power. At 115200 you get garbage.

What you get on TXD at every normal boot is a full log, see [boot-log.txt](boot-log.txt) and the notes in [firmware.md](firmware.md). It prints the Wi-Fi password and the cloud MQTT credentials in clear text, so redact it before sharing. The file in this repo is redacted.

## What does not work (yet)

Getting the lamp into download mode works, but **flashing through the lamp's own UART pads did not**. See [flashing.md](flashing.md) for measurements and what to try next.

## Wi-Fi

2.4 GHz only (it is an ESP8266). Seen in the log: connects as HT20 on channel 3 of my router, DHCP lease in about 3 seconds after power on, MQTT connected at about 3.8 s. If the lamp is flaky, give it a fixed 2.4 GHz channel (1, 6, 11), 20 MHz width, WPA2-PSK, and turn off 802.11w and 802.11r for that network.
