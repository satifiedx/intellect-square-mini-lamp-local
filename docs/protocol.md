# Lamp protocol notes

[Українська](protocol.uk.md)

Everything here comes from sniffing the lamp on the router, from the Homie description the lamp publishes about itself on every connect, and from its UART log. Firmware `20230815_2.0.0`. A redacted copy of the full description is in [homie-description.txt](homie-description.txt), the UART log is in [boot-log.txt](boot-log.txt).

## Boot sequence

1. Wi-Fi, DHCP, then a DNS query for `intellect.properties`.
2. Plain HTTP on port 80: `GET /firmwares/v1/products/<product id>/firmware-version`, answer `{"firmware_version":"6"}`. Looks like an update check. The firmware file itself was never requested in my captures.
3. MQTT 3.1.1 over plain TCP to port 1883 of the same host. CONNECT has clean session on, keepalive 120 s, username and password present. The username is the same 64 hex string that is used as the topic prefix. A local broker can accept any password. The lamp opens two connections, one of them is tiny and short.
4. Right after connecting the lamp publishes its whole state and the Homie `$`-attributes of every property as retained messages, then a heartbeat roughly every 10 to 30 seconds.

The official app does not talk to the lamp directly. It goes through the vendor cloud (HTTPS), and the cloud publishes `/set` messages to the lamp.

## Topics

```
<prefix>/sweet-home/<device>/<node>/<property>          state, published by the lamp
<prefix>/sweet-home/<device>/<node>/<property>/set      command, published by you
```

- `<prefix>` is 64 hex characters, the same for everything from one lamp, read it from the first message you see
- `<device>` is the lamp mac with dashes, for example `aa-bb-cc-dd-ee-ff`
- nodes: `led-module`, `status-control`, `ntp`, plus service topics (`$heartbeat`, `$telemetry/signal`)

After you publish to `/set` the lamp applies it and echoes the new value on the topic without `/set`. Publish with QoS 1.

## led-module properties

| Property | Type | Range or values | Notes |
| --- | --- | --- | --- |
| `led-on` | bool | `true`, `false` | power |
| `led-brightness` | int | 1 to 100 | 0 is not accepted |
| `led-mode` | enum | see below | effect |
| `led-color-1` | color | `R,G,B` | for example `117,213,28` |
| `led-color-2` | color | `R,G,B` | used by some modes |
| `led-color-3` | color | `R,G,B` | used by some modes |
| `led-speed` | int | 0 to 100 | effect speed |
| `led-intensity` | int | 0 to 100 | effect intensity |
| `led-mic-sens` | int | 0 to 100 | sound reactive modes |
| `led-mic-noise` | int | 0 to 100 | sound reactive modes |
| `led-count` | int | read only | number of LEDs, 37 on my lamp |
| `led-enabled` | bool | | |
| `power-limit` | enum | `Default`, `Power saving` | the log prints `Current limit ... 2500 (Default)` |
| `led-start-on` | enum | `Last selected`, `On`, `Off` | state after power up |
| `led-start-mode` | enum | `Last selected` plus all modes | mode after power up |
| `led-start-last-bright` | enum | `Last selected`, `Set manually` | |
| `led-start-brightness` | int | 1 to 100 | used with `Set manually` |
| `led-fade-time` | string | `HH:MM` | |
| `led-timer-time` | string | `HH:MM` | timer length |
| `led-timer-start` | bool | | start the timer |
| `led-timer-left` | string | `HH:MM` | read only |
| `led-sunrise-enabled` | bool | | sunrise alarm |
| `led-sunrise-time` | string | `HH:MM` | |
| `led-sunrise-delay` | string | `HH:MM` | |
| `led-sunrise-duration` | string | `HH:MM` | |

### Modes

`Solid`, `Solid 2`, `Solid 3`, `Percent`, `Percent 2`, `Strobe`, `Rainbow`, `Gradient`, `Fireworks`, `Meteor`, `Fire`, `Blends`, `Random colors`, `Plasma`, `Sound reactive percent`, `Sound reactive lighthouse`, `Sound reactive fire`, `Sound reactive equalizer`, `Sound reactive strobe`

Names are case sensitive and contain spaces, send them exactly like this.

What the official app sent when switching modes (from a capture): a mode change is followed by a color write (`led-color-1` for the Solid and Percent modes, `led-color-2` for Gradient and Plasma, `led-color-1` plus `led-speed`, `led-mic-sens`, `led-mic-noise` for the sound reactive one). Which mode uses which of the three colors was not verified for every effect.

## status-control properties

| Property | Notes |
| --- | --- |
| `sync-group` | `Group_1` to `Group_5`, lamps in one group can be synced |
| `sync-enabled` | bool |
| `firmware-version` | for example `20230815_2.0.0` |
| `fw-autoupdate` | bool |
| `fw-update-time` | `HH:MM` |
| `fw-update-status` | for example `UptoDate` |
| `firmware-staging` | bool |
| `reset-reason`, `reset-status` | numbers |
| `system-uptime` | `H:MM:SS` |
| `reboot` | seen in the traffic, not tested |

`ntp/timezone` is an enum of country names, the lamp turns it into a POSIX TZ string for SNTP time.

The lamp also publishes a JSON snapshot under `<prefix>/sync-group/products/Group_1/intellect-led-lamp`, that is how lamps in a group follow each other. Example payload keys: `led-on`, `led-mode`, `led-brightness`, `led-color-1/2/3`, `led-speed`, `led-intensity`, the timer and sunrise settings and `timezone`.

## Homie attributes

For each property the lamp publishes `$name`, `$settable`, `$retained`, `$datatype`, `$unit` and `$format` (the range or the enum values). That is where the mode list and the ranges above come from. Subscribe to `#` on your broker after a lamp reboot and you get all of it, or read [homie-description.txt](homie-description.txt).
