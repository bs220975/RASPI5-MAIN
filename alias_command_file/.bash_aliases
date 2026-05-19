# ─────────────────────────────────────────
# Pi5 Custom Aliases
# Backed up to: pi5_drive/alias_command_file/.bash_aliases
#               OS_Migration_PI5/configs/.bash_aliases (GitHub)
# ─────────────────────────────────────────

# --- General ---
alias scr='sudo crontab -e'
alias cr='crontab -e'
alias codestatus='ps axww | grep "python"'
alias myenv='source /home/pi5/myenv/bin/activate'

# --- Sync & Backup ---
alias sync='/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/shell_scripts/sync.sh'
alias backup='/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/shell_scripts/backup.sh'
alias copyalias="cp /home/pi5/.bash_aliases /home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/alias_command_file/.bash_aliases"

# --- Navigation ---
alias cdmain='cd /home/pi5/pi5_drive/Git_projects/RASPI5-MAIN'
alias cdapp='cd /home/pi5/pi5_drive/Git_projects/HOMESECURITY-APP'

# --- mybot service ---
alias stopmybot='sudo systemctl stop mybot.service'
alias startmybot='sudo systemctl start mybot.service'
alias restartmybot='sudo systemctl restart mybot.service'
alias statusmybot='sudo systemctl status mybot.service'
alias enablemybot='sudo systemctl enable mybot.service'
alias reloadmybot='sudo systemctl daemon-reload'
alias copymybot='sudo cp /home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/OS_Migration_PI5/services/mybot.service /etc/systemd/system/'
alias servicemybot='sudo journalctl -f -u mybot.service'

# --- mybot2 service ---
alias stopmybot2='sudo systemctl stop mybot2.service'
alias startmybot2='sudo systemctl start mybot2.service'
alias restartmybot2='sudo systemctl restart mybot2.service'
alias statusmybot2='sudo systemctl status mybot2.service'
alias enablemybot2='sudo systemctl enable mybot2.service'
alias reloadmybot2='sudo systemctl daemon-reload'
alias copymybot2='sudo cp /home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/OS_Migration_PI5/services/mybot2.service /etc/systemd/system/'
alias servicemybot2='sudo journalctl -f -u mybot2.service'

# --- mqttdatainflux service ---
alias stopmqtt='sudo systemctl stop mqttdatainflux.service'
alias startmqtt='sudo systemctl start mqttdatainflux.service'
alias restartmqtt='sudo systemctl restart mqttdatainflux.service'
alias statusmqtt='sudo systemctl status mqttdatainflux.service'
alias enablemqtt='sudo systemctl enable mqttdatainflux.service'
alias reloadmqtt='sudo systemctl daemon-reload'
alias copymqtt='sudo cp /home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/OS_Migration_PI5/services/mqttdatainflux.service /etc/systemd/system/'
alias servicemqtt='sudo journalctl -f -u mqttdatainflux.service'

# --- Pi4 SSH (192.168.1.122, user: pi, pass: 22) ---
alias sshpi4='sshpass -p 22 ssh -o StrictHostKeyChecking=no pi@192.168.1.122'
pi4startall() { sshpass -p 22 ssh -o StrictHostKeyChecking=no pi@192.168.1.122 "source ~/.bash_aliases && startall $*"; }
pi4stopall()  { sshpass -p 22 ssh -o StrictHostKeyChecking=no pi@192.168.1.122 "source ~/.bash_aliases && stopall"; }
pi4statusall(){ sshpass -p 22 ssh -o StrictHostKeyChecking=no pi@192.168.1.122 "source ~/.bash_aliases && statusall"; }

# --- keepalived (virtual IP 192.168.1.100) ---
alias stopkeepalived='sudo systemctl stop keepalived'
alias startkeepalived='sudo systemctl start keepalived'
alias restartkeepalived='sudo systemctl restart keepalived'
alias statuskeepalived='sudo systemctl status keepalived'

# --- VIP Handoff (work from either Pi) ---
_pi_status() {
    local pi5_vip pi4_vip pi5_ka pi5_bot pi4_ka pi4_bot pi5_role pi4_role
    ip addr show wlan0 2>/dev/null | grep -q "192.168.1.100" && pi5_vip=1 || pi5_vip=0
    pi4_vip=$(sshpass -p 22 ssh -n -o StrictHostKeyChecking=no -o ConnectTimeout=3 pi@192.168.1.122 \
        "ip addr show wlan0 2>/dev/null | grep -q 192.168.1.100 && echo 1 || echo 0" 2>/dev/null || echo 0)
    pi5_ka=$(systemctl is-active keepalived 2>/dev/null; true)
    pi5_bot=$(systemctl is-active mybot.service 2>/dev/null; true)
    pi4_ka=$(sshpass -p 22 ssh -n -o StrictHostKeyChecking=no pi@192.168.1.122 \
        "systemctl is-active keepalived; true" 2>/dev/null || echo "---")
    pi4_bot=$(sshpass -p 22 ssh -n -o StrictHostKeyChecking=no pi@192.168.1.122 \
        "systemctl is-active mybot.service; true" 2>/dev/null || echo "---")
    [ "$pi5_vip" -gt 0 ] && pi5_role="MASTER" || pi5_role="BACKUP"
    [ "$pi4_vip" -gt 0 ] && pi4_role="MASTER" || pi4_role="BACKUP"
    echo ""
    echo "  === Current Status ==="
    printf "  Pi5 (192.168.1.108): %-6s | keepalived: %-8s | mybot: %s\n" "$pi5_role" "$pi5_ka" "$pi5_bot"
    printf "  Pi4 (192.168.1.122): %-6s | keepalived: %-8s | mybot: %s\n" "$pi4_role" "$pi4_ka" "$pi4_bot"
    echo ""
    # export for caller
    _PI5_VIP=$pi5_vip; _PI4_VIP=$pi4_vip
}

makepi4master() {
    _pi_status
    if [ "$_PI4_VIP" -gt 0 ]; then
        echo "  [INFO] Pi4 is already MASTER — nothing to do."
        return 0
    fi
    echo "  Action: Stop Pi5 services → Hand VIP to Pi4"
    read -rp "  Proceed? [y/N]: " confirm
    [[ "$confirm" =~ ^[yY] ]] || { echo "  Aborted."; return 1; }
    echo "  [1/2] Stopping services on Pi5..."
    stopall || true
    sleep 3
    echo "  [2/2] Starting services on Pi4..."
    sshpass -p 22 ssh -o StrictHostKeyChecking=no pi@192.168.1.122 "source ~/.bash_aliases && startall --force"
}

makepi5master() {
    _pi_status
    if [ "$_PI5_VIP" -gt 0 ]; then
        echo "  [INFO] Pi5 is already MASTER — nothing to do."
        return 0
    fi
    echo "  Action: Stop Pi4 services → Hand VIP to Pi5"
    read -rp "  Proceed? [y/N]: " confirm
    [[ "$confirm" =~ ^[yY] ]] || { echo "  Aborted."; return 1; }
    echo "  [1/2] Stopping services on Pi4..."
    sshpass -p 22 ssh -o StrictHostKeyChecking=no pi@192.168.1.122 "source ~/.bash_aliases && stopall" || true
    sleep 3
    echo "  [2/2] Starting services on Pi5..."
    startall --force
}

# --- All services (keepalived controls 192.168.1.100 VIP) ---
startall() {
    if [ "$1" != "--force" ]; then
        if ip addr show wlan0 2>/dev/null | grep -q "192.168.1.100"; then
            echo "  [Pi5] Already MASTER — VIP 192.168.1.100 is already on this Pi."
            echo "  Run 'statusall' to check service health."
            return 0
        fi
        if ping -c 1 -W 2 192.168.1.100 > /dev/null 2>&1; then
            echo "  [WARNING] VIP 192.168.1.100 is currently held by Pi4 (192.168.1.122)."
            echo "  Pi4 services are active. Starting here puts Pi5 in BACKUP — Pi4 keeps the VIP."
            echo ""
            echo "  To transfer VIP to Pi5:"
            echo "    1. SSH into Pi4:   sshpi4"
            echo "    2. Run there:      stopall"
            echo "    3. Return here:    startall"
            echo ""
            echo "  To start in BACKUP mode anyway:  startall --force"
            return 1
        fi
    fi
    sudo systemctl reset-failed mybot.service mqttdatainflux.service 2>/dev/null
    sudo systemctl start keepalived && \
    sudo systemctl start mybot.service && \
    sudo systemctl start mqttdatainflux.service && \
    echo "  [OK] All services started — VIP 192.168.1.100 is now on Pi5"
}

stopall() {
    if ! systemctl is-active --quiet keepalived; then
        echo "  [Pi5] keepalived is not running — services may already be stopped."
        echo "  Run 'statusall' to confirm current state."
        return 1
    fi
    sudo systemctl stop mybot.service
    sudo systemctl stop mqttdatainflux.service
    sudo systemctl stop keepalived && \
    echo "  [OK] All services stopped — VIP 192.168.1.100 released to Pi4"
}

statusall() {
    echo "=== keepalived ===" && sudo systemctl status keepalived --no-pager -l | tail -5
    echo "=== mybot ===" && sudo systemctl status mybot.service --no-pager -l | tail -5
    echo "=== mqttdatainflux ===" && sudo systemctl status mqttdatainflux.service --no-pager -l | tail -5
}
