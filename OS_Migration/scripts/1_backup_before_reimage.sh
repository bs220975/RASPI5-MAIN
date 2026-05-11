#!/bin/bash
# =============================================================
# PRE-REIMAGE BACKUP SCRIPT
# Backs up to Google Drive if total size < 600 MB
# Falls back to local USB if Drive unavailable or size exceeded
# Run this BEFORE flashing new 64-bit OS
# =============================================================

# Note: intentionally no 'set -e' — backup should continue even if individual steps fail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SIZE_LIMIT_MB=600
DATE=$(date +"%Y-%m-%d_%H-%M")
BACKUP_NAME="pre_reimage_${DATE}"
GDRIVE_DEST="gdrive:/pi4_backups/${BACKUP_NAME}"
LOCAL_STAGING="/tmp/pi4_backup_staging/${BACKUP_NAME}"

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}   Pi4 Pre-Reimage Backup Script${NC}"
echo -e "${CYAN}   $(date)${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# ─────────────────────────────────────────────
# Estimate backup size first
# ─────────────────────────────────────────────
echo -e "${CYAN}Calculating backup size...${NC}"

ITEMS=(
    /home/pi/pi4_drive
    /home/pi/python_raspi
    /home/pi/.ssh
    /home/pi/.bashrc
    /home/pi/.bash_aliases
    /home/pi/.config/rclone/rclone.conf
    /etc/mosquitto
)

TOTAL_BYTES=0
for item in "${ITEMS[@]}"; do
    if [ -e "$item" ]; then
        SIZE=$(du -sb "$item" 2>/dev/null | awk '{print $1}')
        TOTAL_BYTES=$((TOTAL_BYTES + SIZE))
    fi
done
TOTAL_MB=$((TOTAL_BYTES / 1024 / 1024))

echo -e "  Estimated backup size: ${YELLOW}${TOTAL_MB} MB${NC} (limit: ${SIZE_LIMIT_MB} MB)"
echo ""

# ─────────────────────────────────────────────
# Choose destination
# ─────────────────────────────────────────────
USE_GDRIVE=false

if [ "$TOTAL_MB" -lt "$SIZE_LIMIT_MB" ]; then
    # Check if rclone + gdrive is available
    if command -v rclone &>/dev/null && rclone lsd gdrive:/ &>/dev/null 2>&1; then
        echo -e "${GREEN}  Size OK (${TOTAL_MB} MB < ${SIZE_LIMIT_MB} MB) — backing up to Google Drive${NC}"
        echo -e "  Destination: ${CYAN}${GDRIVE_DEST}${NC}"
        USE_GDRIVE=true
    else
        echo -e "${YELLOW}  Google Drive not available (rclone not configured)${NC}"
        echo -e "${YELLOW}  Falling back to local staging + manual USB copy${NC}"
    fi
else
    echo -e "${RED}  Size ${TOTAL_MB} MB exceeds ${SIZE_LIMIT_MB} MB limit — using local staging${NC}"
fi

# ─────────────────────────────────────────────
# Create staging folder
# ─────────────────────────────────────────────
mkdir -p "$LOCAL_STAGING"/{apt,pip,services,configs,crontab,ssh,mosquitto,aws_certs,code}

# ─────────────────────────────────────────────
# 1. APT packages
# ─────────────────────────────────────────────
echo -e "${CYAN}[1/10] Exporting apt packages...${NC}"
dpkg --get-selections > "$LOCAL_STAGING/apt/apt_packages.txt"
apt-mark showmanual > "$LOCAL_STAGING/apt/apt_manual.txt"
echo -e "${GREEN}  Done${NC}"

# ─────────────────────────────────────────────
# 2. Pip packages
# ─────────────────────────────────────────────
echo -e "${CYAN}[2/10] Exporting pip packages...${NC}"
pip3 freeze 2>/dev/null > "$LOCAL_STAGING/pip/pip_root.txt" || true
if [ -d "/home/pi/myenv" ]; then
    source /home/pi/myenv/bin/activate
    pip freeze > "$LOCAL_STAGING/pip/pip_myenv.txt"
    deactivate
fi
echo -e "${GREEN}  Done${NC}"

# ─────────────────────────────────────────────
# 3. Systemd services
# ─────────────────────────────────────────────
echo -e "${CYAN}[3/10] Backing up systemd services...${NC}"
for svc in mqttdatainflux mybot mybot2; do
    cp /etc/systemd/system/${svc}.service "$LOCAL_STAGING/services/" 2>/dev/null || true
done
systemctl list-unit-files --state=enabled --no-legend > "$LOCAL_STAGING/services/enabled_services.txt"
echo -e "${GREEN}  Done${NC}"

# ─────────────────────────────────────────────
# 4. Mosquitto config
# ─────────────────────────────────────────────
echo -e "${CYAN}[4/10] Backing up Mosquitto config...${NC}"
sudo cp -r /etc/mosquitto/. "$LOCAL_STAGING/mosquitto/" 2>/dev/null || true
echo -e "${GREEN}  Done${NC}"

# ─────────────────────────────────────────────
# 5. Crontabs
# ─────────────────────────────────────────────
echo -e "${CYAN}[5/10] Exporting crontabs...${NC}"
crontab -l > "$LOCAL_STAGING/crontab/crontab_pi.txt" 2>/dev/null || echo "# empty" > "$LOCAL_STAGING/crontab/crontab_pi.txt"
sudo crontab -l > "$LOCAL_STAGING/crontab/crontab_root.txt" 2>/dev/null || echo "# empty" > "$LOCAL_STAGING/crontab/crontab_root.txt"
echo -e "${GREEN}  Done${NC}"

# ─────────────────────────────────────────────
# 6. SSH keys
# ─────────────────────────────────────────────
echo -e "${CYAN}[6/10] Backing up SSH keys...${NC}"
cp -r /home/pi/.ssh/. "$LOCAL_STAGING/ssh/" 2>/dev/null || true
echo -e "${GREEN}  Done${NC}"

# ─────────────────────────────────────────────
# 7. AWS certs
# ─────────────────────────────────────────────
echo -e "${CYAN}[7/10] Backing up AWS certs...${NC}"
for cert_dir in \
    /home/pi/pi4_drive/pi4_python_projects/RASPI4-MAIN/aws_certs \
    /home/pi/pi4_drive/Git_projects/RASPI4-MAIN/aws_certs \
    /home/pi/aws_certs; do
    if [ -d "$cert_dir" ] && [ "$(ls -A $cert_dir)" ]; then
        cp -r "$cert_dir/." "$LOCAL_STAGING/aws_certs/"
        echo -e "${GREEN}  Copied from: $cert_dir${NC}"
        break
    fi
done
echo -e "${GREEN}  Done${NC}"

# ─────────────────────────────────────────────
# 8. Config files
# ─────────────────────────────────────────────
echo -e "${CYAN}[8/10] Backing up config files...${NC}"
cp /home/pi/.bashrc          "$LOCAL_STAGING/configs/bashrc"          2>/dev/null || true
cp /home/pi/.bash_aliases    "$LOCAL_STAGING/configs/.bash_aliases"   2>/dev/null || true
cp /home/pi/pi4_drive/bashrc.txt "$LOCAL_STAGING/configs/bashrc.txt" 2>/dev/null || true
# rclone.conf — needed to restore Drive auth on new Pi
cp /home/pi/.config/rclone/rclone.conf "$LOCAL_STAGING/configs/rclone.conf" 2>/dev/null || true
cp /home/pi/pi4_drive/Git_projects/RASPI4-MAIN/config.py "$LOCAL_STAGING/configs/config.py" 2>/dev/null || true
echo -e "${GREEN}  Done (includes rclone.conf)${NC}"

# ─────────────────────────────────────────────
# 9. InfluxDB backup
# ─────────────────────────────────────────────
echo -e "${CYAN}[9/10] Backing up InfluxDB data...${NC}"
if command -v influx &>/dev/null && systemctl is-active --quiet influxdb; then
    influx backup "$LOCAL_STAGING/influxdb/" 2>/dev/null \
        && echo -e "${GREEN}  InfluxDB backup done${NC}" \
        || echo -e "${YELLOW}  InfluxDB backup failed — check if running${NC}"
else
    echo -e "${YELLOW}  InfluxDB not running — skipping${NC}"
fi

# ─────────────────────────────────────────────
# 10. pi4_drive + python_raspi code
# ─────────────────────────────────────────────
echo -e "${CYAN}[10/10] Syncing code folders...${NC}"
rsync -a --exclude='.git' /home/pi/pi4_drive/ "$LOCAL_STAGING/code/pi4_drive/"
rsync -a /home/pi/python_raspi/ "$LOCAL_STAGING/code/python_raspi/" 2>/dev/null || true
echo -e "${GREEN}  Done${NC}"

# ─────────────────────────────────────────────
# Upload or report
# ─────────────────────────────────────────────
STAGING_SIZE_MB=$(du -sm "$LOCAL_STAGING" | awk '{print $1}')
echo ""
echo -e "${CYAN}Staged backup size: ${STAGING_SIZE_MB} MB${NC}"

if [ "$USE_GDRIVE" = true ]; then
    echo ""
    echo -e "${CYAN}Uploading to Google Drive...${NC}"
    echo -e "  → ${GDRIVE_DEST}"
    rclone copy "$LOCAL_STAGING" "$GDRIVE_DEST" --progress 2>&1
    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  BACKUP UPLOADED TO GOOGLE DRIVE${NC}"
    echo -e "${GREEN}  gdrive:/pi4_backups/${BACKUP_NAME}${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo -e "${YELLOW}On new Pi, post-install script will find this at:${NC}"
    echo -e "  gdrive:/pi4_backups/${BACKUP_NAME}"
    # Clean up staging
    rm -rf /tmp/pi4_backup_staging
else
    echo ""
    echo -e "${YELLOW}============================================${NC}"
    echo -e "${YELLOW}  BACKUP STAGED LOCALLY — COPY TO USB${NC}"
    echo -e "${YELLOW}  ${LOCAL_STAGING}${NC}"
    echo -e "${YELLOW}============================================${NC}"
    echo ""
    echo -e "Copy to USB manually:"
    echo -e "  cp -r \"$LOCAL_STAGING\" /media/pi/YOUR_USB/"
fi
