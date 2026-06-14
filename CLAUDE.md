# Claude Code — Pi5 Session Briefing

This file is auto-loaded at the start of every Claude Code session.
It gives Claude full context about this machine and project without the user needing to re-explain.

---

## Machine

| Item | Value |
|------|-------|
| Device | Raspberry Pi 5 |
| Hostname | `pi5` |
| User | `pi5` |
| IP | `192.168.1.108` |
| OS | Debian (aarch64), kernel 6.12.x |
| Python venv | `/home/pi5/myenv/` (Python 3.13, `include-system-site-packages = true`) |

---

## Main Project — RASPI5-MAIN

**Repo:** `/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/`
**GitHub:** `https://github.com/bs220975/RASPI5-MAIN`
**Purpose:** Home automation hub — integrates local GPIO sensors, ESP IoT devices, Firebase RTDB, Telegram bot, MQTT broker, InfluxDB, and a Raspberry Pi camera.

### Key files

| File | Role |
|------|------|
| `main.py` | Main controller (`RaspberryPiController`) |
| `mqtt_bridge.py` | Paho MQTT client — lobbby + porch relays + radar |
| `firebase_logger.py` | Firebase RTDB writes + SSE command streams |
| `sensors.py` | LD2420 radar, PIR, MMS, reed switch (GPIO 26) |
| `config.py` | All config (`TelegramConfig`, `MqttConfig`, `FirebaseConfig`, etc.) |
| `video_recorder.py` | picamera2 → H264 → ffmpeg MP4 |
| `telegram_handler.py` | Telegram bot send/receive |
| `influxdb_logger.py` | Motion events → InfluxDB 2.x |
| `esp_devices.py` | HTTP fallback for ESP01-LL-RLY heartbeat |
| `bot_commands.py` | Telegram command dispatch |

### Services (systemd)

| Service | Role | Status note |
|---------|------|-------------|
| `mybot.service` | Main bot (runs `main.py`) | May be inactive if debugging manually |
| `mqttdatainflux.service` | MQTT → InfluxDB bridge | |
| `mosquitto` | Local MQTT broker `localhost:1883` | credentials: `mq / mq` |
| `influxdb` | InfluxDB 2.x at `http://[::1]:8086` | org: `pi4org`, bucket: `pi4data` |

Common service commands:
```bash
sudo systemctl restart mybot.service
journalctl -u mybot.service -f        # live log
servicemybot                           # alias for above
statusmqtt                             # alias for mosquitto status
```

---

## Hardware — GPIO Pins (BCM)

| GPIO | Device | Direction | Notes |
|------|--------|-----------|-------|
| 25 | PIR motion sensor | Input | pull_up=False |
| 27 | MMS microwave sensor | Input | pull_up=False |
| 18 | Status LED | Output | mirrors motion |
| 26 | Reed switch (door) | Input | PUD_UP — HIGH=open, LOW=closed |

Serial `/dev/serial0` — LD2420 radar (115200 baud)

**Power supply check:**
```bash
vcgencmd get_throttled        # 0x0 = healthy, any other = under-voltage
vcgencmd measure_volts core   # normal ~0.866V
```
GPIO 5V rail: pin 2 or 4. GPIO 3.3V: pin 1 or 17. GND: pin 6, 9, 14, etc.

---

## ESP IoT Devices

| Device | IP | MQTT prefix | Role |
|--------|----|-------------|------|
| ESP01-LL-RLY | 192.168.1.85 | `home/esp01/lobby/` | Lobby relay (light) |
| ESP01-RELAY | 192.168.1.111 | `home/esp01/porch/` | Porch relay (light) |
| ESP32-RADAR | 192.168.1.87 | `home/esp32/radar2/` | Radar + DHT11 + direct cloud alerts |

MQTT commands: `ON` / `OFF` to `…/cmd/relay`
MQTT state: `…/state` (retained)

---

## Firebase RTDB

URL: `https://home-security-app-555cf-default-rtdb.asia-southeast1.firebasedatabase.app`

Key paths written by Pi:
- `/devices/RASPI-4/` — Pi heartbeat (cpuTemp, uptime, motionDetected, recording)
- `/devices/ESP01-LL-RLY/` — lobby relay state
- `/devices/esp01_relay/` — porch relay state
- `/lights/living_room/confirmed` — after lobby MQTT state
- `/lights/lobby/confirmed` — after porch MQTT state

SSE streams read by Pi:
- `/lights/living_room/state` → lobby relay ON/OFF
- `/lights/lobby/state` → porch relay ON/OFF

Firebase key: `RASPI-5` (Pi4 used `RASPI-4` — note: heartbeat still PATCHes `/devices/RASPI-4/` path in current code)

---

## Known Issues / Ongoing Work

| Issue | Status | Notes |
|-------|--------|-------|
| Reed switch false door alerts | Software fix applied | Debounce 2.0s, cooldown 5s in `sensors.py`; hardware RC filter (10kΩ + 100nF on GPIO 26) recommended but not yet soldered |
| LD2420 EMI on GPIO 26 | Root cause identified | Radar ~10cm from Pi couples RF into reed switch wire; move radar ≥30cm or add RC filter |
| `mybot.service` / `mqttdatainflux.service` | Active | Running normally |

---

## Python Venv Notes

**Path:** `/home/pi5/myenv/`
**Config:** `/home/pi5/myenv/pyvenv.cfg`

`picamera2` is installed **system-wide** (via apt), not inside the venv. The venv must have `include-system-site-packages = true` in `pyvenv.cfg` to access it — without this, `/record_video` silently fails with `PiCamera2 not available`.

**If the venv is ever recreated, always use:**
```bash
python3 -m venv --system-site-packages /home/pi5/myenv
```

This was the root cause of bot video recording not working (fixed Jun 2026).

---

## Other Projects in `/home/pi5/Git_projects/`

ESP32-CAM, ESP32-DHT11, ESP32-ENERGY, ESP32-LORA, ESP32-RADAR, ESP32-UNIFIED, ESP32-S3-XIAO-CAMERA, ESP8266-PORCH, ESP01-RELAY, ESP01-LL-RLY, HOMESECURITY-APP, ICECMGT_APP, MYELECTRONICS-APP, STRUCTURALCAL-APP, raspi-setup, ace_design_projects

---

## Quick Reference Commands

```bash
# MQTT — listen to all topics
mosquitto_sub -h localhost -p 1883 -u mq -P mq -t "home/#" -v

# Manually command relays
mosquitto_pub -h localhost -p 1883 -u mq -P mq -t "home/esp01/lobby/cmd/relay" -m "ON"
mosquitto_pub -h localhost -p 1883 -u mq -P mq -t "home/esp01/porch/cmd/relay" -m "ON"

# Run main bot manually (debug mode)
cd /home/pi5/Git_projects/RASPI5-MAIN
source /home/pi5/myenv/bin/activate
python3 main.py

# GPIO reed switch live monitor
watch -n 0.5 "raspi-gpio get 26"

# Check false door alerts in logs
journalctl -u mybot.service --since "30 min ago" | grep -i door

# Disk usage
df -h /

# Camera videos
ls -lh /home/pi5/raspi_camera_videos/
```

---

## Pi5 vs Pi4 Differences (for context)

| Item | Pi5 (this machine) | Pi4 (old) |
|------|--------------------|-----------|
| Username | `pi5` | `pi` |
| IP | 192.168.1.108 | 192.168.1.122 |
| Drive folder | `pi5_drive` / `gdrive:/pi5_drive` | `pi4_drive` |
| Firebase key | `RASPI-5` | `RASPI-4` |
| MQTT client ID | `raspi5-bridge` | `raspi4-bridge` |
| InfluxDB org/bucket | `pi4org` / `pi4data` (kept for data continuity) | same |
| Migration folder | `OS_Migration_PI5/` | `OS_Migration/` |
