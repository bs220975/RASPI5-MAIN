#!/bin/bash
# =============================================================
# PRE-REIMAGE BACKUP SCRIPT
# Run this BEFORE flashing new 64-bit OS
# Pi4 | Raspbian → Raspberry Pi OS 64-bit (Bookworm)
# =============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

BACKUP_ROOT="/home/pi/Non-Sync_backup_folder/pre_reimage_$(date +%Y-%m-%d)"

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}   Pi4 Pre-Reimage Backup Script${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""
echo -e "${YELLOW}Backup destination: $BACKUP_ROOT${NC}"
echo ""

mkdir -p "$BACKUP_ROOT"/{apt,pip,services,configs,crontab,ssh,mosquitto,influxdb,aws_certs,code}

# --- 1. APT packages ---
echo -e "${CYAN}[1/10] Exporting apt packages...${NC}"
dpkg --get-selections > "$BACKUP_ROOT/apt/apt_packages.txt"
apt-mark showmanual > "$BACKUP_ROOT/apt/apt_manual.txt"
echo -e "${GREEN}  Done → apt_packages.txt, apt_manual.txt${NC}"

# --- 2. Pip packages ---
echo -e "${CYAN}[2/10] Exporting pip packages...${NC}"
pip3 freeze 2>/dev/null > "$BACKUP_ROOT/pip/pip_root.txt" || true
if [ -d "/home/pi/myenv" ]; then
    source /home/pi/myenv/bin/activate
    pip freeze > "$BACKUP_ROOT/pip/pip_myenv.txt"
    deactivate
fi
echo -e "${GREEN}  Done → pip_root.txt, pip_myenv.txt${NC}"

# --- 3. Systemd services ---
echo -e "${CYAN}[3/10] Backing up systemd services...${NC}"
cp /etc/systemd/system/mqttdatainflux.service "$BACKUP_ROOT/services/" 2>/dev/null || true
cp /etc/systemd/system/mybot.service "$BACKUP_ROOT/services/" 2>/dev/null || true
cp /etc/systemd/system/mybot2.service "$BACKUP_ROOT/services/" 2>/dev/null || true
# List all enabled services
systemctl list-unit-files --state=enabled --no-legend > "$BACKUP_ROOT/services/enabled_services.txt"
echo -e "${GREEN}  Done → services/ folder${NC}"

# --- 4. Mosquitto config ---
echo -e "${CYAN}[4/10] Backing up Mosquitto config...${NC}"
sudo cp -r /etc/mosquitto/ "$BACKUP_ROOT/mosquitto/" 2>/dev/null || true
echo -e "${GREEN}  Done → mosquitto/ folder${NC}"

# --- 5. Crontabs ---
echo -e "${CYAN}[5/10] Exporting crontabs...${NC}"
crontab -l > "$BACKUP_ROOT/crontab/crontab_pi.txt" 2>/dev/null || echo "# No crontab for pi" > "$BACKUP_ROOT/crontab/crontab_pi.txt"
sudo crontab -l > "$BACKUP_ROOT/crontab/crontab_root.txt" 2>/dev/null || echo "# No crontab for root" > "$BACKUP_ROOT/crontab/crontab_root.txt"
echo -e "${GREEN}  Done → crontab_pi.txt, crontab_root.txt${NC}"

# --- 6. SSH keys ---
echo -e "${CYAN}[6/10] Backing up SSH keys...${NC}"
cp -r /home/pi/.ssh/ "$BACKUP_ROOT/ssh/" 2>/dev/null || true
echo -e "${GREEN}  Done → ssh/ folder${NC}"

# --- 7. AWS certs ---
echo -e "${CYAN}[7/10] Backing up AWS certs...${NC}"
# Check common cert locations
for cert_dir in \
    /home/pi/pi4_drive/pi4_python_projects/RASPI4-MAIN/aws_certs \
    /home/pi/aws_certs \
    /home/pi/certs; do
    if [ -d "$cert_dir" ]; then
        cp -r "$cert_dir" "$BACKUP_ROOT/aws_certs/"
        echo -e "${GREEN}  Copied from: $cert_dir${NC}"
    fi
done
echo -e "${GREEN}  Done → aws_certs/ folder${NC}"

# --- 8. .env / config files ---
echo -e "${CYAN}[8/10] Backing up config/env files...${NC}"
find /home/pi/pi4_drive -name "*.env" -o -name "config.py" -o -name "*.cfg" 2>/dev/null | while read f; do
    cp --parents "$f" "$BACKUP_ROOT/configs/" 2>/dev/null || true
done
cp /home/pi/pi4_drive/pi4_python_projects/RASPI4-MAIN/config.py "$BACKUP_ROOT/configs/" 2>/dev/null || true
cp /home/pi/.bashrc "$BACKUP_ROOT/configs/bashrc" 2>/dev/null || true
cp /home/pi/pi4_drive/bashrc.txt "$BACKUP_ROOT/configs/bashrc.txt" 2>/dev/null || true
echo -e "${GREEN}  Done → configs/ folder${NC}"

# --- 9. InfluxDB backup ---
echo -e "${CYAN}[9/10] Backing up InfluxDB data...${NC}"
if command -v influx &>/dev/null; then
    influx backup "$BACKUP_ROOT/influxdb/" 2>/dev/null && echo -e "${GREEN}  InfluxDB backup done${NC}" || echo -e "${YELLOW}  InfluxDB backup skipped (check if running)${NC}"
else
    echo -e "${YELLOW}  influx CLI not found — skipping InfluxDB backup${NC}"
fi

# --- 10. Key code folders ---
echo -e "${CYAN}[10/10] Syncing key code folders...${NC}"
rsync -a /home/pi/pi4_drive/ "$BACKUP_ROOT/code/pi4_drive/" --exclude='.git'
echo -e "${GREEN}  Done → code/pi4_drive/${NC}"

# --- Summary ---
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  BACKUP COMPLETE!${NC}"
echo -e "${GREEN}  Location: $BACKUP_ROOT${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Copy $BACKUP_ROOT to USB drive"
echo "  2. Flash Raspberry Pi OS 64-bit (Bookworm) using Raspberry Pi Imager"
echo "  3. Run: 2_post_install_setup.sh after booting new OS"
echo ""

# Show backup size
du -sh "$BACKUP_ROOT"
