# RASPI4-MAIN — Project Reference

Raspberry Pi 4 home automation bridge. Runs as a systemd service (`mybot.service`)
and coordinates local sensors, ESP IoT devices, Firebase RTDB, Telegram, and InfluxDB.
The Pi is the integration point for relay control and logging. ESP32-RADAR also speaks
directly to AWS IoT / Firebase / Telegram for security alerts that must survive a Pi outage.

> For OS setup, reimaging, service files, aliases, and Google Drive backup see
> [`OS_Migration/PROJECT_REFERENCE.md`](OS_Migration/PROJECT_REFERENCE.md).

---

## Contents

- [Change Log](#change-log)
- [Hardware — GPIO Pins](#hardware--gpio-pins)
- [Architecture](#architecture)
  - [ESP32-RADAR: direct cloud paths (Pi-independent)](#esp32-radar--direct-cloud-paths-pi-independent)
  - [Pi / local MQTT paths (Pi-dependent)](#pi--local-mqtt-paths-pi-dependent)
  - [What survives a Pi outage](#what-survives-a-pi-outage)
- [MQTT Topics](#mqtt-topics)
  - [Lobby relay — ESP01-LL-RLY](#lobby-relay--esp01-ll-rly-at-192168185)
  - [Porch relay — ESP01-RELAY](#porch-relay--esp01-relay-at-1921681111)
  - [Radar sensor — ESP32-RADAR](#radar-sensor--esp32-radar-at-192168187)
  - [DHT11 sensor](#dht11-sensor-on-esp32-radar)
- [Firebase RTDB Paths](#firebase-rtdb-paths)
  - [Written by Pi](#written-by-pi)
  - [Read by Pi (SSE streams)](#read-by-pi-sse-streams)
  - [Written directly by ESP32-RADAR](#written-directly-by-esp32-radar-pi-down-resilience)
- [Module Reference](#module-reference)
  - [main.py](#mainpy--main-controller-raspberrypicontroller)
  - [mqtt_bridge.py](#mqtt_bridgepy--mqttbridge)
  - [firebase_logger.py](#firebase_loggerpy--firebaselogger)
  - [sensors.py](#sensorspy--sensormanager--gpiomanager--radarsensor)
  - [config.py](#configpy--appconfig-and-sub-configs)
  - [video_recorder.py](#video_recorderpy--videorecorder)
  - [esp_devices.py](#esp_devicespy--espdevicemanager)
  - [telegram_handler.py](#telegram_handlerpy--telegramhandler)
  - [influxdb_logger.py](#influxdb_loggerpy--influxdblogger)
- [Automation Logic](#automation-logic)
  - [ESP32-RADAR → App siren](#esp32-radar--app-siren-direct-2026-05-14)
  - [Pi local radar → lobby light](#pi-local-radar--lobby-light-existing)
  - [ESP32-RADAR → porch light](#esp32-radar--porch-light-new--2026-05-14)
  - [App-commanded lobby light](#app-commanded-lobby-light)
  - [App-commanded porch light](#app-commanded-porch-light)
- [Running the Service](#running-the-service)
- [Verify MQTT Devices](#verify-mqtt-devices)
- [Troubleshooting](#troubleshooting)

---

## Change Log

| Date | Change |
|---|---|
| 2026-05-15 | Reed switch false door alerts: raised debounce 0.3 s → 2.0 s, added 5 s MIN_INTERVAL cooldown; root cause is LD2420 EMI on GPIO 26 wire; hardware RC filter recommended (see Troubleshooting) |
| 2026-05-14 | Created PROJECT_REFERENCE.md |
| 2026-05-14 | MQTT Option B+C: added porch relay (ESP01-RELAY) + radar motion (ESP32-RADAR) to `mqtt_bridge.py`; night-time relay automation + 5-min off timer in `main.py`; Firebase SSE stream for `lights/lobby`; `push_porch_relay_status()` in `firebase_logger.py`; multi-stream `start_command_stream()` |
| 2026-05-14 | Video quality: CRF 26 re-encode, bitrate 1 Mbps, motion timeout 10 s, max duration 120 s |
| 2026-05-14 | Reed switch door sensor: GPIO 26, polling thread, 300 ms debounce, Telegram alerts |
| 2026-05-14 | Fix Firebase path `lobby` → `lobby` in Pi `main.py` (SSE stream + confirmed write) and ESP32-RADAR `RadarMotion.cpp` (Pi-down RTDB fallback) — lobby light from app was silently failing |
| 2026-05-14 | Restore `AWSService` in ESP32-RADAR `main.cpp`: motion alert siren path is direct ESP32 → AWS IoT → Lambda → FCM (survives Pi outage); local MQTT motion publish kept alongside for porch relay via Pi |
| 2026-05-13 | Phase 1: Firebase SSE stream replaces 1 s REST poll for living room light commands |
| 2026-05-13 | Phase 2: MQTT bridge (lobby relay ESP01-LL-RLY) verified live |

---

## Hardware — GPIO Pins

BCM numbering. All defined in `config.py → GPIOConfig`.

| Pin | Device | Direction | Notes |
|---|---|---|---|
| GPIO 25 | PIR motion sensor | Input | `pull_up=False` |
| GPIO 27 | MMS microwave sensor | Input | `pull_up=False` |
| GPIO 18 | Status LED | Output | Mirrors motion state |
| GPIO 26 | Reed switch (door) | Input | `PUD_UP` — HIGH = open, LOW = closed |

Serial `/dev/serial0` — LD2420 radar sensor (115200 baud, configured in `RadarConfig`)

---

## Architecture

### ESP32-RADAR — direct cloud paths (Pi-independent)

These paths fire regardless of Pi state. Security alerts must survive a Pi outage.

```
Radar sensor (GPIO19) triggers HIGH
    │
    ├── AWSService → AWS IoT topic: RADAR2_MOTION
    │                   └── Lambda → FCM topic: aws_radar2
    │                                   └── App siren 🔔
    │
    ├── TelegramService → Telegram API (direct HTTPS)
    │                       └── Motion alert to chat
    │
    ├── Firebase RTDB (Pi-down resilience only)
    │       └── HTTPS PATCH lights/lobby → {state, confirmed}
    │           (keeps app bulb in sync when Pi is unreachable)
    │
    └── AWS IoT Shadow → radars/{radar2} heartbeat (every 2 min)
                            └── Flutter app radar status
```

### Pi / local MQTT paths (Pi-dependent)

```
Android App
    │
    ▼  Firebase RTDB
    ├── lights/living_room/state  ──SSE──►  Pi: _on_firebase_light_cmd
    │                                            └──► MQTT → home/esp01/lobby/cmd/relay
    │                                                      → ESP01-LL-RLY (lobby light)
    │
    └── lights/lobby/state  ───────SSE──►  Pi: _on_firebase_porch_light_cmd
                                               └──► MQTT → home/esp01/porch/cmd/relay
                                                         → ESP01-RELAY (porch light)

ESP32-RADAR (motion sensor) — also publishes via local MQTT for relay control:
    └── MQTT home/esp32/radar2/motion  ──►  Pi: _on_radar_motion
                                               ├── night (18–06)? → send_porch_relay(ON)
                                               └── motion OFF?    → 5-min timer → relay OFF

ESP01-LL-RLY (lobby relay)
    └── MQTT home/esp01/lobby/state  ──►  Pi: _on_lobby_mqtt_state
                                              └── Firebase PATCH /devices/ESP01-LL-RLY/
                                                  lights/living_room/confirmed

ESP01-RELAY (porch relay)
    └── MQTT home/esp01/porch/state  ──►  Pi: _on_porch_mqtt_state
                                              └── Firebase PATCH /devices/esp01_relay/
                                                  lights/lobby/confirmed

Pi local sensors (GPIO)
    ├── LD2420 radar → _process_motion → _trigger_light_control (lobby light, night only)
    │                                  → video recording → Telegram send_video
    │                                  → InfluxDB log
    │                                  → Firebase push_pi_status
    └── Reed switch (GPIO 26) → _on_door_open / _on_door_close → Telegram alert

Pi → Firebase heartbeat (every 60 s)
    └── PATCH /devices/RASPI-4/ {cpuTemp, uptime, motionDetected, recording}
```

### What survives a Pi outage

| Feature | Survives Pi down? |
|---|---|
| App siren on motion | ✅ ESP32 → AWS IoT → Lambda → FCM |
| Telegram motion alerts | ✅ ESP32 → Telegram API direct |
| AWS shadow heartbeat | ✅ ESP32 → AWS IoT |
| App bulb state (lobby) | ✅ ESP32 → Firebase RTDB direct |
| Porch relay (motion triggered) | ❌ Pi required (MQTT path) |
| App lobby/porch switch | ❌ Pi required (Firebase SSE → MQTT) |
| DHT11 temperature logging | ❌ Pi required |

---

## MQTT Topics

### Lobby relay — ESP01-LL-RLY at 192.168.1.85

| Topic | Direction | QoS | Retained | Payload |
|---|---|---|---|---|
| `home/esp01/lobby/cmd/relay` | Pi → device | 1 | No | `ON` / `OFF` |
| `home/esp01/lobby/state` | Device → Pi | 1 | Yes | `ON` / `OFF` |
| `home/esp01/lobby/availability` | Device → Pi | 1 | Yes | `online` / `offline` |

### Porch relay — ESP01-RELAY at 192.168.1.111

| Topic | Direction | QoS | Retained | Payload |
|---|---|---|---|---|
| `home/esp01/porch/cmd/relay` | Pi → device | 1 | No | `ON` / `OFF` |
| `home/esp01/porch/state` | Device → Pi | 1 | Yes | `ON` / `OFF` |
| `home/esp01/porch/availability` | Device → Pi | 1 | Yes | `online` / `offline` |

### Radar sensor — ESP32-RADAR at 192.168.1.87

| Topic | Direction | QoS | Retained | Payload |
|---|---|---|---|---|
| `home/esp32/radar2/motion` | Device → Pi | 1 | Yes | `ON` / `OFF` |
| `home/esp32/radar2/availability` | Device → Pi | 1 | Yes | `online` / `offline` |

### DHT11 sensor (on ESP32-RADAR)

| Topic | Direction | Payload |
|---|---|---|
| `DHT11` | Device → Pi | JSON `{temp, humidity}` |

**Broker:** Mosquitto on Pi — `localhost:1883`, credentials `mq / mq`

---

## Firebase RTDB Paths

Database: `https://home-security-app-555cf-default-rtdb.asia-southeast1.firebasedatabase.app`

### Written by Pi

| Path | Trigger | Fields |
|---|---|---|
| `/devices/RASPI-4/` | Every 60 s heartbeat | `lastSeen`, `reachable`, `cpuTemp`, `uptime`, `motionDetected`, `recording` |
| `/devices/ESP01-LL-RLY/` | MQTT lobby state + relay heartbeat poll | `lastSeen`, `reachable`, `relayState` |
| `/devices/esp01_relay/` | MQTT porch state | `lastSeen`, `reachable`, `relayState` |
| `/lights/live/` | Pi radar motion changes | `motionDetected`, `lastUpdate` |
| `/lights/living_room/confirmed` | After lobby relay MQTT state arrives | `bool` |
| `/lights/lobby/confirmed` | After porch relay MQTT state arrives | `bool` |

### Read by Pi (SSE streams)

| Path | Callback | Action |
|---|---|---|
| `/lights/living_room/state` | `_on_firebase_light_cmd` | → MQTT lobby relay ON/OFF |
| `/lights/lobby/state` | `_on_firebase_porch_light_cmd` | → MQTT porch relay ON/OFF |

### Written directly by ESP32-RADAR (Pi-down resilience)

| Path | Fields |
|---|---|
| `/lights/lobby/` | `state`, `confirmed` (direct HTTPS PATCH from ESP32 firmware) |

---

## Module Reference

### `main.py` — Main controller (`RaspberryPiController`)

**Motion / recording loop** (200 ms tick):
- `_process_motion(detected)` — video recording, InfluxDB, Telegram, Firebase push
- `_trigger_light_control()` — Pi local radar → lobby relay ON (night: 18:00–08:00), 30 s cooldown
- `_check_stop_recording()` — stops when `motion_timeout` seconds (10 s) with no motion, or max 120 s

**MQTT callbacks:**
- `_on_lobby_mqtt_state(payload)` — updates `/devices/ESP01-LL-RLY/` + `living_room/confirmed`
- `_on_porch_mqtt_state(payload)` — updates `/devices/esp01_relay/` + `lobby/confirmed`
- `_on_radar_motion(payload)` — night check, porch relay ON/OFF, 5-min off timer

**Firebase SSE callbacks:**
- `_on_firebase_light_cmd(cmd)` — debounced 400 ms → `_execute_light_cmd` → MQTT lobby relay
- `_on_firebase_porch_light_cmd(cmd)` — debounced 400 ms → `_execute_porch_cmd` → MQTT porch relay

**Door callbacks:**
- `_on_door_open()` / `_on_door_close()` — Telegram alert with timestamp

**Heartbeats:**
- `_poll_relay_heartbeat()` — every 120 s, GET ESP01-LL-RLY `/status` → Firebase
- `_push_firebase_status()` — every 60 s → `/devices/RASPI-4/`

---

### `mqtt_bridge.py` — `MqttBridge`

Single paho MQTT client session against local Mosquitto.

**Publishes:**
- `send_lobby_relay(state)` → `home/esp01/lobby/cmd/relay`
- `send_porch_relay(state)` → `home/esp01/porch/cmd/relay`

**Subscribes** (registered in `_on_connect`):
- All 6 state/availability topics for lobby relay, porch relay, and radar sensor

**Callbacks injected at construction:**
- `on_lobby_state`, `on_lobby_availability`
- `on_porch_state`, `on_porch_availability`
- `on_radar_motion`, `on_radar_availability`

Auto-reconnect via paho `reconnect_delay_set(5, 60)`.

---

### `firebase_logger.py` — `FirebaseLogger`

Pure HTTPS REST to Firebase RTDB (no auth — database rules allow public write).

**Write methods:**
- `push_pi_status(motion, recording)` — RASPI-4 heartbeat + `lights/live/`
- `push_lobby_relay_status(reachable, relay_on)` — `/devices/ESP01-LL-RLY/`
- `push_porch_relay_status(reachable, relay_on)` — `/devices/esp01_relay/`
- `set_light_confirmed(light_id, confirmed)` — `lights/{light_id}/confirmed`
- `mark_offline()` — sets `RASPI-4/reachable = false` on shutdown

**SSE streams (multiple concurrent, keyed by `light_id`):**
- `start_command_stream(light_id, callback)` — streams `lights/{light_id}/state`
- Currently active: `living_room` and `lobby`
- `stop_command_stream()` — stops all streams

---

### `sensors.py` — `SensorManager` / `GPIOManager` / `RadarSensor`

- **LD2420 radar** (`/dev/serial0`) — `RadarSensor.check_motion()` → `bool`
- **PIR** (GPIO 25) — via `gpiozero.MotionSensor`
- **MMS** (GPIO 27) — via `gpiozero.DigitalInputDevice`
- **Reed switch** (GPIO 26) — polling thread (50 ms), 2.0 s software debounce, 5 s min-interval cooldown
  - `set_reed_callbacks(on_open, on_close)` — called from `main.py`
  - Uses `RPi.GPIO` (not gpiozero — avoids edge-detect conflict)
  - Debounce raised from 0.3 s to 2.0 s to reject LD2420 EMI (see Troubleshooting)

---

### `config.py` — `AppConfig` and sub-configs

| Class | Key settings |
|---|---|
| `TelegramConfig` | `bot_token`, `chat_id` |
| `MqttConfig` | `host=localhost`, `port=1883`, `username=mq`, `password=mq`, `client_id=raspi4-bridge` |
| `FirebaseConfig` | `database_url`, `heartbeat_interval=60` |
| `GPIOConfig` | `mms=27`, `pir=25`, `led=18`, `reed_switch=26` |
| `VideoConfig` | `bitrate=1_000_000`, `max_duration=120`, `motion_timeout=10`, `min_duration=10` |
| `RadarConfig` | `port=/dev/serial0`, `baud_rate=115200` |
| `AppConfig` | `light_cooldown=30`, `motion_message_cooldown=120`, `relay_heartbeat_interval=120` |

Override any value with environment variables (see `config.py` docstring).

---

### `video_recorder.py` — `VideoRecorder`

- Records H264 via `picamera2`, converts to MP4 with `ffmpeg`
- FFmpeg command: `-c:v libx264 -crf 26 -preset fast` (quality re-encode, ~1 Mbps output)
- Min duration: 10 s (shorter clips discarded)
- Max duration: 120 s
- Stops when `motion_timeout` (10 s) of no motion passes
- Manual recordings (started by `/record` bot command) ignore motion-stop checks
- Disk cleanup: removes all videos if disk > 75% full

---

### `esp_devices.py` — `ESPDeviceManager`

HTTP fallback control for ESP devices that are not yet MQTT-native, and for the lobby
relay heartbeat poll.

| Method | Target | Notes |
|---|---|---|
| `get_relay_state()` | `192.168.1.85/status` | Used in heartbeat poll |
| `lobby_light_on/off()` | `192.168.1.85/lighton` or `/lightoff` | HTTP fallback if MQTT bridge is down |
| `send_to_lobby(endpoint)` | `192.168.1.85/{endpoint}` | Generic ESP01-LL-RLY call |

ESP01-RELAY (192.168.1.111) is **not** called via `esp_devices.py` — it is controlled
exclusively via MQTT, with its own HTTP fallback to ESP32-RADAR handled on-device.

---

### `telegram_handler.py` — `TelegramHandler`

- Wraps the `telepot` library
- `send_text(msg)` — sends to configured `chat_id`
- `send_video(path)` — sends MP4 file
- Message loop started with `start_message_loop(handler)` — dispatches to `bot_commands.py`

---

### `influxdb_logger.py` — `InfluxDBLogger`

- Writes motion state events to InfluxDB 2.x at `http://[::1]:8086`
- Bucket `pi4data`, org `pi4org`
- Used for historical motion graphs

---

## Automation Logic

### ESP32-RADAR → App siren (direct, 2026-05-14)
- Trigger: radar sensor GPIO19 HIGH → EventBus `radar_motion=1`
- Action: `AWSService.handleRadar()` publishes to AWS IoT topic `RADAR2_MOTION`
- AWS IoT Rule → Lambda → FCM topic `aws_radar2` with sound `siren`
- Cooldown: 20 seconds (enforced in Lambda in-memory)
- **No Pi involvement — fires even during Pi outage**

### Pi local radar → lobby light (existing)
- Trigger: LD2420 radar motion detected
- Condition: 18:00 ≤ hour < 08:00, cooldown 30 s since last activation
- Action: `send_lobby_relay(True)` via MQTT; HTTP fallback via `esp_devices`
- No auto-off — relay auto-off is on ESP01-LL-RLY firmware (3 min)

### ESP32-RADAR → porch light (new — 2026-05-14)
- Trigger: `home/esp32/radar2/motion` = ON
- Condition: 18:00 ≤ hour < 06:00 (IST)
- Action: `send_porch_relay(True)` via MQTT
- On motion = OFF: 5-minute `threading.Timer` → `send_porch_relay(False)`
- Timer cancelled if another ON arrives before it fires
- Hardware safety net: ESP01-RELAY's 3-min auto-off always active

### App-commanded lobby light
- Firebase SSE on `lights/living_room/state` → `_on_firebase_light_cmd`
- 400 ms debounce (suppresses rapid Firebase reconnect replays)
- Dedup: skipped if same state as last executed command
- MQTT primary → HTTP fallback if MQTT bridge down

### App-commanded porch light
- Firebase SSE on `lights/lobby/state` → `_on_firebase_porch_light_cmd`
- Same debounce + dedup pattern
- MQTT only (no HTTP fallback from Pi — ESP01-RELAY handles its own HTTP fallback)

---

## Running the Service

```bash
# Start / restart
sudo systemctl restart mybot.service

# Live log
journalctl -u mybot.service -f
# or:
servicemybot   # alias

# Run manually (debug)
cd /home/pi/pi4_drive/Git_projects/RASPI4-MAIN
source /home/pi/myenv/bin/activate
python3 main.py
```

---

## Verify MQTT Devices

```bash
# Subscribe to all managed topics
mosquitto_sub -h localhost -p 1883 -u mq -P mq -t "home/#" -v

# Check lobby relay
mosquitto_sub -h localhost -p 1883 -u mq -P mq -t "home/esp01/lobby/#" -v -W 5

# Check porch relay
mosquitto_sub -h localhost -p 1883 -u mq -P mq -t "home/esp01/porch/#" -v -W 5

# Check radar motion
mosquitto_sub -h localhost -p 1883 -u mq -P mq -t "home/esp32/radar2/#" -v -W 5

# Manually command porch relay
mosquitto_pub -h localhost -p 1883 -u mq -P mq -t "home/esp01/porch/cmd/relay" -m "ON"
mosquitto_pub -h localhost -p 1883 -u mq -P mq -t "home/esp01/lobby/cmd/relay" -m "ON"
```

---

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| Lobby light not responding to app | Check Firebase SSE stream alive (log: `Firebase: SSE stream started for lights/living_room/state`); check MQTT bridge connected |
| Porch light not turning on at night | Check radar MQTT arriving (`home/esp32/radar2/motion`); check night hours 18–06; check `_porch_light_on` state |
| Motion video not sent to Telegram | Check camera initialized (log: `Camera initialized successfully`); check disk space |
| Reed switch not firing | Check GPIO 26 wiring — one leg to GPIO 26, other to GND. Check log for "Reed switch initialized" |
| False Door OPENED / CLOSED Telegram alerts (no activity) | **Cause:** LD2420 24 GHz radar EMI couples into GPIO 26 wire. **Software fix (applied):** debounce raised to 2.0 s, 5 s cooldown between events (`sensors.py _reed_poll_loop`). Suppressed events log `WARNING Reed: state change suppressed`. **Permanent hardware fix:** add 10 kΩ series resistor between reed switch and GPIO 26, plus 100 nF capacitor from GPIO 26 to GND — this RC low-pass filter (~160 Hz cutoff) blocks RF before it reaches the pin. Also: move LD2420 ≥ 30 cm from the Pi, or add a ferrite bead on the reed switch wire. |
| MQTT bridge reconnecting constantly | Check Mosquitto running (`statusmqtt`); check credentials `mq/mq`; check `localhost:1883` |
| `_on_porch_mqtt_state` not firing | Check ESP01-RELAY online (`home/esp01/porch/availability`); check firmware has MQTT |
| Porch light stays on after dawn | 5-min off timer only fires on `motion=OFF` from radar; check ESP32-RADAR is publishing MQTT |
| Firebase writes failing | Check internet connectivity; Firebase RTDB rules allow public write on `devices/`, `lights/` |
| `mybot.service` crash-looping | Check `logs/error_log.txt`; check GPIO conflicts; check sensor hardware connected |
| `start_command_stream` logs two streams | Expected — `living_room` and `lobby` both start on init |
