# Flashing attempt (UART): what worked and what did not

[Українська](flashing.uk.md)

Short version: the chip enters UART download mode, but it never answers the sync command, so `esptool` cannot connect. No firmware dump, no custom firmware through the lamp's own pads. This page is here so nobody has to repeat the same steps, and so someone smarter can pick it up.

## Setup

- ESP-07S pads GND, IO0, RXD, TXD soldered with thin wires (see [hardware.md](hardware.md))
- CP2102 USB-UART adapter, TTL mode, 3.3 V levels, only GND/TXD/RXD connected (crossed), lamp powered from its own 5 V supply
- `esptool` 5.4.0 on Windows, port at 115200

## What worked

1. Receiving: at 74880 baud the chip prints its boot banner and the whole application log, see [boot-log.txt](boot-log.txt).
2. Download mode: ground IO0 (touch it to the strip's G pad), plug the supply in, release. The banner then says `boot mode:(1,7)` instead of `(3,x)` and the lamp stays dark because the firmware never starts. So IO0 and GND are right and the ROM bootloader is alive.
3. Continuity: every soldered joint beeps to the adapter pin it should, neighbours do not beep to each other.

## What did not work

`esptool flash-id` and hand written SLIP sync frames at 115200 (and at 74880, 57600, 230400, 9600) get **no reply at all** while the chip sits in download mode. esptool reports `No serial data received`, which means zero bytes came back after the sync. `--before no-reset` and 100 connect attempts change nothing.

So the PC to chip direction is dead, the chip to PC direction is fine.

## Measurements

Multimeter on DC volts, black on adapter GND, red on the adapter TXD pin (the line going to the chip RXD pad), while the PC streams `0x55` bytes at 115200. A square wave should read about half of the high level on a meter, so the numbers are only good as hints.

| Condition | Reading |
| --- | --- |
| Adapter alone, lamp wire unplugged | about 1.2 V |
| Lamp connected, lamp supply unplugged | about 1.4 V |
| Lamp powered, normal boot (firmware running) | about 0.05 V, the line is pulled to ground |
| Lamp powered, download mode (IO0 grounded) | about 3.0 to 3.1 V on the adapter pin, the RXD pad and the TXD pad, the stream does not pull it down |

In normal mode this is expected, the firmware drives GPIO3 as the I2S LED output and idles it low. In download mode the line is stuck high even though the adapter keeps toggling it.

One more number: on this board the strip's DI pad measures about 1.8 to 1.9 kOhm to the module's VCC and EN pads. It does not beep to any pad of the bottom row. Meaning unknown.

## What I think is going on

The RXD pad is the LED data pin, so something on the controller board (level shifter input, pull-up or a similar stage) is connected to it and holds it harder than a cheap USB-UART adapter with a series resistor can pull it. Wiring mistakes look unlikely because the banner comes through, the continuity checks pass, and IO0 behaves. This is a hypothesis, I could not trace the board.

## Things to try (not tested)

- Power only the module with 3.3 V from the adapter (adapter 3V3 to the module's VCC pad, shared GND) with the lamp's 5 V supply unplugged, so the 5 V side of the board and the LED stage are off. Current from a small adapter may be too low for Wi-Fi bursts but ROM download mode needs little.
- Find what is connected to the RXD pad on the board and lift that part or cut that trace for the duration of flashing.
- Use an adapter with a strong push-pull TX and no series resistor, or drive RXD through a small buffer.
- Read the firmware over the air instead: the lamp has two OTA slots and an OTA mechanism. The update URL is unknown, see [firmware.md](firmware.md).

## If you just want WLED

Skip the stock controller. Cut the strip off the original controller and wire it to an ESP board of your own, WLED then installs over USB or from the browser in a few minutes.

- Strip pads on the original board: `G`, `DI`, `5V`. Connect strip 5V and GND to a 5 V supply that can do the current (3 A for the full lamp), strip DI to a GPIO of the ESP board through a 330 Ohm resistor, and tie the grounds together. Power the ESP board from the same 5 V, do not push the strip current through the dev board.
- ESP8266 board (D1 mini, NodeMCU): in WLED set the data pin to GPIO3 (DMA) or GPIO2. ESP32 board: any free GPIO.
- A 3.3 V data line usually drives WS2812B fine on a short strip. If the strip flickers, add a 74AHCT125 level shifter.
- The native lamp modes (the 19 effects) are not the same as WLED effects, you lose the INTELLECT app and the cloud, you gain WLED.

I did not build this variant myself, treat it as a plan, not a recipe.

## Help wanted

If you manage to dump the firmware (`esptool read-flash 0 0x400000 dump.bin`) or find a clean way to flash this lamp, please open an issue or a pull request. Redact your Wi-Fi password from any dump or log first, the `nvs` partition at `0x9000` contains it.
