# Raspberry Pi 5 — Project Reference

> Pi5 OS migration and setup reference — adapted from `OS_Migration/PROJECT_REFERENCE.md` (Pi4).
> All paths, usernames, hostnames updated for Pi5. Project code is shared in `RASPI5-MAIN`.

---

## Revision History

| Date | Changes |
|---|---|
| 2026-05-19 | Added `wifi-best-signal` service — connects to strongest saved WiFi on boot (multi-floor roaming). Script in `shell_scripts/`, service in `OS_Migration_PI5/services/`. Add to Manual Steps after OS reimage. |
| 2026-05-17 | Added Keepalived VRRP for dual-Pi hub IP failover. `keepalived` service added to Services table. `mybot.service` updated with `MQTT_HOST=192.168.1.100`. Added ESP32-LP-RLY to credentials table. |
| 2026-05-15 | OS_Migration_PI5 created from Pi4 migration infrastructure. All paths, user, hostname updated for Pi5 (pi5 / pi5 / 192.168.1.108). |

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
- [Before Reimaging — Backup](#part-1--before-reimaging-old-pi5)
- [Flash New OS](#step-b--flash-new-os)
- [Post-Install Setup](#part-2--after-reimaging-new-pi5)
- [Google Drive rclone Setup](#google-drive--rclone-setup)
- [Manual Steps After Setup](#manual-steps-after-setup)
- [Troubleshooting](#troubleshooting)

---

## Environment & Credentials

| Item | Value |
|---|---|
| Raspberry Pi 5 LAN IP | `192.168.1.108` |
| Hostname | `pi5` |
| Username | `pi5` |
| Hub IP (Keepalived VIP) | `192.168.1.100` — floats between Pi4 and Pi5 |
| Mosquitto broker (MQTT_HOST) | `192.168.1.100:1883` (hub IP) |
| Mosquitto credentials | `mq / mq` |
| ESP01-LL-RLY static IP | `192.168.1.85` |
| ESP01-RELAY (porch) static IP | `192.168.1.111` |
| ESP32-LP-RLY (LP porch) static IP | `192.168.1.89` |
| ESP32-RADAR static IP | `192.168.1.87` |
| Firebase RTDB URL | `https://home-security-app-555cf-default-rtdb.asia-southeast1.firebasedatabase.app` |
| RASPI5-MAIN repo | `https://github.com/bs220975/RASPI5-MAIN` — branch `main` |
| Firebase device key (Pi5) | `RASPI-5` (in `/devices/RASPI-5/`) |
| MQTT client ID | `raspi5-bridge` |

---

## Project Folder Structure

```
RASPI5-MAIN/
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
├── OS_Migration/                  ← Pi4 migration reference (do not change)
└── OS_Migration_PI5/              ← This folder — Pi5 migration
    ├── PROJECT_REFERENCE.md       ← This file
    ├── scripts/                   ← 1_backup, 2_post_install, 3_verify
    ├── services/                  ← mybot.service, mqttdatainflux.service
    └── configs/                   ← pip, aliases, bashrc for Pi5
```

---

## Key Paths

| Path | Purpose |
|---|---|
| `/home/pi5/myenv/` | Python virtual environment |
| `/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/` | Main project (GitHub) |
| `/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/logs/` | Service logs |
| `/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/shell_scripts/` | sync.sh, backup.sh |
| `/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/OS_Migration_PI5/services/` | Service file backups |
| `/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/alias_command_file/` | .bash_aliases backup |
| `/home/pi5/Non-Sync_backup_folder/` | Local backup destination (backup.sh) |
| `~/.config/rclone/rclone.conf` | Google Drive auth config (do NOT commit) |

---

## Services

| Service | Script | Autostart | Restart Policy |
|---|---|---|---|
| `mybot.service` | `RASPI5-MAIN/main.py` | YES | `always` — 5 crashes in 5 min → Pi reboots |
| `mqttdatainflux.service` | `RASPI5-MAIN/influx_aws_publish/influxdb2_aws_publish.py` | YES | `on-failure` — max 1 restart per 5 min |
| `keepalived` | VRRP hub IP failover — holds/releases `192.168.1.100` | YES | system default |
| `wifi-best-signal` | On boot, scans all saved WiFi and connects to strongest signal | YES | oneshot |
| `mybot2.service` | (secondary service) | NO | manual enable only if needed |
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
| `cdmain` | `cd` to RASPI5-MAIN project |
| `sync` | Interactive Google Drive ↔ Pi5 sync (rclone, gdrive:/pi5_drive) |
| `backup` | Local backup of pi5_drive with rsync + progress |
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

Serial `/dev/serial0` — LD2420 radar sensor (115200 baud)

---

## OS Migration (Fresh Reimage)

Target OS: Raspberry Pi OS 64-bit Bookworm — arm64.

### Overview

```
OLD PI5 (64-bit)             GOOGLE DRIVE                 NEW PI5 (64-bit)
─────────────────            ─────────────────            ─────────────────
Run backup script   ──────►  gdrive:/pi5_backups/    ──►  Post-install script
                             gdrive:/pi5_drive/            auto-restores all
                    ──────►                               ↓
                             github.com/bs220975/         gh repo clone
                             RASPI5-MAIN             ──►  RASPI5-MAIN
```

---

### Part 1 — Before Reimaging (Old Pi5)

#### Step A — Run Backup Script

```bash
bash /home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/OS_Migration_PI5/scripts/1_backup_before_reimage.sh
```

What it backs up:

| Item | Destination |
|---|---|
| apt package list | `gdrive:/pi5_backups/pre_reimage_DATE/apt/` |
| pip packages (myenv + root) | `gdrive:/pi5_backups/pre_reimage_DATE/pip/` |
| systemd service files | `gdrive:/pi5_backups/pre_reimage_DATE/services/` |
| Mosquitto config | `gdrive:/pi5_backups/pre_reimage_DATE/mosquitto/` |
| Crontabs (pi5 + root) | `gdrive:/pi5_backups/pre_reimage_DATE/crontab/` |
| SSH keys | `gdrive:/pi5_backups/pre_reimage_DATE/ssh/` |
| AWS certs | `gdrive:/pi5_backups/pre_reimage_DATE/aws_certs/` |
| .bashrc + .bash_aliases + rclone.conf | `gdrive:/pi5_backups/pre_reimage_DATE/configs/` |
| InfluxDB data | `gdrive:/pi5_backups/pre_reimage_DATE/influxdb/` |
| pi5_drive + code | `gdrive:/pi5_backups/pre_reimage_DATE/code/` |

> Size limit: 600 MB — uploads to Google Drive if under limit, otherwise stages to `/tmp/pi5_backup_staging/` for manual USB copy.

#### Step B — Flash New OS

1. Download **Raspberry Pi Imager** → [raspberrypi.com/software](https://www.raspberrypi.com/software/)
2. Select device: **Raspberry Pi 5**
3. Select OS: **Raspberry Pi OS (64-bit)** — Bookworm
4. Click gear icon ⚙ before flashing:
   - Hostname: `pi5`
   - Enable SSH ✓
   - Username: `pi5`, Password: *(your password)*
   - WiFi SSID + password ✓
5. Flash SD card, insert into Pi5, power on, wait ~60 seconds

---

### Part 2 — After Reimaging (New Pi5)

#### Step 1 — SSH In

```bash
ssh pi5@192.168.1.108
# or:
ssh pi5@pi5.local
```

#### Step 2 — Run Post-Install Script

```bash
wget -qO- https://raw.githubusercontent.com/bs220975/RASPI5-MAIN/main/OS_Migration_PI5/scripts/2_post_install_setup.sh | bash
```

What the script does (12 steps):

| Step | Action |
|---|---|
| 1 | Install Claude CLI (Node.js 20 LTS first) |
| 2 | `apt update` + install all packages (git, python3, rclone, mosquitto, cups…) + GitHub CLI |
| 3 | GitHub CLI (`gh auth login`) — opens browser to authenticate |
| 4 | rclone Google Drive setup — restores `rclone.conf` from backup |
| 5 | Creates `/home/pi5/pi5_drive/` + syncs from `gdrive:/pi5_backups/` and `gdrive:/pi5_drive/` |
| 6 | Clones `RASPI5-MAIN` from GitHub into `pi5_drive/Git_projects/` |
| 7 | Creates Python `myenv` + installs pip packages from `OS_Migration_PI5/configs/pip_myenv.txt` |
| 8 | Installs InfluxDB2 arm64 |
| 9 | Configures Mosquitto MQTT (restores config or creates fresh with `mq/mq`) |
| 10 | Installs + enables systemd services (autostart on boot) |
| 11 | Restores AWS certs (from Drive backup) |
| 12 | Restores `.bashrc` + `.bash_aliases` |

#### Step 3 — Verify

```bash
bash /home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/OS_Migration_PI5/scripts/3_verify_setup.sh
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
rclone ls gdrive:/pi5_drive/
```

#### Sync (interactive — uses sync.sh)

```bash
sync
# Prompts: 1) Drive → Pi   2) Pi → Drive
# Shows dry-run file list first, then asks to confirm
```

---

### Manual Steps After Setup

1. **WiFi best-signal service** — connect to strongest saved WiFi on boot (needed for multi-floor roaming):
   ```bash
   sudo cp /home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/shell_scripts/wifi-best-signal.sh /usr/local/bin/
   sudo chmod +x /usr/local/bin/wifi-best-signal.sh
   sudo cp /home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/OS_Migration_PI5/services/wifi-best-signal.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now wifi-best-signal.service
   ```
   Verify: `sudo journalctl -t wifi-best-signal -n 20`

2. **AWS Certs** — if not auto-restored:
   ```bash
   cp -r /media/pi5/USB/pre_reimage_*/aws_certs/ \
     /home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/aws_certs/
   ```

2. **InfluxDB data** — restore from backup:
   ```bash
   influx restore /media/pi5/USB/pre_reimage_*/influxdb/
   ```

3. **Crontab** — restore:
   ```bash
   crontab /media/pi5/USB/pre_reimage_*/crontab/crontab_pi5.txt
   ```

4. **pip_myenv.txt** — copy from Pi4 if not already in `OS_Migration_PI5/configs/`:
   ```bash
   cp OS_Migration/configs/pip_myenv.txt OS_Migration_PI5/configs/pip_myenv.txt
   ```

---

### Google Drive Folder Structure

```
gdrive:/
├── pi5_drive/                        ← Live working folder (rclone synced)
│   └── Git_projects/
│       └── RASPI5-MAIN/              ← All project files (code, scripts, logs, services)
│
└── pi5_backups/                      ← Pre-reimage snapshots
    └── pre_reimage_2026-05-15_XX-XX/
        ├── apt/ pip/ services/ mosquitto/
        ├── crontab/ ssh/ aws_certs/
        ├── configs/                  ← includes rclone.conf
        ├── influxdb/
        └── code/
```

> Pi4 Drive folders (`gdrive:/pi4_drive`, `gdrive:/pi4_backups`) remain unchanged — Pi4 and Pi5 use separate Drive folders.

---

### Troubleshooting

| Problem | Fix |
|---|---|
| `mqttdatainflux` crashes at boot | AWS certs missing — restore from `gdrive:/pi5_backups/`. If `StandardError` log dir missing, create `logs/` folder and restart |
| `mybot` not connecting | Check `config.py` Telegram token and chat ID |
| Aliases not working | Run `source ~/.bashrc` or re-login |
| Drive sync fails | Run `rclone config` to re-authenticate |
| InfluxDB not found | `which influx` — if missing, re-run Step 8 manually |
| 32-bit OS flashed by mistake | `getconf LONG_BIT` → should return `64` |
| Reed switch false alerts | See root PROJECT_REFERENCE.md — EMI issue, RC filter fix documented there |
| MQTT bridge reconnecting | Check which Pi holds hub IP (`ip addr show wlan0 \| grep 192.168.1.100`); check Mosquitto running on that Pi; check credentials `mq/mq` |
| Pi5 not receiving MQTT from ESPs | Check `MQTT_HOST=192.168.1.100` in `/etc/systemd/system/mybot.service`; run `grep MQTT_HOST /etc/systemd/system/mybot.service` |
| Pi not holding hub IP after reimage | Install and enable keepalived: `sudo apt install keepalived`, copy `OS_Migration_PI5/keepalived/keepalived.conf` to `/etc/keepalived/`, `sudo systemctl enable --now keepalived` |

---

## Notes vs Pi4 Setup

| Item | Pi4 value | Pi5 value |
|---|---|---|
| Username / hostname | `pi` | `pi5` |
| LAN IP | `192.168.1.122` | `192.168.1.108` |
| Home dir | `/home/pi/` | `/home/pi5/` |
| Drive folder | `pi4_drive` | `pi5_drive` |
| Google Drive sync | `gdrive:/pi4_drive` | `gdrive:/pi5_drive` |
| Backup dest | `gdrive:/pi4_backups` | `gdrive:/pi5_backups` |
| Firebase device key | `RASPI-4` | `RASPI-5` |
| MQTT client ID | `raspi4-bridge` | `raspi5-bridge` |
| Migration folder | `OS_Migration/` | `OS_Migration_PI5/` |
| InfluxDB org/bucket | `pi4org` / `pi4data` | `pi4org` / `pi4data` (kept same for data continuity) |

> **InfluxDB org and bucket names are kept as `pi4org`/`pi4data`** — these are logical names configured when InfluxDB was first set up. Changing them would require reinitializing InfluxDB and losing historical data. If restoring from a Pi4 InfluxDB backup, the existing names must match.

> **Android app Firebase path** — `firebase_logger.py` now writes to `/devices/RASPI-5/`. If your Android app reads from `/devices/RASPI-4/`, update the app or update `firebase_logger.py` to keep using `RASPI-4`. Both paths work simultaneously if needed.
