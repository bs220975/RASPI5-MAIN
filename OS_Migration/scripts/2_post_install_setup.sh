#!/bin/bash
# =============================================================
# POST-INSTALL SETUP SCRIPT
# Raspberry Pi OS 64-bit (Bookworm) | Pi4
# =============================================================
# Usage (SSH into fresh Pi, then run):
#   wget -qO- https://raw.githubusercontent.com/bs220975/RASPI4-MAIN/main/OS_Migration/scripts/2_post_install_setup.sh | bash
# =============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
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
    log "${RED}WARNING: Not 64-bit — make sure you flashed Raspberry Pi OS 64-bit${NC}"
    ask "Continue anyway?" || exit 1
fi

# ═══════════════════════════════════════════════════════════════
# STEP 1 — Install Claude CLI FIRST
#           so Claude is available for the rest of the setup
# ═══════════════════════════════════════════════════════════════
log ""
log "${MAGENTA}[STEP 1/12] Installing Claude CLI first...${NC}"

# Minimal packages needed just to install Claude
sudo apt update -q
sudo apt install -y -q curl wget

# Node.js 20 LTS via NodeSource
if ! node --version 2>/dev/null | grep -qE "v(18|20|22)"; then
    log "  Installing Node.js 20 LTS..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - -q
    sudo apt install -y -q nodejs
fi
log "${GREEN}  Node.js $(node --version) ready${NC}"

# Claude CLI
if command -v claude &>/dev/null; then
    log "${YELLOW}  Upgrading Claude CLI...${NC}"
    sudo npm install -g @anthropic-ai/claude-code --loglevel=error
else
    log "  Installing Claude CLI..."
    sudo npm install -g @anthropic-ai/claude-code --loglevel=error
fi
CLAUDE_VER=$(claude --version 2>/dev/null | head -1)
log "${GREEN}  Claude CLI ready: $CLAUDE_VER${NC}"
log ""
log "${MAGENTA}  ★ Claude CLI is now installed!${NC}"
log "${MAGENTA}  ★ After this script finishes, run: claude${NC}"
log "${MAGENTA}  ★ Login with your Anthropic account — Claude will assist you with anything else${NC}"
log ""

# ─────────────────────────────────────────────
# STEP 2 — System update & all packages
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 2/12] Full system update & install packages...${NC}"
sudo apt upgrade -y -q
sudo apt install -y -q \
    git unzip build-essential \
    python3-pip python3-venv python3-dev \
    libssl-dev libffi-dev \
    i2c-tools libgpiod2 \
    mosquitto mosquitto-clients \
    rclone \
    libatlas-base-dev libjpeg-dev \
    cups cups-client
log "${GREEN}  All packages installed${NC}"

# GitHub CLI
if ! command -v gh &>/dev/null; then
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    sudo apt update -q && sudo apt install -y -q gh
fi
log "${GREEN}  GitHub CLI ready${NC}"

# ─────────────────────────────────────────────
# STEP 3 — GitHub CLI auth  [USER INPUT]
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 3/12] GitHub CLI authentication...${NC}"
if ! gh auth status &>/dev/null; then
    log "${YELLOW}  ► ACTION NEEDED: Login to GitHub (browser or token)${NC}"
    gh auth login
else
    log "${GREEN}  Already authenticated as $(gh api user --jq .login)${NC}"
fi

# ─────────────────────────────────────────────
# STEP 4 — rclone Google Drive setup  [USER INPUT if no backup]
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 4/12] Google Drive (rclone) setup...${NC}"
mkdir -p /home/pi/.config/rclone

RCLONE_RESTORED=false
# Try USB backup first
for usb_path in /media/pi /media/${USER} /mnt; do
    for backup_dir in $(ls -d ${usb_path}/*/pre_reimage_* 2>/dev/null | head -3); do
        if [ -f "$backup_dir/configs/rclone.conf" ]; then
            cp "$backup_dir/configs/rclone.conf" /home/pi/.config/rclone/rclone.conf
            log "${GREEN}  rclone.conf restored from USB${NC}"
            RCLONE_RESTORED=true
            break 2
        fi
    done
done

if [ "$RCLONE_RESTORED" = false ]; then
    log "${YELLOW}  ► ACTION NEEDED: No USB backup found — configure Google Drive now${NC}"
    log "${YELLOW}    When prompted: n → name=gdrive → type=drive → scope=drive → auto config=y${NC}"
    rclone config
fi

if rclone lsd gdrive:/ &>/dev/null; then
    log "${GREEN}  Google Drive connected${NC}"
else
    log "${RED}  Drive not connected — check rclone config${NC}"
fi

# ─────────────────────────────────────────────
# STEP 5 — Restore pi4_drive from Drive  [USER INPUT: y/n]
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 5/12] Restoring pi4_drive from Google Drive...${NC}"
mkdir -p "$PI4_DRIVE_DIR"

GDRIVE_BACKUP_DIR=""
if rclone lsd gdrive:/pi4_backups &>/dev/null 2>&1; then
    GDRIVE_BACKUP_DIR=$(rclone lsd gdrive:/pi4_backups/ 2>/dev/null | awk '{print $NF}' | grep "pre_reimage_" | sort -r | head -1)
fi

if [ -n "$GDRIVE_BACKUP_DIR" ]; then
    log "${GREEN}  Found backup: gdrive:/pi4_backups/${GDRIVE_BACKUP_DIR}${NC}"
    if ask "  ► Restore from gdrive:/pi4_backups/${GDRIVE_BACKUP_DIR}?"; then
        rclone copy "gdrive:/pi4_backups/${GDRIVE_BACKUP_DIR}/code/pi4_drive" "$PI4_DRIVE_DIR" --progress 2>&1 | tee -a "$LOG_FILE"
        # Restore rclone.conf from Drive backup if not from USB
        [ "$RCLONE_RESTORED" = false ] && \
            rclone copy "gdrive:/pi4_backups/${GDRIVE_BACKUP_DIR}/configs/rclone.conf" /home/pi/.config/rclone/ 2>/dev/null || true
        # Restore crontab
        rclone copy "gdrive:/pi4_backups/${GDRIVE_BACKUP_DIR}/crontab/crontab_pi.txt" /tmp/ 2>/dev/null && \
            crontab /tmp/crontab_pi.txt 2>/dev/null && log "${GREEN}  Crontab restored${NC}" || true
        log "${GREEN}  Backup restored from Google Drive${NC}"
    fi
fi

if rclone lsd gdrive:/pi4_drive &>/dev/null 2>&1; then
    if ask "  ► Also sync gdrive:/pi4_drive → /home/pi/pi4_drive?"; then
        rclone sync gdrive:/pi4_drive "$PI4_DRIVE_DIR" --exclude=".git/**" --exclude=".lgd-nfy0" --progress 2>&1 | tee -a "$LOG_FILE"
        log "${GREEN}  pi4_drive synced from Google Drive${NC}"
    fi
fi

mkdir -p "$PI4_DRIVE_DIR"/{Git_projects,Service_files,shell_scripts,Error_and_Logs,pi4_python_projects,alias_command_file,OS_Migration}
log "${GREEN}  pi4_drive folder structure ready${NC}"

# ─────────────────────────────────────────────
# STEP 6 — Clone RASPI4-MAIN from GitHub
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 6/12] Cloning RASPI4-MAIN from GitHub...${NC}"
if [ ! -d "$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/.git" ]; then
    gh repo clone ${GITHUB_USER}/${REPO_MAIN} "$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN"
    log "${GREEN}  Cloned RASPI4-MAIN${NC}"
else
    git -C "$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN" pull
    log "${GREEN}  RASPI4-MAIN up to date${NC}"
fi

PROJ_DIR="$PI4_DRIVE_DIR/pi4_python_projects/RASPI4-MAIN"
if [ ! -d "$PROJ_DIR" ]; then
    ln -s "$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN" "$PROJ_DIR"
    log "${GREEN}  Symlink: pi4_python_projects/RASPI4-MAIN → Git_projects/RASPI4-MAIN${NC}"
fi

# ─────────────────────────────────────────────
# STEP 7 — Python virtual environment
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 7/12] Python virtual environment (myenv)...${NC}"
python3 -m venv "$MYENV_DIR"
source "$MYENV_DIR/bin/activate"
pip install --upgrade pip -q

MYENV_REQ="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/configs/pip_myenv.txt"
FALLBACK_REQ="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/requirements.txt"

if [ -f "$MYENV_REQ" ]; then
    pip install -r "$MYENV_REQ" 2>&1 | tee -a "$LOG_FILE" || true
    log "${GREEN}  pip packages installed from pip_myenv.txt${NC}"
elif [ -f "$FALLBACK_REQ" ]; then
    pip install -r "$FALLBACK_REQ" 2>&1 | tee -a "$LOG_FILE" || true
    log "${GREEN}  pip packages installed from requirements.txt${NC}"
else
    log "${YELLOW}  No requirements file found — install manually later${NC}"
fi
deactivate

# ─────────────────────────────────────────────
# STEP 8 — InfluxDB 2 arm64
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 8/12] Installing InfluxDB2 (arm64)...${NC}"
INFLUX_VERSION="2.6.1"
INFLUX_PKG="influxdb2-${INFLUX_VERSION}-linux-arm64.tar.gz"

if [ -f "/home/pi/${INFLUX_PKG}" ]; then
    cp "/home/pi/${INFLUX_PKG}" /tmp/
else
    wget -q "https://dl.influxdata.com/influxdb/releases/${INFLUX_PKG}" -O "/tmp/${INFLUX_PKG}"
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
# STEP 9 — Mosquitto MQTT
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 9/12] Configuring Mosquitto MQTT...${NC}"
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
# STEP 10 — Systemd services
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 10/12] Installing systemd services...${NC}"
SERVICES_SRC="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/services"
mkdir -p "$PI4_DRIVE_DIR/Error_and_Logs"

if [ -d "$SERVICES_SRC" ]; then
    sudo cp "$SERVICES_SRC/mybot.service" /etc/systemd/system/
    sudo systemctl enable mybot.service
    log "${GREEN}  [ENABLED + AUTOSTART] mybot.service${NC}"

    sudo cp "$SERVICES_SRC/mqttdatainflux.service" /etc/systemd/system/
    sudo systemctl enable mqttdatainflux.service
    log "${GREEN}  [ENABLED + AUTOSTART] mqttdatainflux.service${NC}"

    sudo cp "$SERVICES_SRC/mybot2.service" /etc/systemd/system/ 2>/dev/null || true
    log "${YELLOW}  [NOT ENABLED] mybot2.service — enable manually if needed${NC}"

    sudo systemctl daemon-reload
else
    log "${RED}  Services folder missing — copy manually${NC}"
fi

# ─────────────────────────────────────────────
# STEP 11 — AWS certs
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 11/12] AWS certs...${NC}"
CERTS_DEST="$PI4_DRIVE_DIR/pi4_python_projects/RASPI4-MAIN/aws_certs"
CERTS_SRC="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/aws_certs"

if [ -d "$CERTS_SRC" ] && [ "$(ls -A $CERTS_SRC 2>/dev/null)" ]; then
    mkdir -p "$CERTS_DEST" && cp -r "$CERTS_SRC/." "$CERTS_DEST/"
    log "${GREEN}  AWS certs from GitHub repo${NC}"
elif [ -n "$GDRIVE_BACKUP_DIR" ]; then
    mkdir -p "$CERTS_DEST"
    rclone copy "gdrive:/pi4_backups/${GDRIVE_BACKUP_DIR}/aws_certs" "$CERTS_DEST" 2>/dev/null && \
        log "${GREEN}  AWS certs from Drive backup${NC}" || true
fi

if [ -z "$(ls -A $CERTS_DEST 2>/dev/null)" ]; then
    log "${RED}  AWS certs missing — mqttdatainflux will fail until restored${NC}"
    log "${YELLOW}  Fix: cp -r /path/to/aws_certs/ $CERTS_DEST/${NC}"
fi

# ─────────────────────────────────────────────
# STEP 12 — .bashrc & aliases
# ─────────────────────────────────────────────
log ""
log "${BLUE}[STEP 12/12] Restoring .bashrc & aliases...${NC}"
BASHRC_BACKUP="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/configs/bashrc.txt"
ALIASES_BACKUP="$PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/configs/.bash_aliases"

[ -f "$BASHRC_BACKUP" ]  && cp "$BASHRC_BACKUP"  /home/pi/.bashrc       && log "${GREEN}  .bashrc restored${NC}"
[ -f "$ALIASES_BACKUP" ] && cp "$ALIASES_BACKUP" /home/pi/.bash_aliases  && log "${GREEN}  .bash_aliases restored${NC}"

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
log "${CYAN}Installed versions:${NC}"
log "  Claude CLI  → $(claude --version 2>/dev/null | head -1)"
log "  Node.js     → $(node --version 2>/dev/null)"
log "  Python      → $(python3 --version 2>/dev/null)"
log "  InfluxDB    → $(influx version 2>/dev/null | head -1)"
log ""
log "${CYAN}Service autostart:${NC}"
log "  mybot.service          → ENABLED"
log "  mqttdatainflux.service → ENABLED (needs AWS certs)"
log "  mosquitto              → ENABLED"
log "  influxdb               → ENABLED"
log "  ssh                    → ENABLED"
log ""
log "${YELLOW}Next steps:${NC}"
log "  1. Start services:  sudo systemctl start mybot.service mqttdatainflux.service"
log "  2. Verify setup:    bash $PI4_DRIVE_DIR/Git_projects/RASPI4-MAIN/OS_Migration/scripts/3_verify_setup.sh"
log "  3. Reload aliases:  source ~/.bashrc"
log ""
log "${MAGENTA}★━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━★${NC}"
log "${MAGENTA}  Claude CLI is ready — run: claude${NC}"
log "${MAGENTA}  Login with your Anthropic account${NC}"
log "${MAGENTA}  Claude will help with anything from here!${NC}"
log "${MAGENTA}★━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━★${NC}"
log ""
