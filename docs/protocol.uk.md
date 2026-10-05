# Нотатки про протокол лампи

[English](protocol.md)

Усе тут отримано зі сніфу лампи на роутері, з опису Homie, який лампа публікує про себе при кожному підключенні, і з її логу UART. Прошивка `20230815_2.0.0`. Очищена копія повного опису лежить у [homie-description.txt](homie-description.txt), лог UART у [boot-log.txt](boot-log.txt).

## Послідовність завантаження

1. Wi-Fi, DHCP, потім DNS запит `intellect.properties`.
2. Голий HTTP на порту 80: `GET /firmwares/v1/products/<product id>/firmware-version`, відповідь `{"firmware_version":"6"}`. Схоже на перевірку оновлення. Сам файл прошивки в моїх записах жодного разу не запитувався.
3. MQTT 3.1.1 по голому TCP на порт 1883 того самого хоста. У CONNECT clean session увімкнено, keepalive 120 с, логін і пароль присутні. Логін це той самий 64-символьний hex, що й префікс топіків. Локальний брокер може приймати будь-який пароль. Лампа відкриває два з'єднання, одне з них крихітне й коротке.
4. Одразу після підключення лампа публікує весь свій стан і Homie `$`-атрибути кожної властивості як retained повідомлення, а далі приблизно кожні 10 до 30 секунд heartbeat.

Офіційний додаток з лампою напряму не говорить. Він ходить через хмару виробника (HTTPS), а хмара публікує `/set` повідомлення лампі.

## Топіки

```
<prefix>/sweet-home/<device>/<node>/<property>          стан, публікує лампа
<prefix>/sweet-home/<device>/<node>/<property>/set      команда, публікуєш ти
```

- `<prefix>` це 64 hex символи, однаковий для всього від однієї лампи, бери його з першого повідомлення, яке побачиш
- `<device>` це mac лампи через дефіси, наприклад `aa-bb-cc-dd-ee-ff`
- вузли: `led-module`, `status-control`, `ntp`, плюс службові топіки (`$heartbeat`, `$telemetry/signal`)

Після публікації в `/set` лампа застосовує значення і відлунює нове значення в топік без `/set`. Публікуй із QoS 1.

## Властивості led-module

| Властивість | Тип | Діапазон або значення | Примітки |
| --- | --- | --- | --- |
| `led-on` | bool | `true`, `false` | живлення |
| `led-brightness` | int | від 1 до 100 | 0 не приймається |
| `led-mode` | enum | дивись нижче | ефект |
| `led-color-1` | color | `R,G,B` | наприклад `117,213,28` |
| `led-color-2` | color | `R,G,B` | використовується деякими режимами |
| `led-color-3` | color | `R,G,B` | використовується деякими режимами |
| `led-speed` | int | від 0 до 100 | швидкість ефекту |
| `led-intensity` | int | від 0 до 100 | інтенсивність ефекту |
| `led-mic-sens` | int | від 0 до 100 | звукові режими |
| `led-mic-noise` | int | від 0 до 100 | звукові режими |
| `led-count` | int | тільки читання | кількість діодів, у моєї лампи 37 |
| `led-enabled` | bool | | |
| `power-limit` | enum | `Default`, `Power saving` | у логу `Current limit ... 2500 (Default)` |
| `led-start-on` | enum | `Last selected`, `On`, `Off` | стан після подачі живлення |
| `led-start-mode` | enum | `Last selected` плюс усі режими | режим після подачі живлення |
| `led-start-last-bright` | enum | `Last selected`, `Set manually` | |
| `led-start-brightness` | int | від 1 до 100 | діє разом із `Set manually` |
| `led-fade-time` | string | `HH:MM` | |
| `led-timer-time` | string | `HH:MM` | тривалість таймера |
| `led-timer-start` | bool | | запуск таймера |
| `led-timer-left` | string | `HH:MM` | тільки читання |
| `led-sunrise-enabled` | bool | | будильник світанку |
| `led-sunrise-time` | string | `HH:MM` | |
| `led-sunrise-delay` | string | `HH:MM` | |
| `led-sunrise-duration` | string | `HH:MM` | |

### Режими

`Solid`, `Solid 2`, `Solid 3`, `Percent`, `Percent 2`, `Strobe`, `Rainbow`, `Gradient`, `Fireworks`, `Meteor`, `Fire`, `Blends`, `Random colors`, `Plasma`, `Sound reactive percent`, `Sound reactive lighthouse`, `Sound reactive fire`, `Sound reactive equalizer`, `Sound reactive strobe`

Назви чутливі до регістру і містять пробіли, шли їх точно так.

Що слав офіційний додаток при перемиканні режимів (із запису): за зміною режиму йде запис кольору (`led-color-1` для режимів Solid і Percent, `led-color-2` для Gradient і Plasma, `led-color-1` плюс `led-speed`, `led-mic-sens`, `led-mic-noise` для звукового). Який режим які з трьох кольорів використовує, я перевірив не для кожного ефекту.

## Властивості status-control

| Властивість | Примітки |
| --- | --- |
| `sync-group` | від `Group_1` до `Group_5`, лампи однієї групи можуть синхронізуватися |
| `sync-enabled` | bool |
| `firmware-version` | наприклад `20230815_2.0.0` |
| `fw-autoupdate` | bool |
| `fw-update-time` | `HH:MM` |
| `fw-update-status` | наприклад `UptoDate` |
| `firmware-staging` | bool |
| `reset-reason`, `reset-status` | числа |
| `system-uptime` | `H:MM:SS` |
| `reboot` | бачив у трафіку, не перевіряв |

`ntp/timezone` це enum з назвами країн, лампа перетворює його на рядок POSIX TZ для часу SNTP.

Лампа також публікує JSON знімок у `<prefix>/sync-group/products/Group_1/intellect-led-lamp`, саме так лампи в групі повторюють одна одну. Приклад ключів: `led-on`, `led-mode`, `led-brightness`, `led-color-1/2/3`, `led-speed`, `led-intensity`, налаштування таймера і світанку та `timezone`.

## Атрибути Homie

Для кожної властивості лампа публікує `$name`, `$settable`, `$retained`, `$datatype`, `$unit` і `$format` (діапазон або значення enum). Звідси береться список режимів і діапазони вище. Підпишись на `#` на своєму брокері після перезавантаження лампи, і отримаєш усе це, або читай [homie-description.txt](homie-description.txt).
