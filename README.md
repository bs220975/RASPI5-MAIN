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
- [Two-Floor Sensor & Relay Assignment](#two-floor-sensor--relay-assignment)
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

> **Note (2026-06-03):** `mybot.service` `MQTT_HOST` is `localhost` on both Pis.
> ESP devices still connect to the Keepalived VIP `192.168.1.100`, so only the MASTER
> Pi's broker has ESP clients — Pi5's mybot processes ESP MQTT only when Pi5 holds the VIP.
> Pi5 receives ESP32-RADAR motion events at all times via a mosquitto topic bridge
> (`OS_Migration_PI5/configs/mosquitto-radar-bridge.conf`) so Pi5's camera records
> independently regardless of MASTER/BACKUP state.

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

Both Pi4 (`192.168.1.122`) and Pi5 (`192.168.1.108`) run `keepalived` VRRP and
`mybot.service` simultaneously. The virtual IP `192.168.1.100` floats between them
— only the MASTER Pi's mosquitto broker receives ESP device connections.

```
Pi4 (192.168.1.122) MASTER ─┐
                             ├── Keepalived VRRP ──► Hub IP 192.168.1.100
Pi5 (192.168.1.108) BACKUP ─┘                         │
                                                       └── Mosquitto broker
                                                           ESP devices connect here
```

**Priority:**
- Pi4 = 101 base (MASTER); effective priority drops to 81 when `mybot.service` is inactive (`check_mybot weight -20`)
- Pi5 = 100 (BACKUP) — preempts Pi4 when Pi4's effective priority falls to 81
- Pi4 reclaims VIP automatically once its mybot recovers (priority restored to 101)
- Pi5 takes over when Pi4's keepalived stops, wlan0 goes down, **or mybot.service stops/crashes**

**keepalived is fully decoupled from mybot.service** — no `check_mybot` script,
no `notify_master/backup/fault` hooks. Keepalived manages only the VIP. Both Pis
run `mybot.service` independently under systemd at all times.

**MQTT isolation — no duplication:**
- Both Pis use `MQTT_HOST=localhost`
- When Pi4 is MASTER: ESP devices connect to VIP = Pi4's mosquitto. Pi4's mybot
  receives all ESP messages. Pi5's local mosquitto has no ESP clients → Pi5's mybot
  processes nothing.
- When Pi5 becomes MASTER: ESP devices reconnect to VIP = Pi5's mosquitto. Pi5's
  mybot automatically starts processing — no intervention needed.

**Pi5 radar bridge (always-on camera recording):**
Pi5's mosquitto bridges only the two ESP32-RADAR topics from the VIP broker, so
Pi5's camera records motion events and sends video to Pi5's Telegram regardless of
whether Pi5 is MASTER or BACKUP. Config:
`OS_Migration_PI5/configs/mosquitto-radar-bridge.conf` → deploy to
`/etc/mosquitto/conf.d/radar-bridge.conf` on Pi5.

**Split-brain prevention (Pi5):**
A systemd drop-in (`OS_Migration_PI5/keepalived/keepalived-wait-for-wlan.conf`)
delays Pi5's keepalived startup until wlan0 has its IP and is stable. Without this,
Pi5's wlan0 flaps ~4 s after boot, Pi5 misses Pi4's VRRP adverts, and both Pis
claim MASTER simultaneously. Deploy to
`/etc/systemd/system/keepalived.service.d/wait-for-wlan.conf` on Pi5.

**advert_int = 2 on both Pis** — extends `master_down_interval` to ~6.6 s,
giving extra tolerance for brief WiFi gaps before a BACKUP claims MASTER.

**WiFi power management must be disabled on both Pis:**
```bash
# Persistent — survives reboots (/etc/NetworkManager/conf.d/wifi-powersave-off.conf)
[connection]
wifi.powersave = 2
# Immediate
sudo iw dev wlan0 set power_save off
sudo nmcli con modify <SSID> 802-11-wireless.powersave 2
```

**Config files:**
- Pi5 keepalived: `OS_Migration_PI5/keepalived/keepalived.conf` → `/etc/keepalived/keepalived.conf`
- Pi5 startup delay: `OS_Migration_PI5/keepalived/keepalived-wait-for-wlan.conf` → `/etc/systemd/system/keepalived.service.d/wait-for-wlan.conf`
- Pi5 radar bridge: `OS_Migration_PI5/configs/mosquitto-radar-bridge.conf` → `/etc/mosquitto/conf.d/radar-bridge.conf`
- Pi4 keepalived: `RASPI4-MAIN/OS_Migration/keepalived/keepalived.conf` → `/etc/keepalived/keepalived.conf` on Pi4

```bash
# Check which Pi holds VIP
ip addr show wlan0 | grep 192.168.1.100

# Check keepalived state
sudo journalctl -u keepalived -n 20

# Check radar bridge is connected
sudo journalctl -u mosquitto | grep -i bridge
```

### VIP Handoff Commands (from `.bash_aliases`)

Run these from **Pi5** to transfer the active MASTER role between Pis. Both commands
print current status and ask for confirmation before acting.

| Command | Action |
|---|---|
| `makepi5master` | Stop Pi4 keepalived → Pi5 claims VIP |
| `makepi4master` | Stop Pi5 keepalived → Pi4 claims VIP |

```bash
makepi5master   # Transfer VIP to Pi5 (run from Pi5)
makepi4master   # Transfer VIP to Pi4 (run from Pi5)
```

---

## Two-Floor Sensor & Relay Assignment

> **Reference note (2026-06-02):** The system spans two floors, each with its own Pi,
> radar sensor, and relay-controlled light. The sensor-to-relay wiring is different on
> each floor — this section is the canonical reference for which device does what and why.

### Pi4 — Lower Floor Lobby (RASPI4-MAIN)

| Item | Value |
|---|---|
| Pi | Raspberry Pi 4 |
| IP | `192.168.1.122` |
| GitHub repo | `RASPI4-MAIN` |
| Floor | Lower lobby |
| Radar sensor | **LD2420** wired directly to Pi4 serial port (`/dev/serial0`, 115200 baud) |
| Relay device | **ESP01-LL-RLY** (`192.168.1.85`) — lower lobby light |
| MQTT relay topic | `home/esp01/lower-lobby/cmd/relay` |

**Motion flow (Pi4):**
```
LD2420 (serial /dev/serial0)
  └─► Pi4 reads radar frame in sensors.py
        └─► _process_motion() → _trigger_light_control()
              └─► MQTT ON → ESP01-LL-RLY (192.168.1.85) → lower lobby light ON
```

---

### Pi5 — Upper Floor Lobby (RASPI5-MAIN)

| Item | Value |
|---|---|
| Pi | Raspberry Pi 5 |
| IP | `192.168.1.108` |
| GitHub repo | `RASPI5-MAIN` |
| Floor | Upper lobby |
| Radar sensor | **LD2420** wired to **ESP32-RADAR** (`192.168.1.87`) — NOT directly to Pi5 serial pins |
| Relay device | **ESP01-UL-RLY** (`192.168.1.111`) — upper lobby light |
| MQTT relay topic | `home/esp01/upper-lobby/cmd/relay` |
| MQTT motion topic | `home/esp32/radar2/motion` (published by ESP32-RADAR) |

**Why the radar is on the ESP32, not on Pi5:** The Pi5's `/dev/serial0` is the Bluetooth
UART and cannot be used for the LD2420. The LD2420 is instead wired to the ESP32-RADAR
board which publishes motion state over MQTT.

**All ESP devices use the Keepalived VIP `192.168.1.100` as their MQTT broker.** Whichever
Pi is MASTER holds the VIP and runs `mybot.service`. No firmware changes are needed when
Pi4 ↔ Pi5 failover occurs — all devices reconnect automatically to the same VIP on the
new MASTER.

**Motion flow (Pi5):**
```
LD2420 (wired to ESP32-RADAR at 192.168.1.87)
  └─► ESP32-RADAR publishes home/esp32/radar2/motion = ON
        └─► Pi5 MqttBridge._on_message() → _on_radar_motion()
              ├─► MQTT ON → ESP01-UL-RLY (192.168.1.111) → upper lobby light ON
              └─► MQTT ON → ESP01-LL-RLY (192.168.1.85)  → lower lobby light ON
                  (both lights respect 2-min manual-OFF override independently)
                  (both lights turn OFF 5 min after motion stops)
```

---

### Quick comparison

| | Pi4 (lower lobby) | Pi5 (upper lobby) |
|---|---|---|
| Repo | RASPI4-MAIN | RASPI5-MAIN |
| Radar connection | Direct serial `/dev/serial0` | Via ESP32-RADAR over MQTT |
| Light relay | ESP01-LL-RLY `192.168.1.85` | ESP01-UL-RLY `192.168.1.111` |
| MQTT relay cmd topic | `home/esp01/lower-lobby/cmd/relay` | `home/esp01/upper-lobby/cmd/relay` |
| Night hours for auto-ON | 18:00 – 08:00 | 18:00 – 06:00 |
| Code entry point | `_trigger_light_control()` | `_on_radar_motion()` |

---

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| Porch/living-room light keeps toggling on by itself after user turns it off | Radar or LD2420 motion is still active while user manually turns light OFF — motion was firing auto-ON again; fixed in 2026-05-18: `_porch_manual_off_time` / `_living_room_manual_off_time` timestamps block auto-ON for 2 minutes after a manual OFF via app |
| Motion auto-ON takes 2–4 minutes to re-enable after manually toggling a light | Manual OFF sets the 2-min block timer but turning ON never cleared it; each OFF→ON→OFF cycle was resetting the timer to a fresh 2 minutes; fixed in 2026-05-20: `_execute_light_cmd` / `_execute_porch_cmd` now reset `_*_manual_off_time = 0` on explicit ON |
| Light switch in app does nothing | Check Firebase SSE streams started in log; check MQTT bridge connected to `192.168.1.108:1883` |
| Porch light not turning on at night | Check radar MQTT arriving (`home/esp32/radar2/motion`); check night hours 18–06; check `_porch_light_on` state |
| Radar motion detected but no video recorded | Check `is_video_recording_enabled()` via bot; check camera initialised in log (`Video recorder: OK`); check mosquitto radar bridge is running (`sudo journalctl -u mosquitto \| grep bridge`) |
| Pi5 not receiving ESP32-RADAR MQTT messages | Check mosquitto radar bridge: `sudo journalctl -u mosquitto \| grep -i bridge`. Bridge subscribes to `home/esp32/radar2/#` on VIP broker and republishes locally. If bridge is down, restart mosquitto on Pi5. |
| Pi5 not receiving relay/sensor ESP MQTT messages | Expected when Pi5 is BACKUP — `MQTT_HOST=localhost` means Pi5's mybot only processes ESP messages when Pi5 holds the VIP (ESPs connect to VIP broker). This is by design — no duplication between Pis. |
| App bulb shows permanent pending spinner when light triggered by motion or timer | `state` and `confirmed` out of sync — `_on_lobby_mqtt_state` / `_on_porch_mqtt_state` / `_on_lp_rly_mqtt_state` write both `confirmed` and `state` to Firebase; check that MQTT state callbacks are firing in the log |
| App shows orange / VIP unreachable after toggling local routing off then back on | `LocalApiServer` thread was blocked by a half-open TCP connection (Flutter app timed out at 2 s while the Pi's socket stayed open, causing `rfile.readline()` to block forever — accept queue fills, `/ping` never responds). Fixed in 2026-05-22: switched to `ThreadingHTTPServer`. If seen on older build, `sudo systemctl restart mybot.service` clears it immediately. |
| Duplicate door events in Firebase (`door_events` collection has two docs per open/close) | Pi5 reed switch callbacks were registered but GPIO 26 has no physical hardware — EMI from the 24 GHz radar triggered phantom events that published to `REED_DOOR/1` in parallel with Pi4. Fixed 2026-05-24: reed callbacks and `AwsIoTPublisher` disabled at startup on Pi5. |
| `mybot.service` stays inactive after reboot / Telegram bot silent after boot | Internet / DNS not ready when service started — check `After=network-online.target` is set in `mybot.service` (not `network.target`); also check `StartLimitIntervalSec` and `OnFailure` are in the `[Unit]` section; also check `main.py` init failure calls `sys.exit(1)` not a bare `return` so `Restart=on-failure` can re-trigger |
| `mybot.service` crash-looping | Check `logs/error_log.txt`; check GPIO conflicts; check sensor hardware connected |
| Scheduled timer not firing | Check `LightScheduler started` in log; verify `enabled=true` and valid HH:MM times in Firebase `/schedules/`; check Pi clock (`date` command) |
| Both Pi4 and Pi5 running but only one responds to light commands | Only the Pi holding the Keepalived VIP receives ESP MQTT connections — check `ip addr show wlan0 \| grep 192.168.1.100` on each Pi |
| Both Pis show as MASTER / split-brain (both have VIP `192.168.1.100`) | Usually caused by Pi5's wlan0 flapping ~4 s after keepalived starts — Pi5 misses Pi4's adverts and claims MASTER. Fixed by the `wait-for-wlan.conf` startup delay drop-in on Pi5. If it still occurs, run `makepi4master` to resolve manually. |
| keepalived `(HUB_IP) Entering FAULT STATE` / `Netlink reports wlan0 down` in logs | Pi5's wlan0 flapped during startup — suppressed by `wait-for-wlan.conf` startup delay. If it persists at runtime, check WiFi power save: `iwconfig wlan0 \| grep Power` — should say `Power Management:off`. |
| `advertisement interval mismatch` in keepalived logs | `advert_int` differs between Pi4 and Pi5 — must be identical (currently `2` on both). Check `/etc/keepalived/keepalived.conf` on both Pis. |

---

## Changelog

| Date | Change |
|---|---|
| 2026-06-18 | **Fix: Telegram None guard in `_on_recording_complete` and `_process_motion`** — after making Telegram init non-fatal, `self.telegram` can be `None` at runtime; `_on_recording_complete` was calling `self.telegram.send_video()` unconditionally → `AttributeError: 'NoneType' object has no attribute 'send_video'` logged as "Recording error"; `_process_motion` also called `self.telegram.send_text()` unconditionally; both now guarded with `if self.telegram:`. |
| 2026-06-18 | **Fix: Telegram init made non-fatal** — `initialize()` now continues if Telegram is unreachable at startup (logs warning, sets `self.telegram = None`, skips bot loop/command registration with a warning); matches Pi4 behavior; prevents Pi5 from failing to start when Telegram is temporarily down during a master failover. |
| 2026-06-18 | **Fix: Firebase startup pre-seeding** — `initialize()` now reads `living_room`, `lobby`, and `lower_porch_light` states from Firebase before starting SSE streams (`firebase.get_light_command()`); sets `_last_*_cmd` for all three lights; also sets `_ll_motion_triggered = True` if LL light was ON at startup (treats it as motion-owned to avoid the manually-ON guard blocking motion auto-ON during startup window). Without this both Pis executed the initial SSE `put` event as a real relay command on every restart — causing phantom toggles. |
| 2026-06-18 | **Fix: SSE dedup filter added at handler entry** — `_on_firebase_light_cmd`, `_on_firebase_ul_cmd`, `_on_firebase_lp_rly_cmd` now return immediately (log at DEBUG) when the incoming command matches `_last_*_cmd`. Previously the dedup only ran inside the debounced execute methods — both Pis would arm the 400 ms timer and execute in parallel. Now Pi5 ignores the SSE event once Pi4 has confirmed the relay state to Firebase, eliminating double relay commands from app interactions. |
| 2026-06-18 | **Fix: `_execute_light_cmd` restructured to match Pi4** — (1) `_ll_light_off_timer` is now cancelled before the dedup check (user taking manual control always cancels the motion auto-off countdown); (2) `_living_room_manual_off_time` and `_ll_motion_triggered` are set before the dedup check so manual OFF/ON are recorded even if the relay is already in that state; (3) added `self.mqtt_bridge.ll_available` guard (same as Pi4) so LL MQTT command only fires when the relay device is online. |
| 2026-06-18 | **Fix: `_execute_ul_cmd` — clear motion flag on manual ON** — added `self._ul_motion_triggered = False` when user manually turns ON the upper-lobby light; previously the 5-min motion auto-off timer kept running and would turn the light back off while the user had manually set it ON. |
| 2026-06-18 | **Fix: Infinite re-ON loop in radar motion off-timers** — Pi5's `_on_ll_mqtt_state` and `_on_ul_mqtt_state` have firmware-auto-off guards (`if not relay_on and not _*_motion_triggered and _last_*_cmd`) that re-send ON when the relay turns off unexpectedly. When the 5-min timer in `_on_radar_motion` fired: it cleared `_*_motion_triggered = False` then sent OFF → relay went OFF → `_on_*_mqtt_state` fired with `motion_triggered=False` + `last_cmd=True` → guard re-sent ON → infinite loop. Fixed by setting `_last_ul_cmd = False` and `_last_living_room_cmd = False` immediately before `send_*_relay(False)` in each off-timer closure (same pattern already used by `_on_schedule_*_relay`). |
| 2026-06-03 | Add `vrrp_script check_mybot` to Pi4 keepalived config (Pi4 repo) — `weight -20` drops Pi4 effective priority from 101 to 81 when `mybot.service` is not active; Pi5 (priority 100) preempts and claims VIP so ESP devices reconnect to Pi5's broker; no notify scripts so no circular dependency; failover ~10 s, handback ~10 s after mybot recovers. Pi5 keepalived config unchanged. |
| 2026-06-03 | Fix `mybot.service` not restarting after reboot when internet is not yet ready — (1) `After=network.target` → `After=network-online.target` so systemd waits for DNS before starting; (2) `StartLimitIntervalSec` + `OnFailure` moved from `[Service]` to `[Unit]` section where they are valid (were silently ignored before, so the 5-crash → reboot safety net was not working); (3) bare `return` on init failure replaced with `sys.exit(1)` so `Restart=on-failure` actually triggers when the service starts before internet is ready. Verified: full cold reboot with Pi4 as MASTER, Pi5 stays BACKUP — all services healthy after reboot. |
| 2026-06-03 | Add `RecordingResult.trigger` field (`"radar"`, `"local"`, `"manual"`) to `video_recorder.py` — `start_recording()` accepts `trigger` param; `_on_recording_complete` uses it to set a descriptive Telegram video caption (`"ESP32 Radar motion — 22s"` / `"Motion detected — Xs"` / `"Manual recording — Xs"`) instead of sending videos with no caption. |
| 2026-06-03 | Add mosquitto radar topic bridge on Pi5 (`/etc/mosquitto/conf.d/radar-bridge.conf`, `OS_Migration_PI5/configs/mosquitto-radar-bridge.conf`) — bridges `home/esp32/radar2/motion` and `home/esp32/radar2/availability` from VIP broker to Pi5's local mosquitto; Pi5's camera now records and sends radar-triggered video to Pi5's Telegram at all times, regardless of MASTER/BACKUP state. |
| 2026-06-03 | Decouple keepalived from mybot.service on both Pis — removed `vrrp_script check_mybot`, `track_script`, and all `notify_master/backup/fault` hooks; keepalived now manages only the VIP; `mybot.service` runs independently on both Pis under systemd; eliminates the circular dependency (keepalived restart → notify_backup stops mybot → check_mybot fails → Pi4 priority drops 101→81 → split-brain). |
| 2026-06-03 | Fix MQTT duplication — `MQTT_HOST` changed from `192.168.1.100` to `localhost` on both Pis; both Pis were previously connecting to the same VIP broker, subscribing to all ESP topics, and processing every message twice (duplicate Telegram alerts, duplicate Firebase writes); with localhost, only the MASTER Pi's mybot receives ESP messages. |
| 2026-06-03 | Fix keepalived split-brain on Pi5 startup — Pi5's wlan0 flaps ~4 s after boot (WiFi reassociation); Pi5 enters FAULT → BACKUP → MASTER in ~12 s before it can hear Pi4's adverts; fixed with systemd startup delay drop-in `/etc/systemd/system/keepalived.service.d/wait-for-wlan.conf` (waits for `192.168.1.108` on wlan0 then 5 s buffer); also increased `advert_int` 1 → 2 on both Pis to extend `master_down_interval` from ~3.6 s to ~6.6 s. |
| 2026-06-02 | Revert all MQTT brokers back to Keepalived VIP `192.168.1.100` — ESP32-RADAR firmware, ESP01-UL-RLY firmware, and Pi5 `mybot.service` `MQTT_HOST` all changed back from `192.168.1.108` to `192.168.1.100`; this ensures whichever Pi is MASTER handles all MQTT without any device needing reconfiguration on failover. Both devices OTA-flashed. |
| 2026-06-02 | Add "Two-Floor Sensor & Relay Assignment" section to README — documents that Pi4 (lower lobby, RASPI4-MAIN) has LD2420 wired directly on serial and controls ESP01-LL-RLY (`192.168.1.85`), while Pi5 (upper lobby, RASPI5-MAIN) receives radar motion from ESP32-RADAR over MQTT and controls ESP01-UL-RLY (`192.168.1.111`). |
| 2026-06-02 | Fix ESP32-RADAR motion not turning on lower-lobby light (ESP01-LL-RLY) — `_on_radar_motion()` only called `send_ul_relay(True)`; added `send_ll_relay(True)` (night only, respects 2-min manual-OFF override via `_living_room_manual_off_time`); added `_ll_light_off_timer` to turn LL-RLY OFF 5 min after motion stops, matching the existing UL-RLY behaviour. |
| 2026-06-02 | Fix `Restart=always` → `Restart=on-failure` in `mybot.service` on both Pi4 and Pi5 — `Restart=always` restarted mybot even after an explicit `systemctl stop`, fighting keepalived's `notify_backup`/`notify_fault` stop commands; each WiFi flap caused a rapid start/stop cycle that hit `StartLimitBurst=5` in under 5 minutes and triggered `OnFailure=systemd-reboot.service`; with `on-failure`, keepalived's explicit stops stick and only genuine crashes trigger auto-restart. |
| 2026-06-02 | Fix WiFi power management causing keepalived split-brain — `wlan0` sleep mode on both Pis caused periodic `wlan0 down` events; keepalived entered FAULT, fired `notify_fault` (stopped mybot), dropped priority, and both Pis ended up simultaneously MASTER with the VIP on both interfaces. Fixed by disabling WiFi power save permanently on both Pis via `/etc/NetworkManager/conf.d/wifi-powersave-off.conf` (`wifi.powersave = 2`) + `nmcli con modify`. Split-brain resolved by restarting Pi5 keepalived so it cleanly re-enters BACKUP and yields to Pi4 (priority 101). |
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
