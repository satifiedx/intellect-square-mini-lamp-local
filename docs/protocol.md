# Lamp protocol notes

Everything here comes from sniffing the lamp on the router and from the Homie description the lamp publishes about itself on every connect. Firmware `20230815_2.0.0`.

## Boot sequence

1. DHCP, then a DNS query for `intellect.properties`.
2. Plain HTTP on port 80: `GET /firmwares/v1/products/<product id>/firmware-version`, answer `{"firmware_version":"6"}`. Looks like an update check. The firmware file itself was never requested in my captures.
3. MQTT 3.1.1 over plain TCP to port 1883 of the same host. Username and password are sent, a local broker can accept anything. The lamp opens two connections, one of them is tiny and short.
4. Right after connecting the lamp publishes its whole state and the Homie `$`-attributes of every property as retained messages.

The official app does not talk to the lamp directly. It goes through the vendor cloud (HTTPS), and the cloud publishes `/set` messages to the lamp.

## Topics

```
<prefix>/sweet-home/<device>/<node>/<property>          state, published by the lamp
<prefix>/sweet-home/<device>/<node>/<property>/set      command, published by you
```

- `<prefix>` is 64 hex characters, the same for everything from one lamp, read it from the first message you see
- `<device>` is the lamp mac with dashes, for example `aa-bb-cc-dd-ee-ff`
- nodes: `led-module`, `status-control`, plus a couple of service topics (`$heartbeat`, `$telemetry/signal`, `ntp/timezone`)

After you publish to `/set` the lamp applies it and echoes the new value on the topic without `/set`.

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
| `power-limit` | enum | `Default`, `Power saving` | |
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

The lamp also publishes a JSON snapshot under `<prefix>/sync-group/products/Group_1/intellect-led-lamp`, that is how lamps in a group follow each other.

## Homie attributes

For each property the lamp publishes `$name`, `$settable`, `$retained`, `$datatype`, `$unit` and `$format` (the range or the enum values). That is where the mode list and the ranges above come from. Subscribe to `#` on your broker after a lamp reboot and you get all of it.
