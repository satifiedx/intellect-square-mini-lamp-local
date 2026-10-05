# Stock firmware notes

[Українська](firmware.uk.md)

Everything here is read from the lamp's own boot log ([boot-log.txt](boot-log.txt), redacted) and from its traffic, no reverse engineering of the binary was done. The firmware file itself could not be dumped, see [flashing.md](flashing.md).

## What it is

- Built on **ESP8266 RTOS SDK** (the boot log says `ESP-IDF v3.4-79-gaf0cdc36-dirty 2nd stage bootloader`). That is not the Arduino core and not the old NONOS SDK.
- Firmware version reported over MQTT: `20230815_2.0.0` (`status-control/firmware-version`).
- Version the lamp asks the cloud over HTTP: `{"firmware_version":"6"}`. Different numbering, it looks like an integer build counter.
- Tasks and tags seen in the log: `MAIN`, `CLOUD_MQTT`, `led_module`, `SCHEDULER`, `SCHEDULER_CORE`, `NTP_CLIENT`, `TIMEZONES`, `RESET_REASON`, `wifi module`, `utils`.
- Free heap while idle is only about 22 to 27 kB.

## Flash layout (4 MB)

From the partition table printed by the bootloader:

| # | Label | Type | Offset | Size |
| --- | --- | --- | --- | --- |
| 0 | `nvs` | WiFi data | `0x009000` | `0x004000` (16 kB) |
| 1 | `otadata` | OTA data | `0x00d000` | `0x002000` (8 kB) |
| 2 | `phy_init` | RF data | `0x00f000` | `0x001000` (4 kB) |
| 3 | `ota_0` | OTA app | `0x010000` | `0x1e0000` (1.9 MB) |
| 4 | `ota_1` | OTA app | `0x210000` | `0x1e0000` (1.9 MB) |
| 5 | `prop_values` | WiFi data | `0x3f0000` | `0x010000` (64 kB) |

- Two OTA slots, so the lamp updates itself over the air and can fall back to the old image.
- The running image was loaded from `ota_0` at `0x10000`, 5 segments, the biggest ones are about 595 kB and 118 kB mapped from flash.
- `prop_values` is a custom partition. My guess is that it stores the lamp settings (colors, mode, timers), not verified.
- `nvs` holds the Wi-Fi credentials, so a flash dump of this lamp contains your Wi-Fi password.

## Boot sequence in numbers

From the log (timestamps are milliseconds since boot):

1. ROM banner at 74880 baud, `boot mode:(3,x)` is a normal flash boot.
2. 2nd stage bootloader at about 43 ms, app loaded at about 229 ms.
3. LEDs switched on at about 417 ms (the last stored state, so the lamp lights up before it is on the network).
4. Wi-Fi station start at about 530 ms, associated and got an IP at about 2 to 3 s.
5. SNTP starts right after the IP.
6. Cloud MQTT connected at about 3.8 s.

So the lamp itself is up in under 4 seconds. If connecting is slow in practice, the delay is on the network side (DHCP, DNS for `intellect.properties`, the far away broker), which is exactly what pointing the hostname at a local broker removes.

## Things the firmware does

- **MQTT client** to `intellect.properties:1883`, protocol 3.1.1, clean session, keepalive 120 s, username and password sent. Username is the same 64 hex string used as the topic prefix. Root topic `<prefix>/sweet-home`. See [protocol.md](protocol.md).
- **Sync group**: it subscribes to `<prefix>/sync-group/products/Group_1/intellect-led-lamp`. Lamps in one group follow each other.
- **SNTP** time with a timezone picked from a built in country list (`ntp/timezone` property, the log prints the resulting TZ string). The scheduler needs time for the sunrise alarm and timers.
- **Scheduler**: sunrise alarm (`led-sunrise-*`), sleep timer (`led-timer-*`), fade time (`led-fade-time`).
- **Current limit**: `led_module: Current limit changed to 2500 (Default)`. The `power-limit` property switches between `Default` and `Power saving`.
- **Mode, color, brightness, speed, intensity** are exposed as Homie properties, full list in [protocol.md](protocol.md).
- **OTA**: properties `fw-autoupdate`, `fw-update-time`, `fw-update-status`, `firmware-staging` exist. The lamp checks a version over plain HTTP at boot. The update binary URL was never seen on the wire in my captures, so it is unknown. A custom firmware could in theory be pushed this way if you find the URL and the format, untested.
- **Reboot** via a `status-control/reboot` topic (seen in traffic, not tested).

## HTTP version check

```
GET /firmwares/v1/products/1696495347508969/firmware-version HTTP/1.1
Host: intellect.properties
```

Answer: `{"firmware_version":"6"}`. The number in the path looks like a product id, not a device id. If you serve a different number the lamp may try to download an update, I did not try this.

## Security notes

- MQTT is plain TCP, no TLS, and the broker only needs the login the lamp already has. Anyone on your network path who sees the traffic sees everything, including the password.
- The UART log prints the Wi-Fi password and MQTT credentials. A lamp that left your house with an open case leaks them.
- Nothing in the boot log suggests secure boot or flash encryption (ESP8266 has neither anyway).
