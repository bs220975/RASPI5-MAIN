#!/bin/bash
# =============================================================
# POST-INSTALL SETUP SCRIPT
# Run this AFTER flashing Raspberry Pi OS 64-bit (Bookworm)
# Pi4 | 64-bit arm64 setup
# =============================================================
# Usage:
#   curl -sSL https://raw.githubusercontent.com/bs220975/RASPI4-MAIN/main/OS_Migration/scripts/2_post_install_setup.sh | bash
#   OR: bash 2_post_install_setup.sh
# =============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
NC='\033[0m'

GITHUB_USER="bs220975"
REPO_MAIN="RASPI4-MAIN"
PI4_DRIVE_DIR="/home/pi/pi4_drive"
MYENV_DIR="/home/pi/myenv"
LOG_FILE="/home/pi/post_install_$(date +%Y-%m-%d_%H-%M).log"

log() { echo -e "$1" | tee -a "$LOG_FILE"; }

log "${CYAN}============================================${NC}"
log "${CYAN}   Pi4 Post-Install Setup Script${NC}"
log "${CYAN}   $(date)${NC}"
log "${CYAN}============================================${NC}"
log ""

# Verify 64-bit
ARCH=$(uname -m)
BITS=$(getconf LONG_BIT)
log "${CYAN}System: $ARCH | ${BITS}-bit userland${NC}"
if [ "$BITS" != "64" ]; then
    log "${RED}WARNING: This does not appear to be 64-bit userland (got ${BITS}-bit)${NC}"
    log "${RED}Make sure you flashed Raspberry Pi OS 64-bit${NC}"
    read -p "Continue anyway? (y/n): " cont
    [ "$cont" != "y" ] && exit 1
fi

# ─────────────────────────────────────────────
# STEP 1 — System update
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 1/10] System update & upgrade...${NC}"
sudo apt update -q && sudo apt upgrade -y -q
sudo apt install -y -q \
    git curl wget unzip build-essential \
    python3-pip python3-venv python3-dev \
    libssl-dev libffi-dev \
    i2c-tools libgpiod2 \
    mosquitto mosquitto-clients \
    rclone gh \
    libatlas-base-dev libjpeg-dev \
    cups cups-client
log "${GREEN}  System updated${NC}"

# ─────────────────────────────────────────────
# STEP 2 — GitHub CLI auth
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 2/10] GitHub CLI setup...${NC}"
if ! gh auth status &>/dev/null; then
    log "${YELLOW}  Please authenticate GitHub CLI:${NC}"
    gh auth login
else
    log "${GREEN}  Already authenticated as $(gh api user --jq .login)${NC}"
fi

# ─────────────────────────────────────────────
# STEP 3 — Clone pi4_drive from GitHub
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 3/10] Cloning pi4_drive / RASPI4-MAIN from GitHub...${NC}"
mkdir -p /home/pi/pi4_drive/Git_projects

# Clone main project
if [ ! -d "/home/pi/pi4_drive/Git_projects/RASPI4-MAIN/.git" ]; then
    gh repo clone ${GITHUB_USER}/${REPO_MAIN} /home/pi/pi4_drive/Git_projects/RASPI4-MAIN
    log "${GREEN}  Cloned RASPI4-MAIN${NC}"
else
    log "${GREEN}  RASPI4-MAIN already cloned — pulling latest${NC}"
    git -C /home/pi/pi4_drive/Git_projects/RASPI4-MAIN pull
fi

# ─────────────────────────────────────────────
# STEP 4 — Python virtual environment
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 4/10] Creating Python virtual environment (myenv)...${NC}"
python3 -m venv "$MYENV_DIR"
source "$MYENV_DIR/bin/activate"

log "  Installing pip packages from requirements..."
# Try myenv requirements first (from OS_Migration folder)
MYENV_REQ="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/configs/pip_myenv.txt"
FALLBACK_REQ="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/requirements.txt"

if [ -f "$MYENV_REQ" ]; then
    pip install --upgrade pip -q
    pip install -r "$MYENV_REQ" 2>&1 | tee -a "$LOG_FILE" || true
    log "${GREEN}  Installed from pip_myenv.txt${NC}"
elif [ -f "$FALLBACK_REQ" ]; then
    pip install --upgrade pip -q
    pip install -r "$FALLBACK_REQ" 2>&1 | tee -a "$LOG_FILE" || true
    log "${GREEN}  Installed from requirements.txt${NC}"
else
    log "${YELLOW}  No requirements file found — install manually later${NC}"
fi

deactivate

# ─────────────────────────────────────────────
# STEP 5 — InfluxDB 2 (arm64)
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 5/10] Installing InfluxDB2 (arm64)...${NC}"
INFLUX_VERSION="2.6.1"
INFLUX_PKG="influxdb2-${INFLUX_VERSION}-linux-arm64.tar.gz"
INFLUX_URL="https://dl.influxdata.com/influxdb/releases/${INFLUX_PKG}"

# Check if tarball already exists in pi4_drive
if [ -f "/home/pi/${INFLUX_PKG}" ]; then
    log "  Using existing tarball: /home/pi/${INFLUX_PKG}"
    cp "/home/pi/${INFLUX_PKG}" /tmp/
else
    log "  Downloading InfluxDB2 ${INFLUX_VERSION}..."
    wget -q "$INFLUX_URL" -O "/tmp/${INFLUX_PKG}"
fi

tar xzf "/tmp/${INFLUX_PKG}" -C /tmp/
sudo cp /tmp/influxdb2-${INFLUX_VERSION}/usr/bin/influx /usr/local/bin/
sudo cp /tmp/influxdb2-${INFLUX_VERSION}/usr/bin/influxd /usr/local/bin/

# Install InfluxDB as service
if [ -f "/tmp/influxdb2-${INFLUX_VERSION}/lib/systemd/system/influxdb.service" ]; then
    sudo cp /tmp/influxdb2-${INFLUX_VERSION}/lib/systemd/system/influxdb.service /etc/systemd/system/
fi
sudo systemctl daemon-reload
sudo systemctl enable influxdb
sudo systemctl start influxdb
log "${GREEN}  InfluxDB2 installed and started${NC}"

# ─────────────────────────────────────────────
# STEP 6 — Mosquitto MQTT
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 6/10] Configuring Mosquitto MQTT...${NC}"
sudo systemctl enable mosquitto

# Check if backup config exists
MOSQ_CONF_BACKUP="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/configs/mosquitto"
if [ -d "$MOSQ_CONF_BACKUP" ]; then
    sudo cp -r "$MOSQ_CONF_BACKUP/." /etc/mosquitto/
    log "${GREEN}  Restored Mosquitto config from backup${NC}"
else
    # Fresh config
    sudo tee /etc/mosquitto/conf.d/default.conf > /dev/null <<'EOL'
allow_anonymous false
password_file /etc/mosquitto/passwd
listener 1883 0.0.0.0
EOL
    echo -e "mq\nmq\n" | sudo mosquitto_passwd -c /etc/mosquitto/passwd mq > /dev/null 2>&1
    log "${GREEN}  Fresh Mosquitto config created (user: mq / pass: mq)${NC}"
fi

sudo systemctl restart mosquitto
log "${GREEN}  Mosquitto configured and running${NC}"

# ─────────────────────────────────────────────
# STEP 7 — Systemd services
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 7/10] Installing systemd services...${NC}"
SERVICES_SRC="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/services"

if [ -d "$SERVICES_SRC" ]; then
    for svc in "$SERVICES_SRC"/*.service; do
        svc_name=$(basename "$svc")
        sudo cp "$svc" /etc/systemd/system/
        sudo systemctl enable "$svc_name"
        log "${GREEN}  Enabled: $svc_name${NC}"
    done
    sudo systemctl daemon-reload
else
    log "${YELLOW}  Services folder not found in OS_Migration — copy manually${NC}"
fi

# ─────────────────────────────────────────────
# STEP 8 — AWS certs
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 8/10] AWS certs...${NC}"
CERTS_SRC="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/aws_certs"
CERTS_DEST="/home/pi/pi4_drive/pi4_python_projects/RASPI4-MAIN/aws_certs"

if [ -d "$CERTS_SRC" ]; then
    mkdir -p "$CERTS_DEST"
    cp -r "$CERTS_SRC/." "$CERTS_DEST/"
    log "${GREEN}  AWS certs in place${NC}"
else
    log "${YELLOW}  AWS certs NOT found — restore from USB backup manually:${NC}"
    log "${YELLOW}  cp -r /media/pi/USB/pre_reimage_XXXX/aws_certs/ $CERTS_DEST/${NC}"
fi

# ─────────────────────────────────────────────
# STEP 9 — rclone (Google Drive)
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 9/10] rclone Google Drive setup...${NC}"
RCLONE_CONF_BACKUP="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/configs/rclone.conf"
if [ -f "$RCLONE_CONF_BACKUP" ]; then
    mkdir -p /home/pi/.config/rclone
    cp "$RCLONE_CONF_BACKUP" /home/pi/.config/rclone/rclone.conf
    log "${GREEN}  rclone config restored${NC}"
else
    log "${YELLOW}  No rclone config backup found. Run manually: rclone config${NC}"
fi

# ─────────────────────────────────────────────
# STEP 10 — .bashrc & aliases
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 10/10] Restoring .bashrc & aliases...${NC}"
BASHRC_BACKUP="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/configs/bashrc.txt"
if [ -f "$BASHRC_BACKUP" ]; then
    cp "$BASHRC_BACKUP" /home/pi/.bashrc
    log "${GREEN}  .bashrc restored${NC}"
else
    log "${YELLOW}  No bashrc backup found — skipping${NC}"
fi

# ─────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────
log ""
log "${GREEN}============================================${NC}"
log "${GREEN}  POST-INSTALL COMPLETE!${NC}"
log "${GREEN}  Log saved to: $LOG_FILE${NC}"
log "${GREEN}============================================${NC}"
log ""
log "${YELLOW}Manual steps remaining:${NC}"
log "  1. Restore AWS certs from USB if not auto-copied"
log "  2. Restore InfluxDB data: influx restore /path/to/backup/influxdb/"
log "  3. Restore crontab:  crontab /path/to/backup/crontab_pi.txt"
log "  4. Start services:   sudo systemctl start mybot.service mqttdatainflux.service"
log "  5. Verify services:  systemctl status mybot.service mqttdatainflux.service"
log "  6. Test MQTT:        mosquitto_pub -h localhost -t test -m hello -u mq -P mq"
log "  7. Open InfluxDB UI: http://localhost:8086"
log ""
