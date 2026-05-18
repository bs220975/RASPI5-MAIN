# RASPI5-MAIN

Raspberry Pi 5 home automation bridge. Runs as a systemd service (`mybot.service`)
and coordinates local sensors, ESP IoT devices, Firebase RTDB, Telegram, and InfluxDB.
Functionally identical to [RASPI4-MAIN](https://github.com/bs220975/RASPI4-MAIN) —
refer to that README for full architecture, MQTT topics, Firebase paths, module
reference, and troubleshooting. This file documents Pi5-specific details and changes.

> For OS setup, reimaging, service files, aliases, and Google Drive backup see
> [`OS_Migration/OS_Migration_help.md`](OS_Migration/OS_Migration_help.md) in RASPI4-MAIN.

---

## Contents

- [Pi5-Specific Configuration](#pi5-specific-configuration)
- [Running the Service](#running-the-service)
- [Dual-Pi Hub Architecture](#dual-pi-hub-architecture)
- [Troubleshooting](#troubleshooting)
- [Changelog](#changelog)

---

## Pi5-Specific Configuration

| Item | Value |
|---|---|
| Pi 5 LAN IP | `192.168.1.108` |
| Pi 4 LAN IP | `192.168.1.122` |
| Hub VIP (Keepalived) | `192.168.1.100` |
| Device ID in Firebase | `RASPI-5` |
| MQTT client ID | `raspi5-bridge` (set in `config.py`) |
| Local API port | `5757` |
| Mosquitto broker | hub VIP `192.168.1.100:1883` |

All ESP device IPs and MQTT topics are identical to Pi4 — both Pis control the same
relays and sensors; only one holds the Keepalived VIP and actively receives ESP
MQTT connections at a time.

### Key Paths (on Pi5)

| Path | Purpose |
|---|---|
| `/home/pi/myenv/` | Python virtual environment |
| `/home/pi/pi5_drive/Git_projects/RASPI5-MAIN/` | Main project (GitHub) |
| `/home/pi/pi5_drive/Git_projects/RASPI5-MAIN/logs/` | Service logs |

---

## Running the Service

```bash
# Start / restart
sudo systemctl restart mybot.service

# Live log
journalctl -u mybot.service -f

# Run manually (debug)
cd /home/pi/pi5_drive/Git_projects/RASPI5-MAIN
source /home/pi/myenv/bin/activate
python3 main.py
```

---

## Dual-Pi Hub Architecture

Both Pi4 (`192.168.1.122`) and Pi5 (`192.168.1.108`) run `keepalived` VRRP.
The virtual IP `192.168.1.100` floats between them — whichever starts first claims MASTER.

```
Pi4 (192.168.1.122)  ─┐
                       ├── Keepalived VRRP ──► Hub IP 192.168.1.100
Pi5 (192.168.1.108)  ─┘                         │
                                                 └── Mosquitto broker
                                                     ESP devices connect here
```

- Both Pis start as `BACKUP` (`nopreempt`). First to advertise becomes MASTER.
- VIP migrates to the standby Pi within ~3 s if the MASTER's Keepalived stops.
- `nopreempt` — recovered Pi rejoins as BACKUP; does not reclaim VIP automatically.

---

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| Porch/living-room light keeps toggling on by itself after user turns it off | Radar or LD2420 motion is still active while user manually turns light OFF — motion was firing auto-ON again; fixed in 2026-05-18: `_porch_manual_off_time` / `_living_room_manual_off_time` timestamps block auto-ON for 2 minutes after a manual OFF via app |
| Light switch in app does nothing | Check Firebase SSE streams started in log; check MQTT bridge connected to `192.168.1.100:1883` |
| Porch light not turning on at night | Check radar MQTT arriving (`home/esp32/radar2/motion`); check night hours 18–06; check `_porch_light_on` state |
| App bulb shows permanent pending spinner when light triggered by motion or timer | `state` and `confirmed` out of sync — `_on_lobby_mqtt_state` / `_on_porch_mqtt_state` / `_on_lp_rly_mqtt_state` write both `confirmed` and `state` to Firebase; check that MQTT state callbacks are firing in the log |
| `mybot.service` crash-looping | Check `logs/error_log.txt`; check GPIO conflicts; check sensor hardware connected |
| Scheduled timer not firing | Check `LightScheduler started` in log; verify `enabled=true` and valid HH:MM times in Firebase `/schedules/`; check Pi clock (`date` command) |
| Both Pi4 and Pi5 running but only one responds to light commands | Only the Pi holding the Keepalived VIP receives ESP MQTT connections — check `ip addr show wlan0 \| grep 192.168.1.100` on each Pi |

---

## Changelog

| Date | Change |
|---|---|
| 2026-05-18 | Fix light auto-toggle loop — when user manually turns OFF a porch or living-room light while motion is still active, the radar (`_on_radar_motion`) and LD2420 loop (`_trigger_light_control`) were immediately overriding the user's intent and turning it back ON; added `_porch_manual_off_time` and `_living_room_manual_off_time` timestamps recorded in `_execute_porch_cmd` / `_execute_light_cmd` on every manual OFF; both auto-ON paths check these timestamps and skip re-activation for 120 seconds after a manual OFF; normal automatic behaviour resumes after 2 minutes |
| 2026-05-18 | Add local HTTP API server (`local_api_server.py`, port 5757) — LAN fallback for light control when Firebase/internet is down; `PUT /lights/{id}` routes directly to relay execute methods; Pi deduplicates if both paths deliver |
| 2026-05-18 | Fix pending spinner on app bulb when light triggered by motion or scheduler — MQTT state callbacks now write both `lights/{id}/state` and `confirmed` to Firebase; `_last_*_cmd` dedup flag set before Firebase write to prevent SSE feedback loop |
| 2026-05-17 | Add Firebase-backed scheduled on/off timers for all three lights — `light_scheduler.py` (APScheduler cron wrapper); `firebase_logger.py` `get_schedules()` + `start_schedule_stream()` SSE watcher |
| 2026-05-17 | Add Keepalived VRRP dual-Pi hub IP — Pi4 and Pi5 share VIP `192.168.1.100`; `mybot.service` sets `MQTT_HOST=192.168.1.100` |
| 2026-05-17 | Add ESP32-LP-RLY (L-Porch-Light) full integration — MQTT state/availability/OTA; Firebase SSE stream on `lower_porch_light` with 400 ms debounce |
| 2026-05-14 | Initial Pi5 port — identical feature set to RASPI4-MAIN; device ID `RASPI-5`; MQTT client ID `raspi5-bridge` |
