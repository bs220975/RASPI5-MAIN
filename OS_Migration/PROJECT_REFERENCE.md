# Raspberry Pi 4 — Project Reference

> Single reference document for the RASPI4-MAIN home automation project.
> All setup, architecture, implementation log, and troubleshooting in one place.

---

## Revision History

| Date | Changes |
|---|---|
| 2026-05-13 | Phase 1 Firebase SSE streaming implemented. Phase 2 MQTT bridge implemented. ESP01-LL-RLY MQTT firmware verified live. Both repos pushed to GitHub. |
| 2026-05-14 | Full project folder reorganisation — all files consolidated inside `RASPI4-MAIN/`. Shell scripts rewritten (`backup.sh` → rsync with progress; `sync.sh` → fixed stderr capture and rclone v1.60 grep). Broken aliases fixed. `logs/` created; `influx_aws_publish/` moved in. Service files updated with correct paths. File renamed from `ARCHITECTURE_MQTT_FIREBASE_BRIDGE.md` to `PROJECT_REFERENCE.md`. README.md, COMPLETE_FLOW.md, and rclone_setup.md merged into this file. |
| 2026-05-14 | Reed switch door sensor added on GPIO 26. Edge-triggered callbacks in `sensors.py`. Telegram alerts on door open/close. Log path in `config.py` corrected. |

---

## Quick Navigation

**System**
- [Environment & Credentials](#environment--credentials)
- [Project Folder Structure](#project-folder-structure)
- [Key Paths](#key-paths)
- [Services](#services)
- [Aliases Reference](#aliases-reference)
- [Hardware — GPIO Pins](#hardware--gpio-pins)

**OS Migration (fresh reimage)**
- [Before Reimaging — Backup](#part-1--before-reimaging-old-pi)
- [Flash New OS](#step-b--flash-new-os)
- [Post-Install Setup](#part-2--after-reimaging-new-pi)
- [Google Drive rclone Setup](#google-drive--rclone-setup)
- [Manual Steps After Setup](#manual-steps-after-setup)
- [Troubleshooting](#troubleshooting)

**Architecture**
- [Goal](#goal)
- [Recommended Architecture](#recommended-architecture)
- [Communication Model](#communication-model)
- [MQTT Topic Design](#recommended-mqtt-topic-design)
- [Heartbeat & Live Status](#heartbeat-and-live-status-architecture)
- [OTA Firmware Update Architecture](#ota-firmware-update-architecture)

**Implementation Log**
- [Environment Details](#environment)
- [Completed Work](#completed)
- [Pending Work](#pending)
- [Next Session — Start Here](#next-session--start-here)

---

## Environment & Credentials

| Item | Value |
|---|---|
| Raspberry Pi LAN IP | `192.168.1.122` |
| Mosquitto broker | `localhost:1883` |
| Mosquitto credentials | `mq / mq` |
| ESP01-LL-RLY static IP | `192.168.1.85` |
| Firebase RTDB URL | `https://home-security-app-555cf-default-rtdb.asia-southeast1.firebasedatabase.app` |
| RASPI4-MAIN repo | `https://github.com/bs220975/RASPI4-MAIN` — branch `main` |
| ESP01-LL-RLY repo | `https://github.com/bs220975/ESP01-LL-RLY` — branch `master` |

---

## Project Folder Structure

```
RASPI4-MAIN/
├── main.py                        ← Service entry point
├── config.py                      ← All configuration (GPIO, MQTT, Firebase, etc.)
├── sensors.py                     ← Radar, PIR, MMS, reed switch
├── bot_commands.py                ← Telegram bot command handlers
├── telegram_handler.py            ← Telegram API wrapper
├── esp_devices.py                 ← HTTP control for ESP devices
├── mqtt_bridge.py                 ← Local Mosquitto MQTT bridge
├── firebase_logger.py             ← Firebase RTDB read/write
├── influxdb_logger.py             ← InfluxDB metrics logging
├── video_recorder.py              ← Pi camera recording
├── aws_certs/                     ← AWS IoT certificates
├── influx_aws_publish/            ← InfluxDB → AWS publisher (mqttdatainflux service)
├── logs/                          ← Runtime service logs (gitignored)
├── shell_scripts/                 ← backup.sh, sync.sh
├── alias_command_file/            ← .bash_aliases backup
├── not_using/                     ← Archived old code
└── OS_Migration/                  ← This folder
    ├── PROJECT_REFERENCE.md       ← This file
    ├── scripts/                   ← 1_backup, 2_post_install, 3_verify
    ├── services/                  ← mybot.service, mqttdatainflux.service
    └── configs/                   ← pip, apt, bashrc, mosquitto configs
```

---

## Key Paths

| Path | Purpose |
|---|---|
| `/home/pi/myenv/` | Python virtual environment |
| `/home/pi/pi4_drive/Git_projects/RASPI4-MAIN/` | Main project (GitHub) |
| `/home/pi/pi4_drive/Git_projects/RASPI4-MAIN/logs/` | Service logs |
| `/home/pi/pi4_drive/Git_projects/RASPI4-MAIN/shell_scripts/` | sync.sh, backup.sh |
| `/home/pi/pi4_drive/Git_projects/RASPI4-MAIN/OS_Migration/services/` | Service file backups |
| `/home/pi/pi4_drive/Git_projects/RASPI4-MAIN/alias_command_file/` | .bash_aliases backup |
| `/home/pi/Non-Sync_backup_folder/` | Local backup destination (backup.sh) |
| `~/.config/rclone/rclone.conf` | Google Drive auth config (do NOT commit) |

---

## Services

| Service | Script | Autostart | Restart Policy |
|---|---|---|---|
| `mybot.service` | `RASPI4-MAIN/main.py` | YES | `always` — 5 crashes in 5 min → Pi reboots |
| `mqttdatainflux.service` | `RASPI4-MAIN/influx_aws_publish/influxdb2_aws_publish.py` | YES | `on-failure` — max 1 restart per 5 min |
| `mybot2.service` | (old Pi5 service) | NO | manual enable only if needed |
| `mosquitto` | MQTT broker port 1883 | YES | system default |
| `influxdb` | InfluxDB 2.x port 8086 | YES | system default |
| `ssh` | Remote access | YES | system default |
| `cron` | Scheduled tasks | YES | system default |

**Service aliases:**

```bash
statusmybot / startmybot / restartmybot / stopmybot / servicemybot
statusmqtt  / startmqtt  / restartmqtt  / stopmqtt  / servicemqtt
copymybot   # copy mybot.service to /etc/systemd/system/
copymqtt    # copy mqttdatainflux.service to /etc/systemd/system/
reloadmybot # daemon-reload
```

---

## Aliases Reference

| Alias | What it does |
|---|---|
| `myenv` | Activate Python virtual environment |
| `cdmain` | `cd` to RASPI4-MAIN project |
| `sync` | Interactive Google Drive ↔ Pi sync (rclone) |
| `backup` | Local backup of pi4_drive with rsync + progress |
| `copyalias` | Save updated `.bash_aliases` to `alias_command_file/` |
| `statusmybot` | `systemctl status mybot.service` |
| `startmybot` | Start mybot service |
| `restartmybot` | Restart mybot service |
| `servicemybot` | Live log stream for mybot |
| `statusmqtt` | `systemctl status mqttdatainflux.service` |
| `startmqtt` | Start mqttdatainflux service |
| `servicemqtt` | Live log stream for mqttdatainflux |

Run `source ~/.bash_aliases` to reload after editing.

---

## Hardware — GPIO Pins

BCM pin numbering. All configured in `config.py → GPIOConfig`.

| Pin | Sensor | Notes |
|---|---|---|
| GPIO 25 | PIR motion sensor | pull_up=False |
| GPIO 27 | MMS microwave sensor | pull_up=False |
| GPIO 18 | Status LED | output |
| GPIO 26 | Reed switch (door) | pull_up=True, other leg to GND. HIGH = door open, LOW = door closed |

Reed switch Telegram alerts: `🚪 Door OPENED — DD/MM/YY HH:MM:SS` / `🔒 Door CLOSED — ...`

---

## OS Migration (Fresh Reimage)

Current OS before reimage: Raspbian GNU/Linux 12 Bookworm — 32-bit (armhf).
Target after reimage: Raspberry Pi OS 64-bit Bookworm — arm64.

### Overview

```
OLD PI (32-bit)              GOOGLE DRIVE                 NEW PI (64-bit)
─────────────────            ─────────────────            ─────────────────
Run backup script   ──────►  gdrive:/pi4_backups/    ──►  Post-install script
                             gdrive:/pi4_drive/            auto-restores all
                    ──────►                               ↓
                             github.com/bs220975/         gh repo clone
                             RASPI4-MAIN             ──►  RASPI4-MAIN
```

---

### Part 1 — Before Reimaging (Old Pi)

#### Step A — Run Backup Script

```bash
bash /home/pi/pi4_drive/Git_projects/RASPI4-MAIN/OS_Migration/scripts/1_backup_before_reimage.sh
```

What it backs up:

| Item | Destination |
|---|---|
| apt package list | `gdrive:/pi4_backups/pre_reimage_DATE/apt/` |
| pip packages (myenv + root) | `gdrive:/pi4_backups/pre_reimage_DATE/pip/` |
| systemd service files | `gdrive:/pi4_backups/pre_reimage_DATE/services/` |
| Mosquitto config | `gdrive:/pi4_backups/pre_reimage_DATE/mosquitto/` |
| Crontabs (pi + root) | `gdrive:/pi4_backups/pre_reimage_DATE/crontab/` |
| SSH keys | `gdrive:/pi4_backups/pre_reimage_DATE/ssh/` |
| AWS certs | `gdrive:/pi4_backups/pre_reimage_DATE/aws_certs/` |
| .bashrc + .bash_aliases + rclone.conf | `gdrive:/pi4_backups/pre_reimage_DATE/configs/` |
| InfluxDB data | `gdrive:/pi4_backups/pre_reimage_DATE/influxdb/` |
| pi4_drive + code | `gdrive:/pi4_backups/pre_reimage_DATE/code/` |

> Size limit: 600 MB — uploads to Google Drive if under limit, otherwise stages to `/tmp/pi4_backup_staging/` for manual USB copy.

#### Step B — Flash New OS

1. Download **Raspberry Pi Imager** → [raspberrypi.com/software](https://www.raspberrypi.com/software/)
2. Select device: **Raspberry Pi 4**
3. Select OS: **Raspberry Pi OS (64-bit)** — Bookworm
4. Click gear icon ⚙ before flashing:
   - Hostname: `pi`
   - Enable SSH ✓
   - Username: `pi`, Password: *(your password)*
   - WiFi SSID + password ✓
5. Flash SD card, insert into Pi4, power on, wait ~60 seconds

---

### Part 2 — After Reimaging (New Pi)

#### Step 1 — SSH In

```bash
ssh pi@<pi-ip-address>
# or:
ssh pi@pi.local
```

#### Step 2 — Run Post-Install Script

```bash
wget -qO- https://raw.githubusercontent.com/bs220975/RASPI4-MAIN/main/OS_Migration/scripts/2_post_install_setup.sh | bash
```

What the script does (12 steps):

| Step | Action |
|---|---|
| 1 | `apt update` + install all packages (git, python3, rclone, mosquitto, cups…) + Node.js 20 LTS |
| 2 | GitHub CLI (`gh auth login`) — opens browser to authenticate |
| 3 | rclone Google Drive setup — restores `rclone.conf` from backup |
| 4 | Creates `/home/pi/pi4_drive/` + syncs from `gdrive:/pi4_backups/` and `gdrive:/pi4_drive/` |
| 5 | Clones `RASPI4-MAIN` from GitHub into `pi4_drive/Git_projects/` |
| 6 | Creates Python `myenv` + installs pip packages from `pip_myenv.txt` |
| 7 | Installs InfluxDB2 arm64 |
| 8 | Configures Mosquitto MQTT (restores config or creates fresh with `mq/mq`) |
| 9 | Installs + enables systemd services (autostart on boot) |
| 10 | Restores AWS certs (from Drive backup) |
| 11 | Restores `.bashrc` + `.bash_aliases` |
| 12 | Installs Claude CLI (`npm install -g @anthropic-ai/claude-code`) |

#### Step 3 — Verify

```bash
bash /home/pi/pi4_drive/Git_projects/RASPI4-MAIN/OS_Migration/scripts/3_verify_setup.sh
```

Expected output:
```
  [PASS] 64-bit OS confirmed
  [PASS] SSH enabled & running
  [PASS] Mosquitto enabled / running
  [PASS] InfluxDB enabled / running
  [PASS] mybot enabled (autostart) / running
  [PASS] mqttdatainflux enabled / running
  [PASS] logs folder exists
  [PASS] mybot script exists
  [PASS] influx script exists
  [PASS] python3 / myenv / paho-mqtt / influxdb_client / telepot
  [PASS] git / gh / rclone / influx / mosquitto_pub / node / claude
  [PASS] MQTT test pub/sub
  [PASS] InfluxDB HTTP
  [PASS] Internet
  [PASS] aws_certs dir exists
```

#### Step 4 — Start Services

```bash
sudo systemctl start mybot.service
sudo systemctl start mqttdatainflux.service
```

#### Step 5 — Re-login for Aliases

```bash
source ~/.bashrc
```

---

### Google Drive / rclone Setup

> Do NOT store `rclone.conf` in git — it contains OAuth tokens.

#### First-time rclone config

```bash
rclone config
# n) New remote
# name> gdrive
# Storage type: drive (Google Drive)
# client_id / client_secret: leave blank
# scope: 1 (full access)
# Use auto config: y  (opens browser)
# Configure as shared drive: n
```

#### Verify

```bash
rclone lsd gdrive:/
rclone ls gdrive:/pi4_drive/
```

#### Sync (interactive — uses sync.sh)

```bash
sync
# Prompts: 1) Drive → Pi   2) Pi → Drive
# Shows dry-run file list first, then asks to confirm
```

---

### Manual Steps After Setup

1. **AWS Certs** — if not auto-restored:
   ```bash
   cp -r /media/pi/USB/pre_reimage_*/aws_certs/ \
     /home/pi/pi4_drive/Git_projects/RASPI4-MAIN/aws_certs/
   ```

2. **InfluxDB data** — restore from backup:
   ```bash
   influx restore /media/pi/USB/pre_reimage_*/influxdb/
   ```

3. **Crontab** — restore:
   ```bash
   crontab /media/pi/USB/pre_reimage_*/crontab/crontab_pi.txt
   ```

4. **Google Drive sync** — if rclone config not auto-restored:
   ```bash
   rclone config
   # Add remote named "gdrive" → Google Drive
   rclone sync gdrive:/pi4_drive /home/pi/pi4_drive --progress
   ```

---

### Google Drive Folder Structure

```
gdrive:/
├── pi4_drive/                        ← Live working folder (rclone synced)
│   └── Git_projects/
│       └── RASPI4-MAIN/              ← All project files (code, scripts, logs, services)
│
└── pi4_backups/                      ← Pre-reimage snapshots
    └── pre_reimage_2026-05-11_09-30/
        ├── apt/ pip/ services/ mosquitto/
        ├── crontab/ ssh/ aws_certs/
        ├── configs/                  ← includes rclone.conf
        ├── influxdb/
        └── code/
```

---

### Troubleshooting

| Problem | Fix |
|---|---|
| `mqttdatainflux` crashes at boot | AWS certs missing — restore from `gdrive:/pi4_backups/` |
| `mybot` not connecting | Check `config.py` Telegram token and chat ID |
| Aliases not working | Run `source ~/.bashrc` or re-login |
| Drive sync fails | Run `rclone config` to re-authenticate |
| InfluxDB not found | `which influx` — if missing, re-run Step 7 manually |
| 32-bit OS flashed by mistake | `getconf LONG_BIT` → should return `64` |
| Reed switch no alerts | Check GPIO 26 wiring; one leg to GPIO 26, other to GND |
| Door alert fires on startup | Normal — `when_deactivated` fires once on init if door is open |

---

## Architecture — MQTT + Firebase Bridge

### Goal

Use the Raspberry Pi as the single always-on bridge between:

- local ESP01 / ESP32 devices
- local Mosquitto MQTT broker
- Firebase Realtime Database
- local automations (motion-triggered switching, door alerts)

This removes the need for low-memory ESP devices to maintain multiple direct cloud TCP/TLS connections to Firebase.

### Recommended Architecture

```
ESP01 / ESP32 devices  <->  Mosquitto on Raspberry Pi  <->  Raspberry Pi bridge  <->  Firebase RTDB
                                              |
                                              +-> local automations / Telegram / sensors
```

#### ESP device responsibilities

- connect to local Wi-Fi
- open one MQTT connection to Mosquitto on the Raspberry Pi
- subscribe to command topics
- publish state, telemetry, and availability topics
- avoid direct Firebase communication

#### Raspberry Pi responsibilities

- run Mosquitto as the local MQTT broker
- run one bridge process for MQTT ↔ Firebase RTDB
- receive local state from ESP devices
- publish local commands to ESP devices
- stream Firebase app commands and convert them to MQTT commands
- update Firebase RTDB with filtered device state and confirmations
- handle retries, reconnects, state cache, logging, and automation logic

#### Firebase RTDB responsibilities

- Android app state
- remote control commands
- live status visible outside LAN
- confirmed switch state
- selected alerts and summaries

Firebase should not be the primary transport between ESP devices and the local network.

---

### Communication Model

**Control path:**
```
Android app → Firebase RTDB → Raspberry Pi Firebase listener → MQTT publish → ESP device
```

**Status path:**
```
ESP device → MQTT publish → Raspberry Pi bridge → Firebase RTDB
```

**Local automation path:**
```
Pi sensor event → Raspberry Pi automation → MQTT publish → ESP device
```

---

### Recommended MQTT Topic Design

#### Commands from Pi to devices

- `home/esp01/lobby/cmd/relay`
- `home/esp32/porch/cmd/light`
- `home/esp32/gsm/cmd/reed`

#### State from devices to Pi

- `home/esp01/lobby/state`
- `home/esp01/lobby/availability`
- `home/esp32/porch/state`
- `home/esp32/porch/telemetry`

#### Example payloads

Command: `ON` / `OFF` / `RESET`

State:
```json
{ "relay": true, "rssi": -67, "uptime": 12345 }
```

#### MQTT practices

- Last Will and Testament: each device publishes `online` on connect, `offline` as LWT
- Retained messages: use for desired state and latest known state topics
- QoS 0 for frequent telemetry, QoS 1 for relay commands and important state

---

### Raspberry Pi Bridge Responsibilities

**1. MQTT client / broker integration**
- subscribe to all ESP state topics
- publish commands to device command topics
- detect availability changes
- maintain last-known-state cache

**2. Firebase bridge**
- write selected MQTT state into RTDB
- listen to RTDB command changes via SSE streaming connection
- convert Firebase commands into MQTT publishes
- write confirmed device state back to RTDB

**3. Local automation engine**
- react to radar, PIR, MMS, reed switch events
- publish MQTT commands for local switching
- update Telegram and Firebase when state changes

> Do not mirror every raw sensor event to Firebase — push only useful cloud-visible state, alerts, summaries, and confirmations.

---

### Heartbeat and Live Status Architecture

```
ESP device → MQTT heartbeat / state → Raspberry Pi bridge → Firebase RTDB → app
```

Each MQTT device publishes:
- `home/<device_id>/availability` — `online` on connect, `offline` as LWT
- `home/<device_id>/state` — current state

Raspberry Pi:
- subscribes to availability and state topics for all managed devices
- detects online/offline changes
- updates Firebase RTDB with selected fields
- avoids direct IP polling for MQTT-native devices

Firebase fields per device:
```json
{
  "reachable": true,
  "lastSeen": 1778570000000,
  "relayState": true,
  "rssi": -64,
  "firmwareVersion": "1.2.3"
}
```

Update policy: write on online/offline transitions and important state changes. Refresh `lastSeen` every 30–120 seconds. Do not push every sensor reading.

---

### OTA Firmware Update Architecture

Recommended control path:
```
Firebase app → Firebase RTDB → Raspberry Pi OTA controller → MQTT OTA → ESP device
```

Recommended model:
- Firebase stores OTA intent and version metadata
- Raspberry Pi validates the request, serves firmware over HTTP on LAN
- ESP downloads firmware from Pi (avoids cloud TLS)
- ESP flashes and reports progress via MQTT
- Pi writes final state to Firebase RTDB

MQTT topics:
- `home/<device_id>/cmd/ota` — OTA command
- `home/<device_id>/ota/progress` — progress reporting
- `home/<device_id>/ota/status` — final status

Example OTA command:
```json
{
  "version": "1.2.3",
  "url": "http://192.168.1.122/fw/esp32_porch_v1.2.3.bin",
  "sha256": "abc123...",
  "size": 524288,
  "force": false
}
```

Notes: ESP32 is a good OTA target. ESP01 needs extra care — validate flash size and partition layout before implementing OTA.

---

## Implementation Log

### Lessons Learned

**Bootstrap vs relay firmware (important)**
The `esp01_bootstrap_ota` and `esp01_relay_ota` environments both upload to the same IP.
Always use `pio run -e esp01_relay_ota --target upload` for production relay firmware.
Bootstrap is only for blank devices that need OTA capability first.
Symptom of bootstrap running: device pings, port 80 closed, port 8266 open, no MQTT.

---

### Completed

#### Infrastructure

- [x] Mosquitto installed and running on Pi with authentication (`mq / mq`)
- [x] `paho-mqtt` installed in myenv
- [x] Git identity configured (`bs220975 / bs220975@gmail.com`)
- [x] `gh` CLI 2.92.0 and `git` 2.47.3 installed

#### Phase 1 — Firebase SSE streaming

- [x] `firebase_logger.py` — added `start_command_stream(light_id, callback)`
  - Persistent SSE connection to `lights/<light_id>/state`
  - Auto-reconnects with 5s backoff
- [x] `main.py` — removed 1-second Firebase REST polling loop
- [x] `main.py` — added `_on_firebase_light_cmd(cmd)` with debounce (400ms)
- [x] Firebase paths preserved: `lights/living_room/state`, `lights/living_room/confirmed`, `devices/RASPI-4`, `devices/ESP01-LL-RLY`, `lights/live`

#### Phase 2 — MQTT bridge

- [x] `mqtt_bridge.py` — `MqttBridge` class connecting to local Mosquitto
  - Subscribes to `home/esp01/lobby/state` and `home/esp01/lobby/availability` (QoS 1)
  - Publishes ON/OFF to `home/esp01/lobby/cmd/relay` (QoS 1)
  - Graceful degradation if `paho-mqtt` not installed
- [x] `config.py` — `MqttConfig` dataclass with env var support
- [x] `main.py` — MQTT bridge initialised; tries MQTT first, HTTP fallback

#### ESP01-LL-RLY firmware — MQTT verified live

- [x] `platformio.ini` — added `knolleary/PubSubClient@^2.8`
- [x] MQTT constants: broker `192.168.1.122:1883`, client `esp01-ll-rly`, user `mq/mq`
- [x] Topics: `home/esp01/lobby/cmd/relay`, `home/esp01/lobby/state`, `home/esp01/lobby/availability`
- [x] `mqttConnect()` with LWT (`offline`, retained), publishes `online`, subscribes cmd topic
- [x] HTTP endpoints preserved: `/lighton`, `/lightoff`, `/status`, ArduinoOTA
- [x] **MQTT verified live:** relay responds to ON/OFF commands via MQTT

#### Project restructure (2026-05-14)

- [x] All project files consolidated inside `RASPI4-MAIN/`
- [x] `shell_scripts/` — `backup.sh` rewritten with rsync + progress; `sync.sh` fixed stderr capture
- [x] `logs/` folder created; `influx_aws_publish/` moved in
- [x] Service files updated with correct paths
- [x] All aliases fixed and verified
- [x] `ace_design_projects/RASPI4-MAIN` archived as `RASPI4-MAIN_OLD_BACKUP`

#### Reed switch door sensor (2026-05-14)

- [x] `config.py` — `reed_switch_pin = 26` added to `GPIOConfig`; log path fixed
- [x] `sensors.py` — reed switch initialised with `pull_up=True`, 50ms debounce
  - Edge-triggered: `when_deactivated` → door open, `when_activated` → door closed
  - `set_reed_callbacks(on_open, on_close)` added
  - `SensorState` updated with `door_open` field
- [x] `main.py` — `_on_door_open` / `_on_door_close` send timestamped Telegram alerts

#### GitHub — repos pushed

- [x] `RASPI4-MAIN` — current on `main`
- [x] `ESP01-LL-RLY` — commit `adb055a` on `master`

---

### Pending

#### End-to-end app test

- [ ] Run `main.py` and test Living Room switch via Android app
- [ ] Confirm `lights/living_room/confirmed` updates correctly
- [ ] Confirm motion-triggered relay works via MQTT

#### DHT11_ESP32 auth fix

- [ ] `DHT11_ESP32-10B37A-V1` at `192.168.1.87` — failing Mosquitto auth every 5 min
- [ ] Fix: add credentials to Mosquitto or reflash firmware with `mq / mq`

#### Phase 3 — Route all app commands through Pi MQTT bridge

- [ ] Extend Firebase SSE stream to cover additional device command paths
- [ ] Map each Firebase command path to its MQTT device topic
- [ ] Pi writes confirmation back after MQTT state received

#### Phase 4 — Remove direct cloud logic from ESP devices

- [ ] Remove any remaining Firebase direct writes from ESP firmware
- [ ] Pi becomes sole cloud integration point

#### Other devices — MQTT migration

- [ ] ESP01_Porch (`192.168.1.89`) — light, HTTP only → migrate to MQTT
- [ ] ESP32_GSM (`192.168.1.91`) — reed alert → migrate to MQTT
- [ ] ESP8266_DHT (`192.168.1.87`) — DHT11 sensor → fix auth then migrate
- [ ] ESP32_OLED (`192.168.1.102`), ESP32_ENERGY (`192.168.1.131`) — assess and schedule

#### OTA firmware update architecture

- [ ] Design and implement OTA orchestration on the Pi
- [ ] Expose local HTTP firmware endpoint
- [ ] Implement OTA MQTT topics per device

---

### Next Session — Start Here

**Step 1 — Confirm ESP01 is still online**
```bash
mosquitto_sub -h localhost -p 1883 -u mq -P mq -t "home/esp01/lobby/#" -v -W 5
```
Expected: `home/esp01/lobby/availability online` and `home/esp01/lobby/state OFF`

**Step 2 — Run main.py and do full end-to-end app test**
```bash
cd /home/pi/pi4_drive/Git_projects/RASPI4-MAIN
source /home/pi/myenv/bin/activate
python3 main.py
```
Then toggle the Living Room switch in the Android app and confirm:
1. Firebase SSE delivers command to Pi (`_on_firebase_light_cmd` fires)
2. Pi publishes MQTT command to `home/esp01/lobby/cmd/relay`
3. ESP01 relay clicks and publishes state back
4. Pi writes `lights/living_room/confirmed` to Firebase
5. Android app shows confirmed state

**Step 3 — Test reed switch**
- Open and close the door
- Confirm Telegram receives `🚪 Door OPENED` and `🔒 Door CLOSED` with timestamps

**Step 4 — Fix DHT11_ESP32 auth failure**
- Device `DHT11_ESP32-10B37A-V1` at `192.168.1.87` fails Mosquitto auth every 5 minutes
- Fix: `sudo mosquitto_passwd /etc/mosquitto/passwd <username>` or reflash with `mq / mq`
