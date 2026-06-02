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
| Mosquitto broker | `192.168.1.108:1883` (Pi5 direct) |

All ESP device IPs and MQTT topics are identical to Pi4 — both Pis control the same
relays and sensors; only one holds the Keepalived VIP and actively receives ESP
MQTT connections at a time.

> **Note (2026-06-01):** `mybot.service` environment variable `MQTT_HOST` changed from
> `192.168.1.100` (shared Keepalived VIP, held by Pi4) to `192.168.1.108` (Pi5 direct IP).
> Pi5 is now always its own MQTT broker regardless of which Pi holds the VIP.
> ESP32-RADAR firmware `HardwareConfig.h` `MQTT_BROKER` also points to `192.168.1.108`
> so both sides use Pi5's broker directly.

### Telegram Bot

| Item | Value |
|---|---|
| Bot username | `@raspi22bot` |
| Bot ID | `6525932255` |
| Chat ID | `5820747117` |
| Account name | `Raspi-5` |

Token and chat ID are set as defaults in `config.py` (`TelegramConfig`) and can be
overridden via `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` environment variables.

### Key Paths (on Pi5)

| Path | Purpose |
|---|---|
| `/home/pi5/myenv/` | Python virtual environment |
| `/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/` | Main project (GitHub) |
| `/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/logs/` | Service logs |

---

## Running the Service

```bash
# Start / restart
sudo systemctl restart mybot.service

# Live log
journalctl -u mybot.service -f

# Run manually (debug)
cd /home/pi5/pi5_drive/Git_projects/RASPI5-MAIN
source /home/pi5/myenv/bin/activate
python3 main.py
```

---

## Dual-Pi Hub Architecture

Both Pi4 (`192.168.1.122`) and Pi5 (`192.168.1.108`) run `keepalived` VRRP.
The virtual IP `192.168.1.100` floats between them automatically based on `mybot.service` health.

```
Pi4 (192.168.1.122) MASTER ─┐
                             ├── Keepalived VRRP ──► Hub IP 192.168.1.100
Pi5 (192.168.1.108) BACKUP ─┘                         │
                                                       └── Mosquitto broker
                                                           ESP devices connect here
```

**Priority:**
- Pi4 = 101 (MASTER), Pi5 = 100 (BACKUP)
- Pi4 runs `check_mybot` health-check every 2 s — if `mybot.service` stops, Pi4 priority drops 101 → 81
- Pi5 at 100 wins the election and claims the VIP within ~4 s
- Pi4 reclaims VIP automatically when its `mybot.service` restarts (priority rises back to 101)

**Auto start/stop via notify scripts (both Pis):**
- `notify_master` → `systemctl start mybot.service` (fired when VIP is gained)
- `notify_backup` → `systemctl stop mybot.service` (fired when VIP is lost)
- Only one Pi runs `mybot.service` at a time — no Telegram polling conflicts

**Failover triggers:**
- Pi4 `mybot.service` stops → Pi5 takes over in ~4 s
- Pi4 goes completely offline → Pi5 takes over in ~3 s

**Config:** `OS_Migration_PI5/keepalived/keepalived.conf` — deploy to `/etc/keepalived/keepalived.conf` on Pi5. Pi4 config in `RASPI4-MAIN/OS_Migration/keepalived/keepalived.conf`.

```bash
# Check which Pi holds VIP
ip addr show wlan0 | grep 192.168.1.100

# Check keepalived state and priority
sudo journalctl -u keepalived -n 20
```

### VIP Handoff Commands (from `.bash_aliases`)

Run these from **Pi5** to transfer the active MASTER role between Pis. Both commands first print current status and ask for confirmation before acting.

| Command | Action |
|---|---|
| `makepi5master` | Stop Pi4 services → start Pi5 services → Pi5 claims the VIP |
| `makepi4master` | Stop Pi5 services → start Pi4 services → Pi4 claims the VIP |

```bash
# Transfer VIP to Pi5 (run from Pi5)
makepi5master

# Transfer VIP to Pi4 (run from Pi5)
makepi4master
```

Both commands call `_pi_status` first, show which Pi currently holds the VIP, and abort if the target is already MASTER.

---

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| Porch/living-room light keeps toggling on by itself after user turns it off | Radar or LD2420 motion is still active while user manually turns light OFF — motion was firing auto-ON again; fixed in 2026-05-18: `_porch_manual_off_time` / `_living_room_manual_off_time` timestamps block auto-ON for 2 minutes after a manual OFF via app |
| Motion auto-ON takes 2–4 minutes to re-enable after manually toggling a light | Manual OFF sets the 2-min block timer but turning ON never cleared it; each OFF→ON→OFF cycle was resetting the timer to a fresh 2 minutes; fixed in 2026-05-20: `_execute_light_cmd` / `_execute_porch_cmd` now reset `_*_manual_off_time = 0` on explicit ON |
| Light switch in app does nothing | Check Firebase SSE streams started in log; check MQTT bridge connected to `192.168.1.108:1883` |
| Porch light not turning on at night | Check radar MQTT arriving (`home/esp32/radar2/motion`); check night hours 18–06; check `_porch_light_on` state |
| Radar motion detected but no video recorded | Check `is_video_recording_enabled()` via bot; check camera initialised in log; confirm ESP32-RADAR MQTT broker is `192.168.1.108` (not `192.168.1.100`) |
| Pi5 not receiving any ESP32 MQTT messages | ESP32-RADAR may still be pointing at Pi4's broker (`192.168.1.100`) — reflash ESP32-RADAR firmware after updating `MQTT_BROKER` in `HardwareConfig.h` to `192.168.1.108` |
| App bulb shows permanent pending spinner when light triggered by motion or timer | `state` and `confirmed` out of sync — `_on_lobby_mqtt_state` / `_on_porch_mqtt_state` / `_on_lp_rly_mqtt_state` write both `confirmed` and `state` to Firebase; check that MQTT state callbacks are firing in the log |
| App shows orange / VIP unreachable after toggling local routing off then back on | `LocalApiServer` thread was blocked by a half-open TCP connection (Flutter app timed out at 2 s while the Pi's socket stayed open, causing `rfile.readline()` to block forever — accept queue fills, `/ping` never responds). Fixed in 2026-05-22: switched to `ThreadingHTTPServer`. If seen on older build, `sudo systemctl restart mybot.service` clears it immediately. |
| Duplicate door events in Firebase (`door_events` collection has two docs per open/close) | Pi5 reed switch callbacks were registered but GPIO 26 has no physical hardware — EMI from the 24 GHz radar triggered phantom events that published to `REED_DOOR/1` in parallel with Pi4. Fixed 2026-05-24: reed callbacks and `AwsIoTPublisher` disabled at startup on Pi5. |
| `mybot.service` crash-looping | Check `logs/error_log.txt`; check GPIO conflicts; check sensor hardware connected |
| Scheduled timer not firing | Check `LightScheduler started` in log; verify `enabled=true` and valid HH:MM times in Firebase `/schedules/`; check Pi clock (`date` command) |
| Both Pi4 and Pi5 running but only one responds to light commands | Only the Pi holding the Keepalived VIP receives ESP MQTT connections — check `ip addr show wlan0 \| grep 192.168.1.100` on each Pi |

---

## Changelog

| Date | Change |
|---|---|
| 2026-06-02 | Keepalived failover redesign — Pi4 is fixed MASTER (priority 101), Pi5 is BACKUP (priority 100); removed `nopreempt` from Pi5 so it preempts Pi4 when Pi4's priority drops to 81; added `notify_master`/`notify_backup` scripts on both Pis to auto-start/stop `mybot.service` on VIP gain/loss; only one bot runs at a time; Pi4 reclaims automatically when its mybot recovers. Tested end-to-end: failover in ~4 s, handback in ~7 s. |
| 2026-06-01 | Add `/test_cam` bot command — publishes `TRIGGER` to `home/esp32/radar2/cmd` via MQTT; ESP32-RADAR receives it, simulates motion ON for 5 s then OFF; Pi5 records video and sends MP4 to Telegram bot. Full chain test without needing physical motion. |
| 2026-06-01 | `mybot.service` `MQTT_HOST` env var changed from `192.168.1.100` (shared Keepalived VIP held by Pi4) to `192.168.1.108` (Pi5 direct IP). Pi5 was receiving no ESP32-RADAR MQTT messages because Pi4 holds the VIP and owns that broker. Pi5 is now always its own broker. |
| 2026-06-01 | Add `RecordingResult.manual` flag to `video_recorder.py` — manual recordings (`/record_video`, `/test_cam`) always send the MP4 to Telegram regardless of the `bot_video_enabled` toggle; motion-triggered recordings still respect the toggle. |
| 2026-06-01 | Add `/record_video <sec>` to Telegram command menu (`get_commands_list`); add `/record_video` to `/display_commands` help text. |
| 2026-06-01 | ESP32-RADAR motion now triggers Pi5 video recording and Telegram video send — `_on_radar_motion()` in `main.py` extended: `motion=ON` starts picamera2 recording (if video recording enabled via bot) and sends throttled Telegram text alert; `motion=OFF` schedules `_check_stop_recording` after `motion_timeout` delay via `_radar_rec_stop_timer`; `_on_recording_complete` sends the MP4 to Telegram. |
| 2026-05-24 | Disable reed switch callbacks and AWS IoT door publisher — Pi5 has no physical reed switch on GPIO 26; the pull-up pin was picking up EMI from the nearby 24 GHz radar, firing phantom door open/close events that published duplicate `REED_DOOR/1` MQTT messages to AWS IoT and created extra Firestore `door_events` documents alongside Pi4's writes. Reed callbacks and `AwsIoTPublisher` are now skipped at startup; `aws_door` remains `None` for the lifetime of the process. |
| 2026-05-22 | Sync with Pi4: add `aws_iot_publisher.py` (Pi5 variant — `RaspberryPi5-DoorPublisher`, cert path `/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/aws_certs`); wire into `main.py` door open/close callbacks and cleanup; fix `config.py` InfluxDB org/bucket `pi4org/pi4data` → `pi5org/pi5data`; fix `bot_commands.py` `read_reed_switch()` → `read_reed()` (method name was wrong — same bug fixed in Pi4 same day) |
| 2026-05-22 | Fix `LocalApiServer` hang — single-threaded `HTTPServer` blocked the entire accept loop when the Flutter app established a TCP connection but timed out mid-request (2 s client timeout left a half-open socket; Pi's `rfile.readline()` blocked indefinitely, filling the kernel accept queue; `/ping` appeared unreachable → app stayed orange even when Pi5 held the VRRP VIP). Fixed in `local_api_server.py` by replacing `HTTPServer` with `_ThreadingHTTPServer` (`ThreadingMixIn + HTTPServer`, `daemon_threads=True`). Same fix as RASPI4-MAIN commit `31fe337`. |
| 2026-05-20 | Fix motion auto-ON re-enable delay (2–4 min) after manually toggling a light from the app — `_living_room_manual_off_time` and `_porch_manual_off_time` were set on every manual OFF but never cleared when the user turned the light back ON; each OFF→ON→OFF cycle reset the timer to a fresh 2 minutes; fixed in `_execute_light_cmd` and `_execute_porch_cmd` by adding `elif cmd: _*_manual_off_time = 0` so an explicit ON immediately clears the override |
| 2026-05-18 | Fix light auto-toggle loop — when user manually turns OFF a porch or living-room light while motion is still active, the radar (`_on_radar_motion`) and LD2420 loop (`_trigger_light_control`) were immediately overriding the user's intent and turning it back ON; added `_porch_manual_off_time` and `_living_room_manual_off_time` timestamps recorded in `_execute_porch_cmd` / `_execute_light_cmd` on every manual OFF; both auto-ON paths check these timestamps and skip re-activation for 120 seconds after a manual OFF; normal automatic behaviour resumes after 2 minutes |
| 2026-05-18 | Add local HTTP API server (`local_api_server.py`, port 5757) — LAN fallback for light control when Firebase/internet is down; `PUT /lights/{id}` routes directly to relay execute methods; Pi deduplicates if both paths deliver |
| 2026-05-18 | Fix pending spinner on app bulb when light triggered by motion or scheduler — MQTT state callbacks now write both `lights/{id}/state` and `confirmed` to Firebase; `_last_*_cmd` dedup flag set before Firebase write to prevent SSE feedback loop |
| 2026-05-17 | Add Firebase-backed scheduled on/off timers for all three lights — `light_scheduler.py` (APScheduler cron wrapper); `firebase_logger.py` `get_schedules()` + `start_schedule_stream()` SSE watcher |
| 2026-05-17 | Add Keepalived VRRP dual-Pi hub IP — Pi4 and Pi5 share VIP `192.168.1.100`; `mybot.service` sets `MQTT_HOST=192.168.1.100` |
| 2026-05-17 | Add ESP32-LP-RLY (L-Porch-Light) full integration — MQTT state/availability/OTA; Firebase SSE stream on `lower_porch_light` with 400 ms debounce |
| 2026-05-14 | Initial Pi5 port — identical feature set to RASPI4-MAIN; device ID `RASPI-5`; MQTT client ID `raspi5-bridge` |
