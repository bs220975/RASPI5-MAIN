#!/bin/bash
# On boot, connect to the saved WiFi network with the strongest signal.

logger -t wifi-best-signal "Starting best-signal WiFi selection"

# Wait for wlan0 to be managed
for i in $(seq 1 10); do
    STATE=$(nmcli -g GENERAL.STATE device show wlan0 2>/dev/null)
    [[ "$STATE" != "" ]] && break
    sleep 2
done

# Force a fresh scan
nmcli device wifi rescan ifname wlan0 2>/dev/null
sleep 4

# Build list of saved WiFi connections and their SSIDs
declare -A CONN_SSID
while IFS=: read -r name type; do
    [[ "$type" == "802-11-wireless" ]] || continue
    ssid=$(nmcli -g 802-11-wireless.ssid connection show "$name" 2>/dev/null)
    [[ -n "$ssid" ]] && CONN_SSID["$name"]="$ssid"
done < <(nmcli -t -f name,type connection show)

if [[ ${#CONN_SSID[@]} -eq 0 ]]; then
    logger -t wifi-best-signal "No saved WiFi connections found"
    exit 0
fi

# Find the saved connection with the best visible signal
BEST_CONN=""
BEST_SIGNAL=-999

for conn in "${!CONN_SSID[@]}"; do
    ssid="${CONN_SSID[$conn]}"
    # Get highest signal for this SSID (may have multiple BSSIDs)
    signal=$(nmcli -t -f SSID,SIGNAL device wifi list ifname wlan0 2>/dev/null \
        | awk -F: -v s="$ssid" '$1==s {print $2}' \
        | sort -n | tail -1)
    [[ -z "$signal" ]] && continue
    logger -t wifi-best-signal "Saved '$conn' (SSID: $ssid) signal: $signal"
    if (( signal > BEST_SIGNAL )); then
        BEST_SIGNAL=$signal
        BEST_CONN=$conn
    fi
done

if [[ -z "$BEST_CONN" ]]; then
    logger -t wifi-best-signal "No saved networks visible in scan"
    exit 0
fi

CURRENT_CONN=$(nmcli -g GENERAL.CONNECTION device show wlan0 2>/dev/null)

logger -t wifi-best-signal "Best: '$BEST_CONN' (signal $BEST_SIGNAL), Current: '$CURRENT_CONN'"

if [[ "$BEST_CONN" == "$CURRENT_CONN" ]]; then
    logger -t wifi-best-signal "Already on best network, no switch needed"
    exit 0
fi

logger -t wifi-best-signal "Switching to '$BEST_CONN'"
nmcli connection up "$BEST_CONN" ifname wlan0
