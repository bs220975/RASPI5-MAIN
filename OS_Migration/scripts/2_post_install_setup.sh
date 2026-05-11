#!/bin/bash
# =============================================================
# POST-INSTALL SETUP SCRIPT
# Run this AFTER flashing Raspberry Pi OS 64-bit (Bookworm)
# Pi4 | 64-bit arm64 setup
# =============================================================
# Usage (on fresh Pi, SSH in first):
#   wget -qO- https://raw.githubusercontent.com/bs220975/RASPI4-MAIN/main/OS_Migration/scripts/2_post_install_setup.sh | bash
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
ask() { echo -e "${YELLOW}$1${NC}"; read -p "(y/n): " _ans; [[ "$_ans" == "y" || "$_ans" == "Y" ]]; }

log "${CYAN}============================================${NC}"
log "${CYAN}   Pi4 Post-Install Setup Script${NC}"
log "${CYAN}   $(date)${NC}"
log "${CYAN}============================================${NC}"
log ""

# ── Verify 64-bit ────────────────────────────────────────────
ARCH=$(uname -m)
BITS=$(getconf LONG_BIT)
log "${CYAN}System: $ARCH | ${BITS}-bit userland${NC}"
if [ "$BITS" != "64" ]; then
    log "${RED}WARNING: Not 64-bit userland (got ${BITS}-bit) — make sure you used Raspberry Pi OS 64-bit${NC}"
    ask "Continue anyway?" || exit 1
fi

# ─────────────────────────────────────────────
# STEP 1 — System update & core packages
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 1/11] System update & install packages...${NC}"
sudo apt update -q && sudo apt upgrade -y -q
sudo apt install -y -q \
    git curl wget unzip build-essential \
    python3-pip python3-venv python3-dev \
    libssl-dev libffi-dev \
    i2c-tools libgpiod2 \
    mosquitto mosquitto-clients \
    rclone \
    libatlas-base-dev libjpeg-dev \
    cups cups-client
log "${GREEN}  System updated and packages installed${NC}"

# Install GitHub CLI (gh) separately — not always in apt
if ! command -v gh &>/dev/null; then
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    sudo apt update -q && sudo apt install -y -q gh
fi
log "${GREEN}  GitHub CLI ready${NC}"

# ─────────────────────────────────────────────
# STEP 2 — GitHub CLI auth
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 2/11] GitHub CLI authentication...${NC}"
if ! gh auth status &>/dev/null; then
    log "${YELLOW}  Login to GitHub (opens browser or use token):${NC}"
    gh auth login
else
    log "${GREEN}  Already authenticated as $(gh api user --jq .login)${NC}"
fi

# ─────────────────────────────────────────────
# STEP 3 — rclone (Google Drive) setup
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 3/11] Google Drive (rclone) setup...${NC}"
mkdir -p /home/pi/.config/rclone

# Try to restore rclone.conf — check USB first, then prompt for manual auth
RCLONE_RESTORED=false
for usb_path in /media/pi /media/${USER} /mnt; do
    for backup_dir in $(ls -d ${usb_path}/*/pre_reimage_* 2>/dev/null | head -3); do
        RCLONE_FROM="$backup_dir/configs/rclone.conf"
        if [ -f "$RCLONE_FROM" ]; then
            cp "$RCLONE_FROM" /home/pi/.config/rclone/rclone.conf
            log "${GREEN}  rclone.conf restored from USB: $RCLONE_FROM${NC}"
            RCLONE_RESTORED=true
            break 2
        fi
    done
done

if [ "$RCLONE_RESTORED" = false ]; then
    log "${YELLOW}  No USB backup found — running rclone config interactively${NC}"
    log "${YELLOW}  When prompted: n → name=gdrive → type=drive → scope=drive → use auto config=y${NC}"
    rclone config
fi

# Verify rclone can reach Google Drive
if rclone lsd gdrive:/ &>/dev/null; then
    log "${GREEN}  Google Drive connected successfully${NC}"
else
    log "${RED}  Could not connect to Google Drive — check rclone config${NC}"
    log "${YELLOW}  Run manually: rclone config (add remote named 'gdrive')${NC}"
fi

# ─────────────────────────────────────────────
# STEP 4 — Sync pi4_drive from Google Drive
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 4/11] Restoring pi4_drive from Google Drive...${NC}"
mkdir -p "$PI4_DRIVE_DIR"

# Check for pre-reimage backup on Drive first, then fall back to pi4_drive sync
GDRIVE_BACKUP_DIR=""
if rclone lsd gdrive:/pi4_backups &>/dev/null 2>&1; then
    # Find the latest pre_reimage_* backup
    GDRIVE_BACKUP_DIR=$(rclone lsd gdrive:/pi4_backups/ 2>/dev/null | awk '{print $NF}' | grep "pre_reimage_" | sort -r | head -1)
fi

if [ -n "$GDRIVE_BACKUP_DIR" ]; then
    log "${GREEN}  Found backup on Google Drive: gdrive:/pi4_backups/${GDRIVE_BACKUP_DIR}${NC}"
    log ""
    if ask "  Restore from gdrive:/pi4_backups/${GDRIVE_BACKUP_DIR}?"; then
        log "  Downloading backup... (this may take a few minutes)"
        rclone copy "gdrive:/pi4_backups/${GDRIVE_BACKUP_DIR}/code/pi4_drive" "$PI4_DRIVE_DIR" --progress 2>&1 | tee -a "$LOG_FILE"
        # Restore rclone.conf from Drive backup if not already restored from USB
        if [ "$RCLONE_RESTORED" = false ]; then
            rclone copy "gdrive:/pi4_backups/${GDRIVE_BACKUP_DIR}/configs/rclone.conf" /home/pi/.config/rclone/ 2>/dev/null && \
                log "${GREEN}  rclone.conf restored from Drive backup${NC}" || true
        fi
        # Restore crontab
        TMP_CRON=$(mktemp)
        rclone copy "gdrive:/pi4_backups/${GDRIVE_BACKUP_DIR}/crontab/crontab_pi.txt" /tmp/ 2>/dev/null && \
            crontab /tmp/crontab_pi.txt 2>/dev/null && \
            log "${GREEN}  Crontab restored${NC}" || true
        log "${GREEN}  Backup restored from Google Drive${NC}"
    else
        log "${YELLOW}  Skipped backup restore${NC}"
    fi
fi

# Also sync live pi4_drive from Drive
if rclone lsd gdrive:/pi4_drive &>/dev/null 2>&1; then
    log ""
    log "${CYAN}  Found gdrive:/pi4_drive (your live working folder)${NC}"
    if ask "  Also sync gdrive:/pi4_drive → /home/pi/pi4_drive?"; then
        log "  Syncing pi4_drive..."
        rclone sync gdrive:/pi4_drive "$PI4_DRIVE_DIR" --progress 2>&1 | tee -a "$LOG_FILE"
        log "${GREEN}  pi4_drive synced from Google Drive${NC}"
    fi
else
    log "${YELLOW}  gdrive:/pi4_drive not found — skipping${NC}"
fi

# Always ensure key subfolders exist
mkdir -p "$PI4_DRIVE_DIR"/{Git_projects,Service_files,shell_scripts,Error_and_Logs,pi4_python_projects,alias_command_file,OS_Migration}
log "${GREEN}  pi4_drive folder structure created${NC}"

# ─────────────────────────────────────────────
# STEP 5 — Clone RASPI4-MAIN from GitHub
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 5/11] Cloning RASPI4-MAIN from GitHub...${NC}"
if [ ! -d "$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/.git" ]; then
    gh repo clone ${GITHUB_USER}/${REPO_MAIN} "$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN"
    log "${GREEN}  Cloned RASPI4-MAIN${NC}"
else
    log "${GREEN}  RASPI4-MAIN already exists — pulling latest${NC}"
    git -C "$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN" pull
fi

# Also link pi4_python_projects/RASPI4-MAIN → Git_projects/RASPI4-MAIN if not present
PROJ_DIR="$PI4_DRIVE_DIR/pi4_python_projects/RASPI4-MAIN"
if [ ! -d "$PROJ_DIR" ]; then
    mkdir -p "$PI4_DRIVE_DIR/pi4_python_projects"
    ln -s "$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN" "$PROJ_DIR"
    log "${GREEN}  Symlink: pi4_python_projects/RASPI4-MAIN → Git_projects/RASPI4-MAIN${NC}"
fi

# ─────────────────────────────────────────────
# STEP 6 — Python virtual environment
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 6/11] Creating Python virtual environment (myenv)...${NC}"
python3 -m venv "$MYENV_DIR"
source "$MYENV_DIR/bin/activate"
pip install --upgrade pip -q

# Use pip_myenv.txt from OS_Migration (now available after Drive sync + GitHub clone)
MYENV_REQ="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/configs/pip_myenv.txt"
FALLBACK_REQ="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/requirements.txt"

if [ -f "$MYENV_REQ" ]; then
    log "  Installing from pip_myenv.txt (${MYENV_REQ})..."
    pip install -r "$MYENV_REQ" 2>&1 | tee -a "$LOG_FILE" || true
    log "${GREEN}  pip packages installed${NC}"
elif [ -f "$FALLBACK_REQ" ]; then
    log "  Installing from requirements.txt..."
    pip install -r "$FALLBACK_REQ" 2>&1 | tee -a "$LOG_FILE" || true
    log "${GREEN}  pip packages installed${NC}"
else
    log "${YELLOW}  No requirements file found — install manually: pip install -r pip_myenv.txt${NC}"
fi
deactivate

# ─────────────────────────────────────────────
# STEP 7 — InfluxDB 2 (arm64)
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 7/11] Installing InfluxDB2 (arm64)...${NC}"
INFLUX_VERSION="2.6.1"
INFLUX_PKG="influxdb2-${INFLUX_VERSION}-linux-arm64.tar.gz"
INFLUX_URL="https://dl.influxdata.com/influxdb/releases/${INFLUX_PKG}"

# Check if tarball already synced from Drive
if [ -f "/home/pi/${INFLUX_PKG}" ]; then
    log "  Found tarball at /home/pi/${INFLUX_PKG}"
    cp "/home/pi/${INFLUX_PKG}" /tmp/
else
    log "  Downloading InfluxDB2 ${INFLUX_VERSION}..."
    wget -q "$INFLUX_URL" -O "/tmp/${INFLUX_PKG}"
fi

tar xzf "/tmp/${INFLUX_PKG}" -C /tmp/
sudo cp /tmp/influxdb2-${INFLUX_VERSION}/usr/bin/influx /usr/local/bin/
sudo cp /tmp/influxdb2-${INFLUX_VERSION}/usr/bin/influxd /usr/local/bin/
[ -f "/tmp/influxdb2-${INFLUX_VERSION}/lib/systemd/system/influxdb.service" ] && \
    sudo cp /tmp/influxdb2-${INFLUX_VERSION}/lib/systemd/system/influxdb.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable influxdb
sudo systemctl start influxdb
log "${GREEN}  InfluxDB2 installed and running${NC}"

# ─────────────────────────────────────────────
# STEP 8 — Mosquitto MQTT
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 8/11] Configuring Mosquitto MQTT...${NC}"
sudo systemctl enable mosquitto

MOSQ_CONF_BACKUP="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/configs/mosquitto"
if [ -d "$MOSQ_CONF_BACKUP" ]; then
    sudo cp -r "$MOSQ_CONF_BACKUP/." /etc/mosquitto/
    log "${GREEN}  Mosquitto config restored from backup${NC}"
else
    sudo tee /etc/mosquitto/conf.d/default.conf > /dev/null <<'EOL'
allow_anonymous false
password_file /etc/mosquitto/passwd
listener 1883 0.0.0.0
EOL
    echo -e "mq\nmq\n" | sudo mosquitto_passwd -c /etc/mosquitto/passwd mq > /dev/null 2>&1
    log "${GREEN}  Mosquitto configured (user: mq / pass: mq)${NC}"
fi
sudo systemctl restart mosquitto
log "${GREEN}  Mosquitto running${NC}"

# ─────────────────────────────────────────────
# STEP 9 — Systemd services
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 9/11] Installing systemd services...${NC}"
SERVICES_SRC="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/services"

# Log folder required by service files
mkdir -p "$PI4_DRIVE_DIR/Error_and_Logs"
log "${GREEN}  Error_and_Logs folder ready${NC}"

if [ -d "$SERVICES_SRC" ]; then
    # mybot.service — enabled (runs RASPI4-MAIN/main.py via myenv, restart=always)
    sudo cp "$SERVICES_SRC/mybot.service" /etc/systemd/system/
    sudo systemctl enable mybot.service
    log "${GREEN}  [ENABLED + AUTOSTART] mybot.service${NC}"

    # mqttdatainflux.service — enabled (runs influxdb2_aws_publish.py via myenv, restart=on-failure)
    sudo cp "$SERVICES_SRC/mqttdatainflux.service" /etc/systemd/system/
    sudo systemctl enable mqttdatainflux.service
    log "${GREEN}  [ENABLED + AUTOSTART] mqttdatainflux.service${NC}"

    # mybot2.service — installed but NOT enabled (was inactive on original Pi)
    sudo cp "$SERVICES_SRC/mybot2.service" /etc/systemd/system/ 2>/dev/null || true
    log "${YELLOW}  [INSTALLED, NOT ENABLED] mybot2.service — enable manually if needed${NC}"

    sudo systemctl daemon-reload
else
    log "${RED}  Services folder missing — copy .service files manually${NC}"
fi

# ─────────────────────────────────────────────
# STEP 10 — AWS certs
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 10/11] AWS certs...${NC}"
CERTS_DEST="$PI4_DRIVE_DIR/pi4_python_projects/RASPI4-MAIN/aws_certs"

# Check GitHub repo (aws_certs is committed there)
CERTS_SRC="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/aws_certs"
if [ -d "$CERTS_SRC" ] && [ "$(ls -A $CERTS_SRC)" ]; then
    mkdir -p "$CERTS_DEST"
    cp -r "$CERTS_SRC/." "$CERTS_DEST/"
    log "${GREEN}  AWS certs copied from GitHub repo${NC}"
else
    # Try Drive backup
    if [ -n "$GDRIVE_BACKUP_DIR" ]; then
        mkdir -p "$CERTS_DEST"
        rclone copy "gdrive:/pi4_backups/${GDRIVE_BACKUP_DIR}/aws_certs" "$CERTS_DEST" 2>/dev/null && \
            log "${GREEN}  AWS certs restored from Google Drive backup${NC}" || true
    fi
    # Try USB backup as fallback
    if [ -z "$(ls -A $CERTS_DEST 2>/dev/null)" ]; then
        for usb_path in /media/pi /media/${USER} /mnt; do
            for backup_dir in $(ls -d ${usb_path}/*/pre_reimage_* 2>/dev/null); do
                if [ -d "$backup_dir/aws_certs" ]; then
                    mkdir -p "$CERTS_DEST"
                    cp -r "$backup_dir/aws_certs/." "$CERTS_DEST/"
                    log "${GREEN}  AWS certs restored from USB backup${NC}"
                    break 2
                fi
            done
        done
    fi
    if [ -z "$(ls -A $CERTS_DEST 2>/dev/null)" ]; then
        log "${RED}  AWS certs NOT found — mqttdatainflux will fail until restored${NC}"
        log "${YELLOW}  Copy manually: cp -r /path/to/aws_certs/ $CERTS_DEST/${NC}"
    fi
fi

# ─────────────────────────────────────────────
# STEP 11 — .bashrc & aliases
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 11/11] Restoring .bashrc & aliases...${NC}"
BASHRC_BACKUP="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/configs/bashrc.txt"
ALIASES_BACKUP="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/configs/.bash_aliases"

if [ -f "$BASHRC_BACKUP" ]; then
    cp "$BASHRC_BACKUP" /home/pi/.bashrc
    log "${GREEN}  .bashrc restored${NC}"
fi

if [ -f "$ALIASES_BACKUP" ]; then
    cp "$ALIASES_BACKUP" /home/pi/.bash_aliases
    log "${GREEN}  .bash_aliases restored — all aliases active on next login${NC}"
fi

# PATH for shell_scripts
grep -q "pi4_drive/shell_scripts" /home/pi/.bashrc || \
    echo 'export PATH="$PATH:/home/pi/pi4_drive/shell_scripts"' >> /home/pi/.bashrc

# ─────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────
log ""
log "${GREEN}============================================${NC}"
log "${GREEN}  POST-INSTALL COMPLETE!${NC}"
log "${GREEN}  Log: $LOG_FILE${NC}"
log "${GREEN}============================================${NC}"
log ""
log "${CYAN}Service autostart summary:${NC}"
log "  mybot.service          → ENABLED (starts on boot)"
log "  mqttdatainflux.service → ENABLED (starts on boot, needs AWS certs)"
log "  mybot2.service         → installed but NOT enabled"
log "  mosquitto              → ENABLED (starts on boot)"
log "  influxdb               → ENABLED (starts on boot)"
log "  ssh                    → ENABLED (default)"
log ""
log "${YELLOW}Remaining manual steps:${NC}"
log "  1. If AWS certs missing:  cp -r /media/pi/USB/.../aws_certs/ $CERTS_DEST/"
log "  2. Restore InfluxDB data: influx restore /media/pi/USB/.../influxdb/"
log "  3. Restore crontab:       crontab /media/pi/USB/.../crontab/crontab_pi.txt"
log "  4. Start services now:    sudo systemctl start mybot.service mqttdatainflux.service"
log "  5. Verify:                bash $PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/scripts/3_verify_setup.sh"
log "  6. Re-login for aliases:  source ~/.bashrc"
log ""
