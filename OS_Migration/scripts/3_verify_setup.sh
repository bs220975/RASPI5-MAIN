#!/bin/bash
# =============================================================
# POST-INSTALL VERIFICATION SCRIPT
# Run after 2_post_install_setup.sh to check everything works
# =============================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0

check() {
    local label="$1"
    local cmd="$2"
    if eval "$cmd" &>/dev/null; then
        echo -e "  ${GREEN}[PASS]${NC} $label"
        PASS=$((PASS+1))
    else
        echo -e "  ${RED}[FAIL]${NC} $label"
        FAIL=$((FAIL+1))
    fi
}

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}   Pi4 64-bit Setup Verification${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Architecture
echo -e "${CYAN}--- System ---${NC}"
ARCH=$(uname -m)
BITS=$(getconf LONG_BIT)
echo "  Kernel: $(uname -r)"
echo "  Arch:   $ARCH | ${BITS}-bit userland"
[ "$BITS" = "64" ] && echo -e "  ${GREEN}[PASS]${NC} 64-bit OS confirmed" || echo -e "  ${RED}[FAIL]${NC} Not 64-bit!"
echo ""

# Services
echo -e "${CYAN}--- Services (enabled + autostart) ---${NC}"
# Standard services
check "SSH enabled & running"        "systemctl is-active --quiet ssh"
check "Mosquitto enabled"            "systemctl is-enabled --quiet mosquitto"
check "Mosquitto running"            "systemctl is-active --quiet mosquitto"
check "InfluxDB enabled"             "systemctl is-enabled --quiet influxdb"
check "InfluxDB running"             "systemctl is-active --quiet influxdb"
check "cron enabled"                 "systemctl is-enabled --quiet cron"
# Custom services
check "mybot enabled (autostart)"    "systemctl is-enabled --quiet mybot.service"
check "mybot running"                "systemctl is-active --quiet mybot.service"
check "mqttdatainflux enabled"       "systemctl is-enabled --quiet mqttdatainflux.service"
check "mqttdatainflux running"       "systemctl is-active --quiet mqttdatainflux.service"
# Log folder
check "logs folder exists"           "[ -d /home/pi/pi4_drive/Git_projects/RASPI4-MAIN/logs ]"
# Script paths the services depend on
check "mybot script exists"          "[ -f /home/pi/pi4_drive/Git_projects/RASPI4-MAIN/main.py ]"
check "influx script exists"         "[ -f /home/pi/pi4_drive/Git_projects/RASPI4-MAIN/influx_aws_publish/influxdb2_aws_publish.py ]"
echo ""

# Python
echo -e "${CYAN}--- Python ---${NC}"
check "python3 exists"          "command -v python3"
check "myenv exists"            "[ -d /home/pi/myenv ]"
check "pip in myenv"            "[ -f /home/pi/myenv/bin/pip ]"
check "paho-mqtt installed"     "source /home/pi/myenv/bin/activate && python -c 'import paho.mqtt.client'"
check "influxdb_client installed" "source /home/pi/myenv/bin/activate && python -c 'import influxdb_client'"
check "telepot installed"       "source /home/pi/myenv/bin/activate && python -c 'import telepot'"
echo ""

# Tools
echo -e "${CYAN}--- Tools ---${NC}"
check "git installed"           "command -v git"
check "gh CLI installed"        "command -v gh"
check "rclone installed"        "command -v rclone"
check "influx CLI installed"    "command -v influx"
check "mosquitto_pub available" "command -v mosquitto_pub"
check "node.js installed"       "command -v node"
check "Claude CLI installed"    "command -v claude"
echo ""

# Connectivity
echo -e "${CYAN}--- Connectivity ---${NC}"
check "MQTT test pub/sub"       "mosquitto_pub -h localhost -t test/verify -m ok -u mq -P mq"
check "InfluxDB HTTP"           "curl -sf http://localhost:8086/health"
check "Internet"                "curl -sf --max-time 5 https://github.com"
echo ""

# AWS certs
echo -e "${CYAN}--- AWS Certs ---${NC}"
CERT_DIR="/home/pi/pi4_drive/Git_projects/RASPI4-MAIN/aws_certs"
check "aws_certs dir exists"    "[ -d '$CERT_DIR' ]"
check "cert .pem file exists"   "ls '$CERT_DIR'/*.pem &>/dev/null"
echo ""

# Summary
echo -e "${CYAN}============================================${NC}"
echo -e "  ${GREEN}PASSED: $PASS${NC}  |  ${RED}FAILED: $FAIL${NC}"
echo -e "${CYAN}============================================${NC}"

if [ $FAIL -gt 0 ]; then
    echo -e "${YELLOW}Check the failed items above before starting services.${NC}"
else
    echo -e "${GREEN}All checks passed! You can start your services:${NC}"
    echo "  sudo systemctl start mybot.service"
    echo "  sudo systemctl start mqttdatainflux.service"
fi
echo ""
