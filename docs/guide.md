# Control your INTELLECT lamp from Telegram: the simple guide

[Українська](guide.uk.md)

No programming needed. If you can install an app and copy a few lines, you can do this. It takes about an hour the first time.

## What you get

Your INTELLECT Square Mini Lamp answers to a Telegram bot instead of the official app. You get buttons for colors, brightness, all 19 effects, timers, a sunrise alarm and saved scenes. You can also send a voice message like "make it warm and dim" and the lamp does it. Everything stays inside your home network, nothing goes through the manufacturer's server.

## How it works, in plain words

The lamp has one habit: at startup it looks up the address `intellect.properties` and connects to whatever it finds there. Normally that is the manufacturer's server. We change the "phone book" of your home network so that this name points to your own small computer instead. On that computer a program (the bot) pretends to be the manufacturer's server, and also talks to Telegram. So the lamp thinks it talks to the manufacturer, but it talks to you.

Side effect: while this is on, the official INTELLECT app cannot see the lamp. You can switch back at any time.

## What you need

- the lamp, already working with your Wi-Fi (2.4 GHz)
- a computer that stays on whenever you want to use the lamp: an old PC or laptop, a Raspberry Pi, a mini server. A computer you switch off every night works too, but then the lamp only listens to the bot while it is on
- Python 3.10 or newer on that computer
- a Telegram account
- access to your router settings, where you can change one DNS entry (see step 5, there are options for most routers)
- optional: a free account at console.groq.com for voice messages and plain text commands

## Step 1. Make your bot in Telegram

1. Open Telegram, search for **@BotFather**, start a chat.
2. Send `/newbot`, answer two questions (a name and a username that ends with `bot`).
3. BotFather sends you a long token like `123456:ABC...`. Copy it. It is the key to your bot, do not share it.

## Step 2. Optional: a Groq key for voice

1. Go to console.groq.com, sign up.
2. Create an API key and copy it.

Skip this step if you only want buttons.

## Step 3. Put the bot on your computer

1. Download the project: on the GitHub page press the green **Code** button, then **Download ZIP**, and unpack it. If you know git: `git clone` the repository.
2. Open a terminal in that folder (on Windows: open the folder, click the address bar, type `cmd`, press Enter).
3. Install the parts it needs:
   ```
   pip install -r requirements.txt
   ```
4. Make your settings file: copy `.env.example` to a new file called `.env` (exactly that name). Open it in Notepad and fill in:
   ```
   BOT_TOKEN=the token from BotFather
   ALLOWED_IDS=
   GROQ_API_KEY=your Groq key, or leave empty
   ```
5. Start the bot:
   ```
   python lampbot.py
   ```
   On Windows a firewall window appears. Allow access for **private networks**. Leave the terminal window open.

## Step 4. Tell the bot it is you

1. In Telegram open your new bot and press **Start**.
2. It answers "Access denied" and shows **your Telegram id**, a number.
3. Put that number into `.env`: `ALLOWED_IDS=123456789` (several people: separate with commas).
4. Stop the bot (Ctrl+C in the terminal) and start it again.
5. Send `/menu` to the bot. You should see a panel with buttons. The lamp does not react yet, that is normal.

From now on only the people in `ALLOWED_IDS` can control the lamp.

## Step 5. Point the lamp at your computer

First give your computer a fixed address, otherwise the next steps break when its address changes. In your router look for "DHCP reservation", "static lease" or "address reservation" and bind your computer to its current IP. Write the IP down, we call it `YOUR_PC_IP` below.

Then make the name `intellect.properties` point to `YOUR_PC_IP`. Pick the line that matches your router:

- **OpenWrt:** in a terminal on the router
  ```
  uci add_list dhcp.@dnsmasq[0].address='/intellect.properties/YOUR_PC_IP'
  uci commit dhcp
  /etc/init.d/dnsmasq restart
  ```
- **Pi-hole:** Local DNS, DNS Records, add `intellect.properties` with `YOUR_PC_IP`.
- **AdGuard Home:** Filters, DNS rewrites, add `intellect.properties` with `YOUR_PC_IP`.
- **MikroTik:** `/ip dns static add name=intellect.properties address=YOUR_PC_IP`
- **Routers on dnsmasq (DD-WRT, Asus Merlin, Tomato):** add `address=/intellect.properties/YOUR_PC_IP` to the custom dnsmasq options.
- **pfSense / OPNsense:** DNS Resolver (Unbound), host override.
- **Grandstream GWN routers:** Network Settings, LAN, tab Local DNS Records, add the entry. Then in the same LAN page open your network and set the DHCP "Preferred DNS Server" to the router's own address, otherwise devices use a public DNS and ignore the entry.
- **Your router has nothing like this (most home routers):** use the bot's built in DNS. In `.env` add `DNS_STUB=1`, restart the bot, then in the router's DHCP settings set the DNS server to `YOUR_PC_IP` (and as a backup DNS the router's own address). Details are in the main README.

## Step 6. Check and reconnect the lamp

1. On any computer in your network run `nslookup intellect.properties`. The answer must show `YOUR_PC_IP`. If it shows something else, wait a minute or two (DNS keeps old answers for a while) and try again.
2. Unplug the lamp for 3 seconds, plug it back.
3. Within about 30 seconds the bot window prints `lamp found`.
4. Open the bot, send `/menu`, press a button. The lamp reacts.

## Step 7. Make it start by itself

So you do not have to start the bot by hand after every reboot.

**Windows:** open a terminal and run (change the path to your folder, keep the quotes):
```
schtasks /create /tn "lampbot" /sc onlogon /tr "pythonw C:\path\to\the\folder\lampbot.py"
```
The bot now starts when you log in, with no window.

**Linux or Raspberry Pi** (no admin rights needed): create a file `run.sh` in the project folder
```
#!/bin/sh
cd "$HOME/lampbot" || exit 1
exec flock -n .lock python3 -u lampbot.py >> bot.log 2>&1
```
make it runnable (`chmod +x run.sh`) and add it to cron once a minute (`crontab -e`, then the line `* * * * * $HOME/lampbot/run.sh`). If the bot is already running the extra start does nothing, if it died or the machine rebooted it starts again.

## Using it

- `/menu` is the button panel, one message that updates itself.
- Voice or text, without any command: "turn on meteor, blue and purple", "make it warm and dim", "sleep timer 20 minutes", "wake me up at 7:30", "turn on the evening scene".
- `/save evening` saves how the lamp looks right now, `/scenes` brings it back.
- All commands are in the main README.

## Something is wrong

- **The bot does not answer in Telegram:** the terminal must still be open and show no errors. Check the token in `.env` has no spaces around it.
- **"Access denied":** your id is not in `ALLOWED_IDS`, or you did not restart the bot after editing.
- **Lamp never shows `lamp found`:** the lamp and the computer must be in the same network (no guest Wi-Fi). The firewall must allow incoming TCP on port 1883. The DNS entry must point to the current IP of the computer. A VPN on the computer can also hide it from the lamp.
- **Commands do nothing but the lamp is found:** wait 30 seconds after plugging the lamp in, it has to report its state first.
- **Bot works but the official app lost the lamp:** expected, see below.

## Going back to the official app

Remove the DNS entry from the router (or turn the DNS stub off), unplug the lamp for a few seconds, plug it back. The official app works again.

## Safety

- Never open port 1883 of this computer to the internet. Anyone could then control your lamp.
- Keep `.env` private, it contains your bot token. Do not upload it anywhere.
- Change the default password of your router.
