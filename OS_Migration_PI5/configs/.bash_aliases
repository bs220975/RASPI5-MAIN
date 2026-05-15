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
