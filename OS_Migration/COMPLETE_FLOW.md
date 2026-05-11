# Pi4 Complete OS Migration Flow
## 32-bit (Raspbian armhf) → 64-bit (Raspberry Pi OS arm64)

---

## Overview

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

## PART 1 — Before Reimaging (Old Pi)

### Step A — Run Backup Script
```bash
bash /home/pi/pi4_drive/OS_Migration/scripts/1_backup_before_reimage.sh
```

**What it backs up:**

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
| pi4_drive + python_raspi code | `gdrive:/pi4_backups/pre_reimage_DATE/code/` |

> Size limit: **600 MB** — if under, uploads directly to Google Drive.
> If Drive unavailable, stages to `/tmp/pi4_backup_staging/` for manual USB copy.

### Step B — Flash New OS

1. Download **Raspberry Pi Imager** on PC/Mac → [raspberrypi.com/software](https://www.raspberrypi.com/software/)
2. Select device: **Raspberry Pi 4**
3. Select OS: **Raspberry Pi OS (64-bit)** — Bookworm
4. Click **gear icon ⚙** before flashing and configure:
   - Hostname: `pi` (or your preferred)
   - Enable SSH ✓
   - Username: `pi`
   - Password: *(your password)*
   - WiFi SSID + password ✓
5. Flash the SD card
6. Insert SD card into Pi4, power on, wait ~60 seconds

---

## PART 2 — After Reimaging (New Pi)

### Step 1 — SSH into New Pi
```bash
ssh pi@<pi-ip-address>
# or if hostname resolves:
ssh pi@pi.local
```

### Step 2 — Download & Run Post-Install Script
```bash
wget -qO- https://raw.githubusercontent.com/bs220975/RASPI4-MAIN/main/OS_Migration/scripts/2_post_install_setup.sh | bash
```

**What the script does automatically (11 steps):**

| Step | Action |
|---|---|
| 1 | `apt update` + install all packages (git, python3, rclone, mosquitto, cups…) + **Node.js 20 LTS** |
| 2 | GitHub CLI (`gh auth login`) — opens browser to authenticate |
| 3 | rclone Google Drive setup — restores `rclone.conf` from backup automatically |
| 4 | **Creates `/home/pi/pi4_drive/`** + syncs from `gdrive:/pi4_backups/` and `gdrive:/pi4_drive/` |
| 5 | Clones `RASPI4-MAIN` from GitHub into `pi4_drive/Git_projects/` |
| 6 | Creates Python `myenv` + installs all pip packages from `pip_myenv.txt` |
| 7 | Installs InfluxDB2 arm64 (uses tarball from Drive if found, else downloads) |
| 8 | Configures Mosquitto MQTT (restores config or creates fresh) |
| 9 | Installs + **enables** systemd services (autostart on boot) |
| 10 | Restores AWS certs (from Drive backup → USB fallback) |
| 11 | Restores `.bashrc` + `.bash_aliases` (all aliases active on next login) |
| 12 | **Installs Claude CLI** (`npm install -g @anthropic-ai/claude-code`) |

### Step 3 — Verify Everything Works
```bash
bash /home/pi/pi4_drive/Git_projects/RASPI4-MAIN/OS_Migration/scripts/3_verify_setup.sh
```

Expected output:
```
--- System ---
  [PASS] 64-bit OS confirmed

--- Services (enabled + autostart) ---
  [PASS] SSH enabled & running
  [PASS] Mosquitto enabled
  [PASS] Mosquitto running
  [PASS] InfluxDB enabled
  [PASS] InfluxDB running
  [PASS] cron enabled
  [PASS] mybot enabled (autostart)
  [PASS] mybot running
  [PASS] mqttdatainflux enabled
  [PASS] mqttdatainflux running
  [PASS] Error_and_Logs folder exists
  [PASS] mybot script exists
  [PASS] influx script exists

--- Python ---
  [PASS] python3 exists
  [PASS] myenv exists
  [PASS] paho-mqtt installed
  [PASS] influxdb_client installed
  [PASS] telepot installed
  ...
```

### Step 4 — Start Services
```bash
sudo systemctl start mybot.service
sudo systemctl start mqttdatainflux.service
```

### Step 5 — Re-login for Aliases
```bash
source ~/.bashrc
# Now all aliases work:
# statusmybot, statusmqtt, myenv, cdmain, sync, backup ...
```

---

## Service Autostart Summary

| Service | Autostart | Restart Policy |
|---|---|---|
| `mybot.service` | **YES** (enabled) | `always` — crashes 5x in 5min → Pi reboots |
| `mqttdatainflux.service` | **YES** (enabled) | `on-failure` — max 1 restart per 5min |
| `mybot2.service` | NO (installed only) | manual enable if needed |
| `mosquitto` | **YES** | system default |
| `influxdb` | **YES** | system default |
| `ssh` | **YES** | system default |
| `cron` | **YES** | system default |

---

## Aliases Available After Restore

| Alias | Command |
|---|---|
| `myenv` | Activate Python virtual environment |
| `cdmain` | `cd` to RASPI4-MAIN project |
| `sync` | Run Google Drive sync script |
| `backup` | Run local backup script |
| `statusmybot` | `systemctl status mybot.service` |
| `startmybot` | Start mybot service |
| `restartmybot` | Restart mybot service |
| `servicemybot` | Live logs for mybot |
| `statusmqtt` | `systemctl status mqttdatainflux.service` |
| `startmqtt` | Start mqttdatainflux service |
| `servicemqtt` | Live logs for mqttdatainflux |
| `copyalias` | Save updated aliases to pi4_drive |

---

## Key Paths (Post-Install)

| Path | Purpose |
|---|---|
| `/home/pi/myenv/` | Python virtual environment |
| `/home/pi/pi4_drive/` | Main working folder (synced to Google Drive) |
| `/home/pi/pi4_drive/Git_projects/RASPI4-MAIN/` | Main Pi4 project (GitHub) |
| `/home/pi/pi4_drive/pi4_python_projects/RASPI4-MAIN/` | Symlink → Git_projects/RASPI4-MAIN |
| `/home/pi/pi4_drive/Service_files/` | Service file backups |
| `/home/pi/pi4_drive/Error_and_Logs/` | Service logs |
| `/home/pi/pi4_drive/shell_scripts/` | sync.sh, backup.sh etc. |
| `~/.config/rclone/rclone.conf` | Google Drive auth config |

---

## Google Drive Folder Structure

```
gdrive:/
├── pi4_drive/                        ← Live working folder (rclone synced)
│   ├── OS_Migration/                 ← All migration scripts
│   │   ├── scripts/
│   │   │   ├── 1_backup_before_reimage.sh
│   │   │   ├── 2_post_install_setup.sh
│   │   │   └── 3_verify_setup.sh
│   │   ├── services/
│   │   │   ├── mybot.service
│   │   │   ├── mybot2.service
│   │   │   └── mqttdatainflux.service
│   │   └── configs/
│   │       ├── pip_myenv.txt
│   │       ├── apt_packages.txt
│   │       ├── .bash_aliases
│   │       └── bashrc.txt
│   ├── Service_files/
│   ├── shell_scripts/
│   └── ...
│
└── pi4_backups/                      ← Pre-reimage snapshots
    └── pre_reimage_2026-05-11_09-30/
        ├── apt/
        ├── pip/
        ├── services/
        ├── mosquitto/
        ├── crontab/
        ├── ssh/
        ├── aws_certs/
        ├── configs/          ← includes rclone.conf
        ├── influxdb/
        └── code/
            ├── pi4_drive/
            └── python_raspi/
```

---

## GitHub Repository

**`github.com/bs220975/RASPI4-MAIN`** (private)

```
RASPI4-MAIN/
├── OS_Migration/             ← Migration scripts (this folder)
│   ├── COMPLETE_FLOW.md      ← This document
│   ├── README.md
│   ├── scripts/
│   ├── services/
│   └── configs/
├── main.py                   ← mybot entry point
├── config.py
├── aws_certs/                ← AWS IoT certificates
└── requirements.txt
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `mqttdatainflux` crashes at boot | AWS certs missing — restore from `gdrive:/pi4_backups/` |
| `mybot` not connecting | Check `config.py` Telegram token |
| Aliases not working | Run `source ~/.bashrc` or re-login |
| Drive sync fails | Run `rclone config` to re-authenticate |
| InfluxDB not found | Run `which influx` — if missing, re-run STEP 7 manually |
| 32-bit OS flashed by mistake | `getconf LONG_BIT` → should be `64` |
