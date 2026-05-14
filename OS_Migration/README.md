# Pi4 OS Migration — 32-bit → 64-bit

## Current Status (before reimage)
- **OS**: Raspbian GNU/Linux 12 (Bookworm) — **32-bit userland (armhf)**
- **Kernel**: 64-bit (aarch64)
- **Target**: Raspberry Pi OS 64-bit (Bookworm) — **arm64**
- **Hardware**: Raspberry Pi 4

---

## Folder Structure

```
OS_Migration/
├── README.md                    ← This file
├── scripts/
│   ├── 1_backup_before_reimage.sh   ← Run BEFORE flashing
│   ├── 2_post_install_setup.sh      ← Run AFTER flashing
│   └── 3_verify_setup.sh            ← Run to check everything
├── services/
│   ├── mqttdatainflux.service
│   ├── mybot.service
│   └── mybot2.service
└── configs/
    ├── pip_myenv.txt            ← Python packages for myenv
    ├── pip_root.txt             ← Python packages (system)
    ├── apt_packages.txt         ← All apt installed packages
    ├── apt_manual.txt           ← Manually installed apt packages
    ├── bashrc.txt               ← .bashrc customizations
    ├── rclone.conf              ← Google Drive rclone config
    └── mosquitto/               ← Mosquitto configs (if backed up)
```

---

## Step-by-Step Migration

### Step 1 — Backup (run on OLD Pi before wiping)
```bash
bash scripts/1_backup_before_reimage.sh
# Saves to: /home/pi/Non-Sync_backup_folder/pre_reimage_YYYY-MM-DD/
# Copy that folder to a USB drive!
```

### Step 2 — Flash 64-bit OS
1. Download **Raspberry Pi Imager** on your PC/Mac
2. Choose: **Raspberry Pi OS (64-bit)** — Bookworm
3. Click gear icon → set: hostname=`pi`, enable SSH, set username=`pi`, set WiFi
4. Flash the SD card

### Step 3 — First boot & setup
```bash
# SSH into new Pi, then clone this repo:
gh repo clone bs220975/RASPI4-MAIN ~/pi4_drive/Git_projects/RASPI4-MAIN

# Run the post-install script:
bash ~/pi4_drive/Git_projects/RASPI4-MAIN/OS_Migration/scripts/2_post_install_setup.sh
```

### Step 4 — Verify
```bash
bash ~/pi4_drive/Git_projects/RASPI4-MAIN/OS_Migration/scripts/3_verify_setup.sh
```

---

## Services Running on Pi4

| Service | Description |
|---|---|
| `mybot.service` | Telegram bot + ESP32 handler (RASPI4-MAIN/main.py) |
| `mqttdatainflux.service` | MQTT → InfluxDB + AWS publisher |
| `mosquitto` | MQTT broker (port 1883, user: mq) |
| `influxdb` | InfluxDB 2.x (port 8086) |

---

## Key Paths (post-install)

| Path | Purpose |
|---|---|
| `/home/pi/myenv/` | Python virtual environment |
| `/home/pi/pi4_drive/` | Main working folder (synced to Google Drive) |
| `/home/pi/pi4_drive/Git_projects/RASPI4-MAIN/` | Main Pi4 project |
| `/home/pi/pi4_drive/Git_projects/RASPI4-MAIN/logs/` | Service logs |
| `~/.config/rclone/rclone.conf` | Google Drive sync config |

---

## Manual Steps After Setup

1. **AWS Certs** — Copy from USB backup if not auto-restored:
   ```bash
   cp -r /media/pi/USB/pre_reimage_*/aws_certs/ \
     /home/pi/pi4_drive/Git_projects/RASPI4-MAIN/aws_certs/
   ```

2. **InfluxDB data** — Restore from backup:
   ```bash
   influx restore /media/pi/USB/pre_reimage_*/influxdb/
   ```

3. **Crontab** — Restore:
   ```bash
   crontab /media/pi/USB/pre_reimage_*/crontab/crontab_pi.txt
   ```

4. **Google Drive sync** — If rclone config not auto-restored:
   ```bash
   rclone config
   # Add remote named "gdrive" → Google Drive
   ```
