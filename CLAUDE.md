# Claude Code — Home Automation System Briefing

Auto-loaded every session. Full context about all devices, projects, and how they connect.
**Update this file whenever a device, topic, path, or architecture changes.**

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     HOME NETWORK (192.168.1.x)                      │
│                     Router/Gateway: 192.168.1.254                   │
│                     WiFi: JioFiber-XtHwH (primary), baljeet22-2g   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────────┐     ┌──────────────────────┐             │
│  │  Pi4 — 192.168.1.122 │     │  Pi5 — 192.168.1.108 │             │
│  │  PRIMARY HUB         │     │  CAMERA NODE         │             │
│  │  Mosquitto broker    │◄────│  Bridge → Pi4        │             │
│  │  mybot.service       │────►│  mybot.service       │             │
│  │  InfluxDB            │     │  Pi camera           │             │
│  └──────────┬───────────┘     └──────────┬───────────┘             │
│             │ MQTT 1883                  │ MQTT localhost           │
│             │ (all ESP devices)          │ (bridge from Pi4)        │
│             │                            │                          │
│     ┌───────┴────────────────────────────┴──────────┐              │
│     │               ESP DEVICES                     │              │
│     │                                               │              │
│     │  ESP32-LP-RDR1  192.168.1.87  (main radar)   │              │
│     │  ESP01-LL-RLY   192.168.1.85  (lower lobby)  │              │
│     │  ESP01-UL-RLY   192.168.1.111 (upper lobby)  │              │
│     │  ESP32-LP-RLY   192.168.1.89  (lower porch)  │              │
│     └───────────────────────────────────────────────┘              │
│                                                                     │
│  VIP 192.168.1.100 — static secondary IP on Pi4 wlan0              │
│  (Keepalived DISABLED 2026-06-21; .100 kept for app backward compat)│
└─────────────────────────────────────────────────────────────────────┘

                        ┌──────────────┐
                        │   CLOUD      │
                        ├──────────────┤
                        │ Firebase RTDB│ ◄── ESP32-LP-RDR1 (direct)
                        │ AWS IoT Core │ ◄── ESP32-LP-RDR1 (direct)
                        │ Telegram API │ ◄── ESP32-LP-RDR1 + Pi bots
                        └──────────────┘
                               ▲
                    Pi4 + Pi5 mybot.service
```

---

## Pi4 — Primary Hub

| Item | Value |
|------|-------|
| Hostname | `pi4` |
| IP | `192.168.1.122` |
| User | `pi` |
| SSH | `ssh pi@192.168.1.122` (password: `22`) |
| OS | Debian (aarch64) |
| Python venv | `/home/pi/myenv/` (Python 3.x) |
| Project path | `/home/pi/pi4_drive/Git_projects/RASPI4-MAIN/` |
| GitHub | `https://github.com/bs220975/RASPI4-MAIN` |

### Pi4 — GPIO Pins (BCM)

| GPIO | Device | Direction | Notes |
|------|--------|-----------|-------|
| 14 | LD2420 radar TX | Output (UART) | `/dev/serial0` TX |
| 15 | LD2420 radar RX | Input (UART) | `/dev/serial0` RX |
| 25 | PIR sensor | Input | pull_up=False |
| 27 | MMS microwave sensor | Input | pull_up=False |
| 18 | Status LED | Output | mirrors motion |
| 26 | Reed switch (door) | Input | PUD_UP — HIGH=open, LOW=closed |
| 17 | Case fan | Output | dtoverlay=gpio-fan,gpiopin=17,temp=65000 |

Serial `/dev/serial0` — LD2420 radar (115200 baud). `enable_uart=1` in `/boot/firmware/config.txt`.

### Pi4 — Services

| Service | Role | Notes |
|---------|------|-------|
| `mybot.service` | Main bot (`RASPI4-MAIN/main.py`) | MQTT_HOST=192.168.1.122 |
| `mqttdatainflux.service` | MQTT → InfluxDB bridge | `influx_aws_publish/influxdb2_aws_publish.py` |
| `mosquitto` | MQTT broker `0.0.0.0:1883` | ALL ESP devices connect here |
| `influxdb` | InfluxDB 2.x `http://[::1]:8086` | org: `pi4org`, bucket: `pi4data` |
| `keepalived` | VRRP failover | **DISABLED** 2026-06-21 — IP source guard conflict |
| `fan-shutdown.service` | Drives GPIO17 LOW on shutdown | Prevents fan spin-up after poweroff |

### Pi4 — Key Files

| File | Role |
|------|------|
| `main.py` | Main controller (`RaspberryPiController`) |
| `mqtt_bridge.py` | Paho MQTT — relays + radar subscriptions |
| `firebase_logger.py` | Firebase RTDB writes + SSE command streams |
| `sensors.py` | LD2420 radar, PIR, MMS, reed switch |
| `config.py` | All config constants |
| `bot_commands.py` | Telegram command dispatch |
| `telegram_handler.py` | Telegram API wrapper |
| `local_api_server.py` | LAN fallback HTTP API port 5757 |
| `light_scheduler.py` | APScheduler daily on/off timers |
| `influxdb_logger.py` | Motion events → InfluxDB |
| `video_recorder.py` | **Pi camera — lobby area recording** (triggered by LD2420 radar, logic inside main.py) |
| `esp_devices.py` | HTTP fallback for ESP heartbeat |

### Pi4 — Aliases

```bash
cdmain        # cd to RASPI4-MAIN
cdgit         # cd to /home/pi/pi4_drive/Git_projects
servicemybot  # journalctl -u mybot.service -f
statusmqtt    # systemctl status mosquitto
copymybot     # copy mybot.service to /etc/systemd/system/
reloadmybot   # systemctl daemon-reload
```

---

## Pi5 — Camera Node

| Item | Value |
|------|-------|
| Hostname | `pi5` |
| IP | `192.168.1.108` |
| User | `pi5` |
| OS | Debian (aarch64), kernel 6.12.x |
| Python venv | `/home/pi5/myenv/` (Python 3.13, **must** have `include-system-site-packages = true`) |
| Project path | `/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/` |
| GitHub | `https://github.com/bs220975/RASPI5-MAIN` |

### Pi5 — GPIO Pins (BCM)

| GPIO | Device | Direction | Notes |
|------|--------|-----------|-------|
| 25 | PIR sensor | Input | pull_up=False |
| 27 | MMS microwave sensor | Input | pull_up=False |
| 18 | Status LED | Output | mirrors motion |
| 26 | Reed switch (door) | Input | PUD_UP — HIGH=open, LOW=closed |

Serial `/dev/serial0` — LD2420 radar (115200 baud).

### Pi5 — Services

| Service | Role | Notes |
|---------|------|-------|
| `mybot.service` | Main bot (`RASPI5-MAIN/main.py`) | MQTT_HOST=localhost (Pi5's own broker) |
| `mqttdatainflux.service` | MQTT → InfluxDB bridge | MQTT_HOST=localhost |
| `mosquitto` | MQTT broker `0.0.0.0:1883` | Bridges specific topics from Pi4 |
| `influxdb` | InfluxDB 2.x `http://[::1]:8086` | org: `pi4org`, bucket: `pi4data` |

### Pi5 — Mosquitto Bridge (to Pi4)

Config: `/etc/mosquitto/conf.d/bridge_pi4.conf`

| Direction | Topic | Purpose |
|-----------|-------|---------|
| IN (from Pi4) | `home/esp32/radar1/#` | Radar motion events → Pi5 camera trigger |
| IN (from Pi4) | `home/switches/L-Porch-Light/state` | LP relay state → Pi5 Firebase update |
| IN (from Pi4) | `home/switches/L-Porch-Light/availability` | LP relay availability |
| OUT (to Pi4) | `home/switches/L-Porch-Light/cmd` | Pi5 LP relay commands |
| OUT (to Pi4) | `home/esp01/upper-lobby/cmd/#` | Pi5 upper lobby relay commands |
| OUT (to Pi4) | `home/esp01/lower-lobby/cmd/#` | Pi5 lower lobby relay commands |

### Pi5 — Key Files

| File | Role |
|------|------|
| `main.py` | Main controller |
| `mqtt_bridge.py` | Paho MQTT — subscribes to bridged topics |
| `firebase_logger.py` | Firebase RTDB writes + SSE streams |
| `sensors.py` | LD2420 radar, PIR, MMS, reed switch |
| `config.py` | All config constants |
| `video_recorder.py` | **picamera2 → H264 → ffmpeg MP4** |
| `telegram_handler.py` | Telegram API wrapper |
| `bot_commands.py` | Telegram command dispatch |
| `influxdb_logger.py` | Motion → InfluxDB |
| `esp_devices.py` | HTTP fallback for ESP01-LL-RLY heartbeat |

### Pi5 — Python Venv

`picamera2` is **system-wide** (apt), not in venv. Venv must have `include-system-site-packages = true`.

```bash
# If venv is ever recreated:
python3 -m venv --system-site-packages /home/pi5/myenv
# NEVER use: python3 -m venv /home/pi5/myenv  ← breaks video recording
```

### Pi5 — Aliases

```bash
cdmain        # cd to RASPI5-MAIN
cdgit         # cd to /home/pi5/pi5_drive/Git_projects
servicemybot  # journalctl -u mybot.service -f
statusmqtt    # systemctl status mosquitto
```

---

## ESP Devices

### ESP32-LP-RDR1 — Main Radar (Lower Porch Radar 1)

| Item | Value |
|------|-------|
| IP | `192.168.1.87` |
| Board | ESP32 Dev Module, 240MHz |
| Project | `/home/pi5/pi5_drive/Git_projects/ESP32-LP-RDR1/` |
| Telegram suffix | `2` — all commands end with `2` (e.g. `/radar_on2`) |
| Telegram bot token | `8292280421:...` |
| Telegram chat ID | `6825638285` |
| WebServerUI port | `81` |
| SwitchService port | `80` |

**GPIO pins:**

| GPIO | Device |
|------|--------|
| 19 | Radar sensor (input) |
| 18 | Radar LED (output) |
| 27 | Door sensor (input) |
| 13 | DHT11 temp/humidity |

**MQTT topics published:**

| Topic | Broker | Purpose |
|-------|--------|---------|
| `home/esp32/radar1/motion` | Pi4 VIP (192.168.1.100 → .122) | Motion ON/OFF — Pi4 light control |
| `home/esp32/radar1/availability` | Pi4 VIP | LWT online/offline |
| `home/pi5/lp-rdr/motion` | Pi5 direct (192.168.1.108) | Motion ON/OFF — Pi5 camera trigger |
| `home/esp32/radar2/motion` | Pi4 VIP | Legacy topic (may still be published) |
| DHT11 temp/humidity | Pi4 broker | Home network only |

**What it does:**
- Motion detection → turns on porch light (ESP01-UL-RLY) at night (18:00–06:00 IST)
- Sends Telegram alerts on motion (throttled 60 s)
- Acts as **Firebase gateway** for the whole system — polls Firebase every 2 s for lobby light state and serves it to ESP01-UL-RLY via HTTP on port 81
- Triggers camera ESP for photo/video (via HTTP)
- Publishes to AWS IoT Core (motion events + device shadow heartbeat every 2 min)
- OTA firmware update via `/ota2` Telegram command or Firebase Storage

**Pi-independent paths (survive Pi outage):**
- AWS IoT → Lambda → FCM push notification (app siren)
- Telegram direct alerts
- Firebase RTDB direct write (app bulb sync)

### ESP01-LL-RLY — Lower Lobby Light Relay

| Item | Value |
|------|-------|
| IP | `192.168.1.85` |
| Board | ESP-01 (ESP8266) |
| Project | `/home/pi5/pi5_drive/Git_projects/ESP01-LL-RLY/` |
| MQTT prefix | `home/esp01/lower-lobby/` |
| Relay pin | GPIO0 (active LOW) |

**MQTT topics:**

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `home/esp01/lower-lobby/cmd/relay` | IN | `ON` / `OFF` command |
| `home/esp01/lower-lobby/state` | OUT (retained) | Current relay state |
| `home/esp01/lower-lobby/availability` | OUT | `online` / `offline` LWT |

**Notes:**
- ESP8266 PubSubClient keepalive instability: broker drops at ~90 s; workaround in firmware (stop+delay before reconnect, WIFI_NONE_SLEEP, 10 s heartbeat)
- Pi4 has HTTP fallback (`/lighton`, `/lightoff`) for reliability
- 3-min firmware auto-off timer — Pi tracks `_ll_motion_triggered` flag to re-send ON if light was manual/scheduled

### ESP01-UL-RLY — Upper Lobby Light Relay (Porch)

| Item | Value |
|------|-------|
| IP | `192.168.1.111` |
| Board | ESP-01 (ESP8266) |
| Project | `/home/pi5/pi5_drive/Git_projects/ESP01-UL-RLY/` |
| MQTT prefix | `home/esp01/upper-lobby/` |
| Relay pin | GPIO0 (active LOW) |

**MQTT topics:**

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `home/esp01/upper-lobby/cmd/relay` | IN | `ON` / `OFF` command |
| `home/esp01/upper-lobby/state` | OUT (retained) | Current relay state |
| `home/esp01/upper-lobby/availability` | OUT | `online` / `offline` LWT |

**Notes:**
- Does NOT talk to Firebase directly — ESP32-LP-RDR1 proxies Firebase for it
- Polls ESP32-LP-RDR1 (port 81) every 1 s for commanded state
- ESP32-LP-RDR1 sends motion-triggered relay commands direct via HTTP

### ESP32-LP-RLY — Lower Porch Light Relay

| Item | Value |
|------|-------|
| IP | `192.168.1.89` |
| Board | ESP32 |
| Project | `/home/pi5/pi5_drive/Git_projects/ESP32-LP-RLY/` |
| MQTT prefix | `home/switches/L-Porch-Light/` |
| HTTP port | `1089` |
| Firebase name | `L-Porch-Light` |

**MQTT topics:**

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `home/switches/L-Porch-Light/cmd` | IN (both brokers) | `ON` / `OFF` |
| `home/switches/L-Porch-Light/state` | OUT (VIP broker) | Current state |
| `home/switches/L-Porch-Light/availability` | OUT (VIP broker) | `online`/`offline` LWT |
| `home/switches/L-Porch-Light/state/json` | OUT (VIP broker) | Full JSON status |
| `home/esp32/lp-rly/ota/cmd` | IN | Firebase OTA trigger |

**Dual MQTT client architecture:**

| Client | Broker | Purpose |
|--------|--------|---------|
| Primary (`mqtt`) | `192.168.1.100` → Pi4 | State publish + general commands |
| Secondary (`mqttPi5`) | `192.168.1.108` Pi5 direct | Pi5 commands when Pi4 holds VIP |

Both subscribe to the cmd topic. Pi5's bridge also forwards the cmd topic out to Pi4.

**HTTP endpoints:** `GET /lighton`, `GET /lightoff`, `GET /status`

---

## MQTT Topic Map (Complete)

Broker: Pi4 at `192.168.1.122:1883` — credentials `mq / mq`

```
home/esp01/lower-lobby/cmd/relay     ← Pi publishes (ON/OFF) → ESP01-LL-RLY
home/esp01/lower-lobby/state         → ESP01-LL-RLY publishes (retained)
home/esp01/lower-lobby/availability  → ESP01-LL-RLY LWT

home/esp01/upper-lobby/cmd/relay     ← Pi publishes (ON/OFF) → ESP01-UL-RLY
home/esp01/upper-lobby/state         → ESP01-UL-RLY publishes (retained)
home/esp01/upper-lobby/availability  → ESP01-UL-RLY LWT

home/switches/L-Porch-Light/cmd      ← Pi publishes (ON/OFF) → ESP32-LP-RLY
home/switches/L-Porch-Light/state    → ESP32-LP-RLY publishes (retained)
home/switches/L-Porch-Light/availability → ESP32-LP-RLY LWT
home/switches/L-Porch-Light/state/json  → ESP32-LP-RLY JSON status
home/esp32/lp-rly/ota/cmd           ← OTA trigger
home/esp32/lp-rly/ota/status        → OTA progress → Pi → Telegram
home/esp32/lp-rly/telegram          → ESP32-LP-RLY → Pi → Telegram forward

home/esp32/radar1/motion             → ESP32-LP-RDR1 (ON/OFF) → Pi4 light ctrl
home/esp32/radar1/availability       → ESP32-LP-RDR1 LWT
home/pi5/lp-rdr/motion              → ESP32-LP-RDR1 direct to Pi5 (video trigger)
home/esp32/radar2/motion             → legacy (may still be published)

home/pi5/lp-rdr/motion is on Pi5's broker directly (ESP32-LP-RDR1 dual client)
home/esp32/radar1/# bridges Pi4 → Pi5 via mosquitto bridge
```

---

## Firebase RTDB

URL: `https://home-security-app-555cf-default-rtdb.asia-southeast1.firebasedatabase.app`

### Paths written by Pi

| Path | Writer | Content |
|------|--------|---------|
| `/devices/RASPI-4/` | Pi heartbeat (60 s) | cpuTemp, uptime, motionDetected, recording |
| `/devices/ESP01-LL-RLY/` | Pi | lower lobby relay state |
| `/devices/esp01_relay/` | Pi | upper lobby relay state |
| `/devices/ESP32-LP-RLY/` | Pi | LP porch relay state |
| `/lights/living_room/confirmed` | Pi | after lower lobby MQTT state |
| `/lights/living_room/state` | Pi | current lower lobby state |
| `/lights/lobby/confirmed` | Pi | after upper lobby MQTT state |
| `/lights/lobby/state` | Pi | current upper lobby state |
| `/lights/lower_porch_light/confirmed` | Pi | after LP relay MQTT state |
| `/lights/lower_porch_light/state` | Pi | current LP relay state |

### Paths written by ESP32-LP-RDR1 (Pi-independent)

| Path | Content |
|------|---------|
| `/lights/lobby/` | state + confirmed (direct write when Pi is down) |
| AWS shadow: `radars/{radar2}` | heartbeat every 2 min |

### SSE streams read by Pi (command input)

| Path | Action |
|------|--------|
| `/lights/living_room/state` | → lower lobby relay ON/OFF |
| `/lights/lobby/state` | → upper lobby relay ON/OFF |
| `/lights/lower_porch_light/state` | → LP relay ON/OFF |
| `/schedules/` | → APScheduler light timers |

### Firestore (separate from RTDB)

| Collection | Writer | Purpose |
|------------|--------|---------|
| `door_events` | Pi (`push_door_event`) | Door open/close history for app |

---

## Data Flow — How Everything Connects

### App → Light ON (normal path)

```
Flutter app taps light switch
  ├── Firebase RTDB /lights/{id}/state = true
  │     └── Pi SSE stream fires → MQTT cmd → ESP relay
  └── [WiFi only] HTTP PUT Pi:5757/lights/{id}  (LAN fallback)
        └── Pi local_api_server → MQTT cmd → ESP relay
  (Pi deduplicates if both arrive)
```

### Motion → Lobby Light + Lobby Camera (Pi4 — LD2420 radar)

```
LD2420 radar (/dev/serial0) detects motion in lower lobby
  └── Pi4 main loop
        ├── _trigger_light_control(): night? → MQTT cmd → ESP01-LL-RLY ON
        └── _handle_video_recording(): → picamera2 records lobby area → MP4 → Telegram
```

### Motion → Porch Light + Porch Camera (Pi5 — ESP32-LP-RDR1)

```
ESP32-LP-RDR1 radar (192.168.1.87) detects motion on lower porch
  ├── MQTT home/esp32/radar1/motion=ON → Pi4 broker
  │     ├── Pi4 _handle_radar_lp_rly(): night? → MQTT cmd → ESP32-LP-RLY ON
  │     └── bridges home/esp32/radar1/# → Pi5 broker → Pi5 _do_radar_motion_on()
  │           → Pi5 night? → MQTT cmd → ESP32-LP-RLY ON (idempotent)
  └── MQTT home/pi5/lp-rdr/motion=ON → Pi5 direct (ESP32-LP-RDR1 dual-publishes)
        └── lp_rdr_service.py: picamera2 records porch area → MP4 → Telegram
  (Telegram alert + AWS IoT → Lambda → FCM also fire — Pi-independent)
```

**Key architectural difference:** Pi4 video is handled INSIDE `main.py` (`_handle_video_recording`). Pi5 video is a SEPARATE process (`lp_rdr_service.py` / `mybot-lp-rdr.service`) that receives motion via MQTT `home/pi5/lp-rdr/motion` from ESP32-LP-RDR1 directly.

Note: ESP32-LP-RDR1 publishes to **two brokers** simultaneously — Pi4 broker for porch relay control, Pi5 broker direct for camera trigger. Both `home/esp32/radar1/#` (bridged Pi4→Pi5) and `home/pi5/lp-rdr/motion` (direct) arrive at Pi5.

### Motion → Light OFF (5-min timer)

```
ESP32-LP-RDR1 radar goes LOW for 5 min
  └── MQTT home/esp32/radar1/motion=OFF → Pi
        └── 5-min timer fires → MQTT cmd → relay OFF
```

### Pi Local Sensors → Light

```
LD2420 radar (/dev/serial0, Pi4 only)
  └── Pi _trigger_light_control (VIP master only)
        └── night? → MQTT → ESP01-LL-RLY ON + video recording (Pi4 only)

PIR (GPIO25) / MMS (GPIO27) → also feed motion logic
Reed switch (GPIO26) → Telegram door alert + AWS IoT + Firestore log
```

### VIP / MASTER guard logic (Pi5 code)

Pi5 checks `ip addr show wlan0` for `192.168.1.100` before sending:
- Relay commands (except radar motion — that's always sent by both Pis, idempotent)
- Firebase updates from relay state changes
- App command responses
- Scheduler-triggered commands

**Pattern — always use this exact form:**
```python
try:
    vip = subprocess.run(['ip', 'addr', 'show', 'wlan0'],
                         capture_output=True, text=True, timeout=2)
    is_master = '192.168.1.100' in vip.stdout
except Exception:
    is_master = False  # FAIL-SAFE: never except: pass (that's fail-open = Pi5 acts as master on timeout)
```

**Three places is_master MUST be applied in every `_on_*_mqtt_state` handler:**
1. **Relay command re-sends** — firmware auto-off guard: `if not relay_on and _last_cmd and is_master: re-send ON`
2. **Firebase writes** — `if is_master: push Firebase`
3. **State variable updates** — `_last_*_cmd = relay_on` (always update, no VIP needed — this tracks local knowledge)

### Distributed state problem (Pi4 vs Pi5 — critical for debugging)

Pi4 and Pi5 each maintain **independent copies** of every state variable (`_last_lp_rly_cmd`, `_lp_rly_motion_triggered`, `_lp_rly_manual_off_time`, etc.). They are NOT synchronized directly.

| Variable | How Pi5 learns Pi4's actions |
|----------|------------------------------|
| `_last_lp_rly_cmd` | Updated when Pi5 receives MQTT state feedback via bridge — lags by one round-trip |
| `_lp_rly_manual_off_time` | Updated from Firebase SSE `_on_firebase_lp_rly_cmd(False)` — Pi4 writes Firebase after state=OFF arrives, then Pi5 SSE fires |
| `_lp_rly_motion_triggered` | Pi5 only knows its own radar triggers; doesn't know Pi4's |

**Consequence:** When Pi4 sends LP-RLY OFF, Pi5's `_last_lp_rly_cmd` is still True until the MQTT state=OFF message arrives via bridge. If the firmware auto-off guard fires in that window WITHOUT `is_master`, Pi5 re-sends ON → toggle loop.

**Why `_*_manual_off_time` must be updated from Firebase SSE (not just `_execute_*_cmd`):**
When Pi4 is master, Pi5 never calls `_execute_lp_rly_cmd` — only Pi4 does. So Pi5's `_lp_rly_manual_off_time` would never be set by `_execute_lp_rly_cmd`. The only reliable way for Pi5 to learn of a manual OFF is via Firebase SSE (`_on_firebase_lp_rly_cmd(False)`), which fires whether the OFF was initiated by the app via local HTTP to Pi4 or directly via Firebase.

### LP-RLY Dual-Pi Control — How It All Connects

LP-RLY (porch light) is unique: **both Pis can independently command it**, because the radar (ESP32-LP-RDR1) publishes motion to BOTH brokers (`home/esp32/radar1/motion` → Pi4 via bridge, and `home/pi5/lp-rdr/motion` → Pi5 direct).

**App turns porch light OFF via local HTTP (Pi4 master):**
```
App PUT 192.168.1.100:5757/lights/lower_porch_light
  └── Pi4 _execute_lp_rly_cmd(False)
        → Pi4: _last_lp_rly_cmd=False, _lp_rly_manual_off_time=now
        → MQTT home/switches/L-Porch-Light/cmd=OFF → ESP32-LP-RLY
              → relay OFF → publishes state=OFF on Pi4 broker
              → Pi4 _on_lp_rly_mqtt_state(OFF): writes Firebase lower_porch_light/state=false
                    → Pi5 SSE fires _on_firebase_lp_rly_cmd(False)
                          → Pi5: _lp_rly_manual_off_time=now (suppresses radar 120s)
              → Pi5 bridge receives state=OFF → Pi5 _on_lp_rly_mqtt_state(OFF)
                    → is_master=False → firmware guard SKIPPED (no re-send ON)
                    → Pi5: _last_lp_rly_cmd=False
```

**Radar motion → LP-RLY ON (both Pis night-time):**
```
ESP32-LP-RDR1 detects motion
  ├── MQTT home/esp32/radar1/motion=ON → Pi4 broker
  │     └── Pi4 _handle_radar_lp_rly(): checks _lp_rly_manual_off_time → sends ON
  └── MQTT home/pi5/lp-rdr/motion=ON → Pi5 broker (direct)
        └── Pi5 _do_radar_motion_on(): checks _lp_rly_manual_off_time → sends ON (if not suppressed)
```
Both Pis may send ON — that's idempotent (relay is already ON). The 120s `_lp_rly_manual_off_time` on each Pi independently suppresses radar re-trigger after manual OFF.

---

## What Survives a Pi Outage

| Feature | Pi needed? | Path |
|---------|-----------|------|
| App siren on motion | No | ESP32-LP-RDR1 → AWS IoT → Lambda → FCM |
| Telegram motion alert | No | ESP32-LP-RDR1 → Telegram API direct |
| AWS shadow heartbeat | No | ESP32-LP-RDR1 → AWS IoT |
| App lobby bulb sync | No | ESP32-LP-RDR1 → Firebase direct |
| Video recording | Yes | Pi5 camera required |
| App light switches | Yes | Pi required for Firebase SSE → MQTT |
| Scheduled light timers | Yes | APScheduler runs on Pi |
| DHT11 logging | Yes | Pi MQTT subscription required |
| Door alerts | Yes | Pi GPIO + Telegram/Firebase |

---

## Git Repositories

### On Pi5 (`/home/pi5/pi5_drive/Git_projects/`)

| Repo | GitHub | Purpose |
|------|--------|---------|
| `RASPI5-MAIN` | `bs220975/RASPI5-MAIN` | Pi5 main bot |
| `ESP32-LP-RDR1` | — | Main radar firmware (ESP32) |
| `ESP01-LL-RLY` | `bs220975/ESP01-LL-RLY` | Lower lobby relay firmware (ESP8266) |
| `ESP01-UL-RLY` | — | Upper lobby relay firmware (ESP8266) |
| `ESP32-LP-RLY` | — | LP porch relay firmware (ESP32) |
| `HOMESECURITY-APP` | — | Flutter Android app |
| `RASPI4-MAIN` | `bs220975/RASPI4-MAIN` | Pi4 main bot (mirror/dev) |
| `ESP32-RADAR` | — | Old/legacy radar project |
| `ESP32-DHT11` | — | Standalone DHT11 project |
| `ESP32-S3-XIAO-CAMERA` | — | Camera ESP project |

### On Pi4 only (`/home/pi/pi4_drive/Git_projects/`)

| Repo | Purpose |
|------|---------|
| `RASPI4-MAIN` | Pi4 main bot (production) |
| `ESP01-LL-RLY` | Lower lobby relay |
| `ESP01-UL-RLY` | Upper lobby relay |
| `ESP32-LP-RDR1` | Main radar |
| `ESP32-LP-RLY` | LP porch relay |
| `ESP32-RADAR` | Legacy radar |
| `HOMESECURITY-APP` | Flutter app |

---

## Known Issues / Ongoing Work

| Issue | Status | Notes |
|-------|--------|-------|
| Reed switch false door alerts | Software fix applied | Debounce 2.0 s, cooldown 5 s in `sensors.py`; hardware RC filter (10 kΩ + 100 nF on GPIO 26) not yet soldered |
| LD2420 EMI on GPIO 26 | Root cause identified | Radar ~10 cm from Pi couples RF into reed switch wire; move radar ≥30 cm or add RC filter |
| ESP01 MQTT keepalive instability | Workaround in firmware | PubSubClient on ESP8266 drops at ~90 s; permanent fix = AsyncMqttClient (not yet done) |
| Keepalived DISABLED | By design | JioFiber IP source guard blocked VIP traffic; .100 kept as static alias on Pi4 wlan0 for app backward compat |
| Pi5 MQTT_HOST=localhost | By design | Pi5 mybot connects to its own broker; bridge from Pi4 delivers ESP events |
| LL-RLY spurious ON on Pi5 start | FIXED 2026-06-23 | 6 methods missing VIP guard — `except Exception: pass` (fail-open) let Pi5 act as master on subprocess timeout; changed to `except Exception: return`; commit 74f996b |
| LP-RLY toggle loop (local HTTP path) | FIXED 2026-06-24 | 3 Pi5 bugs: (1) firmware auto-off guard in `_on_lp_rly_mqtt_state` had no `is_master` check — Pi5 immediately re-sent ON after Pi4's deliberate OFF because Pi5's stale `_last_lp_rly_cmd=True`; (2) Firebase write in same handler had no `is_master`; (3) `_do_radar_motion_on` had no `_lp_rly_manual_off_time` guard. commit fdf0585 |
| Pi4 activate() state vars not set on MQTT-only success | FIXED 2026-06-23 | `_ll_motion_triggered` and `_last_living_room_cmd` only set when HTTP also succeeded; fixed with `sent=True` pattern (MQTT OR HTTP); commit 59c0edc |
| ESP32-LP-RDR1 MQTT keepalive bug | FIXED 2026-06-16 | `setKeepAlive(60)` + `mqttClient.loop()` at start of loop; commit 107bfbb (needs OTA flash) |

---

## Cloud Services

| Service | Provider | Purpose |
|---------|----------|---------|
| Firebase RTDB | Google | App ↔ Pi command channel + device state |
| Firebase Firestore | Google | Door event history |
| Firebase Storage | Google | OTA firmware files |
| AWS IoT Core | Amazon | Motion events + device shadows |
| AWS Lambda | Amazon | IoT → FCM push notification pipeline |
| Telegram Bot API | Telegram | Alerts + remote control |
| InfluxDB (local) | Self-hosted Pi4 | Motion event time-series metrics |

---

## Network Details

| Item | Value |
|------|-------|
| Router/gateway | `192.168.1.254` |
| Pi4 IP | `192.168.1.122` (DHCP reserved) |
| Pi5 IP | `192.168.1.108` (DHCP reserved) |
| VIP alias | `192.168.1.100` static secondary on Pi4 wlan0 (not VRRP) |
| MQTT broker | `192.168.1.122:1883` (Pi4) credentials `mq / mq` |
| InfluxDB | `http://[::1]:8086` org: `pi4org` bucket: `pi4data` |
| Firebase RTDB | `home-security-app-555cf-default-rtdb.asia-southeast1.firebasedatabase.app` |
| Local API | `Pi4:5757` + `Pi5:5757` — Flutter app LAN fallback |

---

## Quick Reference Commands

```bash
# ── MQTT ─────────────────────────────────────────────────────────────
# Watch all MQTT traffic
mosquitto_sub -h localhost -p 1883 -u mq -P mq -t "home/#" -v

# Watch specific device
mosquitto_sub -h 192.168.1.122 -p 1883 -u mq -P mq -t "home/esp01/lower-lobby/#" -v
mosquitto_sub -h 192.168.1.122 -p 1883 -u mq -P mq -t "home/esp32/radar1/#" -v
mosquitto_sub -h 192.168.1.122 -p 1883 -u mq -P mq -t "home/switches/L-Porch-Light/#" -v

# Manually command relays
mosquitto_pub -h localhost -p 1883 -u mq -P mq -t "home/esp01/lower-lobby/cmd/relay" -m "ON"
mosquitto_pub -h localhost -p 1883 -u mq -P mq -t "home/esp01/upper-lobby/cmd/relay" -m "ON"
mosquitto_pub -h localhost -p 1883 -u mq -P mq -t "home/switches/L-Porch-Light/cmd" -m "ON"

# ── Pi5 Services ─────────────────────────────────────────────────────
sudo systemctl restart mybot.service
journalctl -u mybot.service -f          # live log (alias: servicemybot)
systemctl status mosquitto              # alias: statusmqtt

# Run bot manually (debug)
cd /home/pi5/pi5_drive/Git_projects/RASPI5-MAIN
source /home/pi5/myenv/bin/activate
python3 main.py

# ── Pi4 Commands (via SSH) ───────────────────────────────────────────
ssh pi@192.168.1.122
sudo systemctl restart mybot.service
journalctl -u mybot.service -f

# ── GPIO ─────────────────────────────────────────────────────────────
watch -n 0.5 "raspi-gpio get 26"       # reed switch live monitor
vcgencmd get_throttled                  # 0x0 = healthy
vcgencmd measure_volts core             # normal ~0.866V

# ── Camera / Video ───────────────────────────────────────────────────
ls -lh /home/pi5/raspi_camera_videos/

# ── Logs ─────────────────────────────────────────────────────────────
journalctl -u mybot.service --since "30 min ago" | grep -i door
journalctl -u mybot.service --since "1 hour ago" | grep -i "relay\|light\|motion"

# ── PlatformIO (ESP firmware) ────────────────────────────────────────
cd /home/pi5/pi5_drive/Git_projects/ESP32-LP-RLY
/home/pi5/.platformio/penv/bin/pio run --target upload

# ── Navigation ───────────────────────────────────────────────────────
# cdmain  → RASPI5-MAIN (Pi5) or RASPI4-MAIN (Pi4)
# cdgit   → Git_projects folder on either Pi
```

---

## Pi4 vs Pi5 Comparison

| Item | Pi4 (Primary Hub) | Pi5 (Camera Node) |
|------|-------------------|-------------------|
| Role | Main MQTT broker, all logic | Camera recording, BACKUP logic |
| IP | 192.168.1.122 | 192.168.1.108 |
| User | `pi` | `pi5` |
| Camera | Yes — CSI camera, **lower lobby area** | Yes — CSI camera, **lower porch area** |
| MQTT broker | Primary (ESP devices connect here) | Bridges from Pi4 |
| mybot MQTT_HOST | 192.168.1.122 | localhost |
| InfluxDB | Yes (main) | Yes (secondary) |
| LD2420 radar | Yes (GPIO 14/15) | Yes (GPIO 14/15) |
| Firebase key | `RASPI-4` | `RASPI-5` (but heartbeat still PATCHes `/devices/RASPI-4/`) |
| Drive folder | `pi4_drive` | `pi5_drive` |
| Keepalived | DISABLED | BACKUP role (was 100) — also disabled |
| VIP .100 | Static secondary alias on wlan0 | Not assigned |
