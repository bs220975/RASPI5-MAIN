# Raspberry Pi MQTT + Firebase Bridge — Project Reference

## Revision History

| Date | Session | Changes |
|---|---|---|
| 2026-05-13 | Session 2 | Phase 1 Firebase SSE streaming implemented. Phase 2 MQTT bridge implemented. ESP01-LL-RLY MQTT firmware verified live. Both repos pushed to GitHub. |
| 2026-05-14 | Session 3 | Full project folder reorganisation — all files consolidated inside `RASPI4-MAIN/`. Shell scripts rewritten (`backup.sh` → rsync with progress; `sync.sh` → fixed stderr capture and rclone v1.60 grep). Broken aliases fixed and updated. `logs/` folder created (moved from `pi4_drive/Error_and_Logs/`). `influx_aws_publish/` moved into `RASPI4-MAIN/`. Service files updated with correct paths. `ace_design_projects/RASPI4-MAIN` archived as `RASPI4-MAIN_OLD_BACKUP`. This file renamed from `ARCHITECTURE_MQTT_FIREBASE_BRIDGE.md` to `PROJECT_REFERENCE.md`. |

---

## Quick Navigation

- [Goal](#goal)
- [Recommended Architecture](#recommended-architecture)
- [Communication Model](#communication-model)
- [Recommended MQTT Topic Design](#recommended-mqtt-topic-design)
- [Raspberry Pi Bridge Responsibilities](#raspberry-pi-bridge-responsibilities)
- [Recommended Migration Plan](#recommended-migration-plan)
- [Heartbeat And Live Status Architecture](#heartbeat-and-live-status-architecture)
- [OTA Firmware Update Architecture](#ota-firmware-update-architecture)
- [Information Required Before Implementation](#information-required-before-implementation)
- [Minimum Information Needed To Start Coding](#minimum-information-needed-to-start-coding)
- [Suggested Input Template](#suggested-input-template)

---

## Goal

Use the Raspberry Pi as the single always-on bridge between:

- local ESP01 / ESP32 devices
- local Mosquitto MQTT broker
- Firebase Realtime Database
- local automations such as motion-triggered switching

This removes the need for low-memory ESP devices to maintain multiple direct cloud TCP/TLS connections to Firebase.

## Recommended Architecture

```text
ESP01 / ESP32 devices  <->  Mosquitto on Raspberry Pi  <->  Raspberry Pi bridge  <->  Firebase RTDB
                                                  |
                                                  +-> local automations / Telegram / sensors
```

### Device responsibilities

#### ESP devices

ESP01 / ESP32 devices should:

- connect to local Wi-Fi
- open one MQTT connection to Mosquitto on the Raspberry Pi
- subscribe to command topics
- publish state, telemetry, and availability topics
- avoid direct Firebase communication

#### Raspberry Pi

The Raspberry Pi should:

- run Mosquitto as the local MQTT broker
- run one bridge process for MQTT <-> Firebase RTDB
- receive local state from ESP devices
- publish local commands to ESP devices
- stream Firebase app commands and convert them to MQTT commands
- update Firebase RTDB with filtered device state and confirmations
- handle retries, reconnects, state cache, logging, and automation logic

#### Firebase RTDB

Firebase should be used for:

- Android app state
- remote control commands
- live status that must be visible outside the LAN
- confirmed switch state
- selected alerts and summaries

Firebase should not be the primary transport between ESP devices and the local network.

---

## Why this architecture is better

Direct ESP -> Firebase communication is expensive on ESP01 and weaker ESP32 builds because:

- TLS handshakes consume RAM and CPU
- reconnects are costly on unstable Wi-Fi
- multiple simultaneous cloud sockets are hard on low-memory devices
- each device duplicates cloud logic and retry handling

Local MQTT through the Raspberry Pi is better because:

- local LAN traffic is lighter and faster
- each device keeps one persistent MQTT session
- the Pi handles cloud integration centrally
- ESP firmware becomes simpler
- system reliability improves when the internet is unstable

## Communication Model

### Control path

```text
Android app -> Firebase RTDB -> Raspberry Pi Firebase listener -> MQTT publish -> ESP device
```

### Status path

```text
ESP device -> MQTT publish -> Raspberry Pi bridge -> Firebase RTDB
```

### Local automation path

```text
Pi sensor event -> Raspberry Pi automation -> MQTT publish -> ESP device
```

---

## Recommended MQTT Topic Design

Keep topics simple, stable, and predictable.

### Commands from Pi to devices

- `home/esp01/lobby/cmd/relay`
- `home/esp32/porch/cmd/light`
- `home/esp32/gsm/cmd/reed`

### State from devices to Pi

- `home/esp01/lobby/state`
- `home/esp01/lobby/availability`
- `home/esp32/porch/state`
- `home/esp32/porch/telemetry`

### Example command payloads

- `ON`
- `OFF`
- `RESET`

### Example state payload

```json
{
  "relay": true,
  "rssi": -67,
  "uptime": 12345
}
```

## MQTT Practices To Use

### Last Will and Testament

Each ESP device should publish:

- `online` on successful MQTT connect
- `offline` as the Last Will message on unexpected disconnect

### Retained messages

Use retained messages for:

- desired state topics if needed
- latest known state topics where useful
- availability state if your app benefits from the last known value

### QoS guidance

For most device control:

- QoS 0 is acceptable for frequent telemetry
- QoS 1 is safer for relay commands and important state updates

---

## Raspberry Pi Bridge Responsibilities

The Pi bridge should run three logical jobs.

### 1. MQTT client / broker integration

- subscribe to all ESP state topics
- publish commands to device command topics
- detect availability changes
- maintain a last-known-state cache

### 2. Firebase bridge

- write selected MQTT state into RTDB
- listen to RTDB command changes using a streaming connection
- convert Firebase commands into MQTT publishes
- write confirmed device state back to RTDB

### 3. Local automation engine

- react to radar, PIR, MMS, or reed switch events
- publish MQTT commands for local switching
- update Telegram and Firebase when state changes matter

## Important Design Rule

Do not mirror every raw sensor event to Firebase.

Instead:

- publish high-frequency local events on MQTT
- let the Pi decide what is worth pushing to Firebase
- push only useful cloud-visible state, alerts, summaries, and confirmations

This reduces cloud traffic and avoids noisy RTDB updates.

---

## Current Project State

At the time of writing, this repository uses:

- HTTP from Raspberry Pi to ESP devices in `esp_devices.py`
- Firebase RTDB REST reads and writes in `firebase_logger.py`
- a 1-second Firebase poll loop for `lights/living_room/state` in `main.py`

This works, but it keeps device control tied to HTTP polling and does not yet use the Raspberry Pi as the local MQTT bridge.

## Recommended Migration Plan

Do not switch all devices at once.

### Phase 1: improve Firebase command handling

- replace the 1-second Firebase polling loop with a Firebase RTDB stream listener on the Pi
- keep current HTTP control to ESP devices unchanged

Result:

- app commands become near-real-time
- Firebase read traffic drops

### Phase 2: introduce MQTT for selected devices

- add MQTT client logic to one ESP01 and one ESP32 first
- Pi subscribes to their state topics
- Pi publishes commands to them via MQTT
- keep HTTP fallback during testing

Result:

- migration happens safely
- old and new control paths can coexist

### Phase 3: route app commands through the Pi bridge

- Firebase app commands are streamed by the Pi
- Pi translates them into MQTT commands
- Pi updates confirmation state after device response

Result:

- app control no longer depends on direct HTTP polling

### Phase 4: remove direct cloud logic from ESP devices

- stop direct Firebase communication from ESP devices
- leave Firebase communication only on the Raspberry Pi
- keep MQTT as the local transport for ESP devices

Result:

- much lighter firmware footprint
- cleaner separation of responsibilities

---

## Backward-Compatible Target State

During migration, the Raspberry Pi can support both:

- MQTT-first devices
- legacy HTTP-controlled devices

That means:

- new devices use MQTT topics
- older devices can still respond to `http://<ip>/lighton`, `lightoff`, and `/status`
- the Pi bridge decides which transport to use per device

## Suggested Firebase Role After Migration

After migration, Firebase should mainly store:

- Pi online status
- selected device online status
- live motion state needed by the app
- desired switch state from the app
- confirmed switch state from the Pi
- important alerts and summaries

Firebase should not be used as a high-frequency device bus.

## Heartbeat And Live Status Architecture

In the recommended architecture, the Raspberry Pi should act as the heartbeat and presence coordinator for all devices.

The app should read device liveliness and status from Firebase RTDB, not directly from ESP devices.

### Recommended heartbeat path

```text
ESP device -> MQTT heartbeat / state -> Raspberry Pi bridge -> Firebase RTDB -> app
```

### Recommended device behavior

Each MQTT-capable ESP device should publish:

- `home/<device_id>/availability`
- `home/<device_id>/state`

The `availability` topic should indicate:

- `online` when the device connects successfully
- `offline` when the device disconnects unexpectedly

This should be implemented using MQTT Last Will and Testament where possible.

### Recommended Raspberry Pi behavior

The Raspberry Pi should:

- subscribe to availability and state topics for all managed devices
- detect online/offline changes
- update Firebase RTDB with selected status fields
- keep a last-known-state cache locally
- avoid direct IP polling for MQTT-native devices

### Recommended Firebase fields per device

For each device, Firebase RTDB can store:

- `reachable`
- `lastSeen`
- `deviceType`
- `room`
- `firmwareVersion`
- `rssi`
- current device state such as relay, light, motion, or sensor values if needed by the app

Example device status shape:

```json
{
  "reachable": true,
  "lastSeen": 1778570000000,
  "relayState": true,
  "rssi": -64,
  "firmwareVersion": "1.2.3"
}
```

### Recommended update policy

The Raspberry Pi should not push every device state to Firebase every second.

Better behavior is:

- write immediately when a device goes online
- write immediately when a device goes offline
- write when an important state changes
- refresh `lastSeen` at a moderate interval such as 30 to 120 seconds when needed

This keeps the app live and responsive without generating noisy RTDB traffic.

### Legacy device support during migration

During migration, the Raspberry Pi can support both heartbeat models:

- MQTT heartbeat for MQTT-native devices
- HTTP `/status` polling for legacy HTTP-only devices

This allows gradual migration without breaking current devices.

## Mosquitto Deployment Notes

On the Raspberry Pi:

- run Mosquitto with username and password
- avoid anonymous access on the LAN
- give the Pi a static IP
- enable persistence if retained state should survive reboot
- keep topic names fixed and documented

This repository already includes migration scripts that install Mosquitto at the OS level, which aligns with this architecture.

## Best End State

For a mixed ESP01 / ESP32 home automation network, the best long-term design is:

- ESP devices use MQTT only
- Raspberry Pi runs Mosquitto and the MQTT <-> Firebase bridge
- Firebase RTDB is used only for app-facing cloud state and remote control
- the Pi owns retries, reconnects, cloud writes, and automation policy

This is the recommended architecture for lower memory usage, better local reliability, and simpler ESP firmware.

---

# OTA Firmware Update Architecture

The Raspberry Pi can also act as the OTA orchestration point for ESP firmware updates.

This is better than having each ESP device communicate directly with Firebase or another cloud endpoint for firmware downloads.

### Recommended OTA control path

```text
Firebase app -> Firebase RTDB command -> Raspberry Pi OTA controller -> MQTT OTA command -> ESP device
```

### Recommended OTA status path

```text
ESP device -> MQTT progress / status topics -> Raspberry Pi bridge -> Firebase RTDB
```

## OTA Design Recommendation

Use the Raspberry Pi as the OTA controller, not just a command forwarder.

Recommended model:

- Firebase stores OTA intent, version metadata, and rollout request
- Raspberry Pi validates the request
- Raspberry Pi publishes an OTA command to the target ESP device over MQTT
- Raspberry Pi serves the firmware file locally over HTTP on the LAN
- ESP downloads the firmware from the Raspberry Pi
- ESP flashes the image and reports progress and result through MQTT
- Raspberry Pi writes progress and final state back to Firebase RTDB

### Why this model is better

- ESP devices avoid cloud TLS during large firmware downloads
- local LAN firmware download is lighter and more reliable
- Raspberry Pi can validate firmware version, target model, size, and checksum
- Raspberry Pi can centralize rollout control and progress reporting

## Less Preferred OTA Model

It is possible for the Raspberry Pi to tell the ESP device to download firmware directly from a Firebase-linked or cloud-hosted URL.

However, this is less ideal for low-memory devices because:

- the ESP still needs cloud TLS for the firmware download
- cloud download failures are more likely on weak Wi-Fi
- large downloads are harder on small devices
- Firebase RTDB itself is not meant to host firmware binaries

If cloud hosting is used, Firebase should hold metadata only, such as:

- desired firmware version
- release notes or rollout flags
- firmware URL
- firmware checksum

The actual firmware binary should preferably be hosted:

- on the Raspberry Pi
- on a simple HTTP server on the LAN
- or in external object storage when local hosting is not practical

## OTA Responsibilities

### Raspberry Pi responsibilities

- receive OTA request from Firebase RTDB
- validate target device type and version compatibility
- expose firmware images on a local HTTP endpoint
- publish OTA command to the target device over MQTT
- track progress and timeout state
- update Firebase RTDB with progress, success, or failure

### ESP device responsibilities

- subscribe to OTA command topics
- compare current version against requested version
- download firmware from the Raspberry Pi HTTP endpoint
- verify checksum if provided
- flash using the appropriate OTA library
- publish progress and final result over MQTT
- reboot and publish new version after startup

## Suggested MQTT Topics For OTA

### OTA command topic

- `home/<device_id>/cmd/ota`

### OTA progress topics

- `home/<device_id>/ota/progress`
- `home/<device_id>/ota/status`
- `home/<device_id>/state`

## Example OTA Command Payload

```json
{
  "version": "1.2.3",
  "url": "http://192.168.1.10/fw/esp32_porch_v1.2.3.bin",
  "sha256": "abc123...",
  "size": 524288,
  "force": false
}
```

## Example OTA Status Payload

```json
{
  "phase": "downloading",
  "progress": 42,
  "version": "1.2.3"
}
```

## Example OTA Success Payload

```json
{
  "phase": "success",
  "version": "1.2.3"
}
```

## Suggested Firebase Role For OTA

Firebase should store OTA control and reporting data, not the firmware binary itself.

Suggested RTDB areas:

- `ota/commands/<device_id>`
- `ota/status/<device_id>`
- `ota/releases/<device_type>/latest`

Suggested use:

- app writes the target version or rollout request
- Raspberry Pi consumes the request and starts the OTA sequence
- Raspberry Pi updates progress and final state for app visibility

## OTA Limitations And Hardware Notes

ESP32 devices are generally good OTA candidates.

ESP01 devices need extra care because:

- available flash can be very limited
- free space may not allow safe OTA
- binary size and partition layout matter a lot

For some ESP01 builds, OTA may be difficult or impossible without reducing firmware size or changing the flash strategy.

Recommended expectation:

- ESP32: preferred target for full OTA workflow
- ESP01: validate flash size and firmware layout before promising OTA support

---

## Information Required Before Implementation

To implement this architecture cleanly in the current project, collect the following information first.

### 1. Device inventory

For each ESP device, define:

- `device_id`
- hardware type such as `ESP01` or `ESP32`
- function such as `relay`, `light`, `reed`, `motion`, `oled`, `gsm`, or `sensor`
- room or physical location
- migration status:
  - existing HTTP-only device
  - can be updated to MQTT
  - new MQTT-native device

### 2. Per-device command model

For each device, define:

- supported commands
- expected command payloads
- expected state payload shape
- telemetry fields if any

Examples:

- relay commands: `ON`, `OFF`, `RESET`
- door commands: `OPEN`, `CLOSE`
- state payload: relay state, RSSI, uptime, sensor value, battery, temperature

### 3. Firebase RTDB mapping

Identify which Firebase paths must remain compatible with the Android app or any existing clients.

Examples:

- `devices/RASPI-4`
- `devices/ESP01-LL-RLY`
- `lights/living_room/state`
- `lights/living_room/confirmed`

Also define:

- any new RTDB paths to add
- which MQTT states should be written to which RTDB paths
- which RTDB command paths should generate MQTT commands

### 4. Mosquitto deployment details

Define the local broker details:

- Raspberry Pi static IP or hostname
- MQTT port
- username and password
- whether MQTT is LAN-only or also TLS-secured
- whether persistence should be enabled

### 5. Device discovery approach

Choose one of the following:

- strict registry file on the Pi
- auto-discovery from MQTT topics
- hybrid discovery with optional registry metadata

Recommended choice:

- hybrid discovery with a small registry file

### 6. Migration strategy

Choose how to migrate from the current architecture.

Options:

- keep current HTTP ESP control and add Firebase streaming first
- add MQTT bridge and keep HTTP fallback during migration
- move selected devices directly to MQTT-first

Recommended choice:

- add MQTT bridge and keep HTTP fallback during migration

### 7. ESP firmware constraints

For each device family or board type, note:

- available memory constraints
- firmware framework such as Arduino or ESP-IDF
- current MQTT library if already used
- whether the device can be reflashed now

### 8. Reliability and state rules

Define the expected behavior for failure cases:

- what happens if the Pi is offline
- what happens if Mosquitto is offline
- whether relays should restore last state after reboot
- whether command topics should be retained
- whether state topics should be retained
- required QoS level for command and state messages

### 9. Local automation rules

List any Pi-side automation logic that must remain or be added.

Examples:

- lobby motion -> turn relay ON
- porch motion only at night
- cooldown between repeated triggers
- door sensor event -> GSM or Telegram alert

### 10. Secret and configuration handling

Choose where credentials and environment-specific values will live.

Options:

- hardcoded in Python
- environment variables
- systemd environment file
- separate local config file ignored by git

Recommended choices:

- environment variables
- systemd environment file for Raspberry Pi deployment

## Minimum Information Needed To Start Coding

If implementation should begin immediately, the minimum required information is:

- device list and roles
- Firebase RTDB paths that must stay unchanged
- MQTT broker host, port, username, and password
- whether HTTP fallback should remain during migration
- which first device should be migrated to MQTT
- preferred registry format: `json` or `yaml`

## Suggested Input Template

Use a structure like this when preparing implementation details:

```text
Pi broker:
- host: 192.168.1.10
- port: 1883
- username: mq
- password: ***
- TLS: no

Keep Firebase paths:
- devices/RASPI-4
- devices/ESP01-LL-RLY
- lights/living_room/state
- lights/living_room/confirmed

Devices:
- esp01_lobby, relay, existing HTTP, will migrate to MQTT
- esp32_porch, light, can use MQTT now
- esp32_gsm, reed alert, can use MQTT now

Migration mode:
- MQTT bridge + HTTP fallback

Registry format:
- json
```

---

## Implementation Status

Last updated: 2026-05-13 (session 2)

---

### Environment

| Item | Value |
|---|---|
| Raspberry Pi LAN IP | `192.168.1.122` |
| Mosquitto broker | `localhost:1883` |
| Mosquitto credentials | `mq / mq` |
| ESP01-LL-RLY static IP | `192.168.1.85` |
| Firebase RTDB URL | `https://home-security-app-555cf-default-rtdb.asia-southeast1.firebasedatabase.app` |
| RASPI4-MAIN repo | `https://github.com/bs220975/RASPI4-MAIN` — branch `main` |
| ESP01-LL-RLY repo | `https://github.com/bs220975/ESP01-LL-RLY` — branch `master` |

---

### Lessons Learned

**Bootstrap vs relay firmware (important)**
The `esp01_bootstrap_ota` and `esp01_relay_ota` environments both upload to the same IP.
Always use `pio run -e esp01_relay_ota --target upload` for the production relay firmware.
Bootstrap (`esp01_bootstrap_ota`) is only for blank devices that need OTA capability first.
Symptom of bootstrap running: device pings, port 80 closed, port 8266 open, no MQTT.

---

### Completed

#### Infrastructure

- [x] Mosquitto installed and running on Pi with authentication enabled
- [x] `mq / mq` credentials verified working (`mosquitto_pub` test passed)
- [x] `paho-mqtt` installed on Pi (`~/.local/lib/python3.13/site-packages/paho`)
- [x] Git identity configured on Pi (`bs220975 / bs220975@gmail.com`)
- [x] `gh` CLI `2.92.0` and `git` `2.47.3` both installed

#### Phase 1 — Firebase SSE streaming (replaces 1-second REST poll)

- [x] `firebase_logger.py` — added `start_command_stream(light_id, callback)`
  - Opens a persistent SSE connection to `lights/<light_id>/state`
  - Calls callback immediately on every value change
  - Reconnects automatically on network errors with 5 s backoff
  - `mark_offline()` stops the stream on clean shutdown
- [x] `firebase_logger.py` — added `stop_command_stream()`
- [x] `main.py` — removed 1-second Firebase REST polling loop and `_poll_light_command()`
- [x] `main.py` — added `_on_firebase_light_cmd(cmd)` as the event-driven replacement
  - Deduplicates — skips if same command seen since last reconnect
  - Tries MQTT first, falls back to HTTP if bridge is not connected
  - Writes `lights/living_room/confirmed` after HTTP execution
- [x] Firebase paths preserved unchanged:
  - `lights/living_room/state` — app command input
  - `lights/living_room/confirmed` — Pi confirmation output
  - `devices/RASPI-4` — Pi heartbeat
  - `devices/ESP01-LL-RLY` — relay status
  - `lights/live` — live motion state for Android app

#### Phase 2 — MQTT bridge on the Raspberry Pi

- [x] `mqtt_bridge.py` — new module, `MqttBridge` class
  - Connects to local Mosquitto with configurable credentials
  - Subscribes to `home/esp01/lobby/state` (QoS 1)
  - Subscribes to `home/esp01/lobby/availability` (QoS 1)
  - Publishes `ON` / `OFF` to `home/esp01/lobby/cmd/relay` (QoS 1)
  - Handles connect, disconnect, and automatic paho reconnect
  - Graceful degradation if `paho-mqtt` is not installed
- [x] `config.py` — added `MqttConfig` dataclass
  - Reads `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS` from environment
  - Compiled-in defaults: `localhost : 1883 / mq / mq`
- [x] `config.py` — `MqttConfig` added to `AppConfig`
- [x] `main.py` — `MqttBridge` initialised in `initialize()`
- [x] `main.py` — `_trigger_light_control()` (motion → relay) tries MQTT first, HTTP fallback
- [x] `main.py` — `_on_lobby_mqtt_state(payload)` callback
  - Handles both plain `ON` / `OFF` and JSON `{"relay": true}` payloads
  - Updates `devices/ESP01-LL-RLY` and `lights/living_room/confirmed` in Firebase
- [x] `main.py` — `cleanup()` stops MQTT bridge before marking Firebase offline
- [x] `requirements.txt` — added `paho-mqtt>=1.6.0`

#### ESP01-LL-RLY firmware — MQTT verified live (repo: ESP01-LL-RLY, branch master)

- [x] `platformio.ini` — added `knolleary/PubSubClient@^2.8` to `lib_deps`
- [x] `src/config/HardwareConfig.h` — added MQTT constants
  - `MQTT_BROKER   192.168.1.122`
  - `MQTT_PORT     1883`
  - `MQTT_CLIENT_ID  esp01-ll-rly`
  - `MQTT_USER / MQTT_PASS  mq / mq`
  - `MQTT_TOPIC_CMD   home/esp01/lobby/cmd/relay`
  - `MQTT_TOPIC_STATE home/esp01/lobby/state`
  - `MQTT_TOPIC_AVAIL home/esp01/lobby/availability`
- [x] `src/main.cpp` — MQTT added alongside existing HTTP server
  - `mqttConnect()` — connects with Last Will (`offline`, retained), publishes `online`, subscribes cmd topic
  - `mqttCallback()` — receives `ON` / `OFF`, calls `setRelay()`
  - `publishState()` — publishes retained state on every relay change (HTTP, MQTT, and auto-off)
  - `mqttLoop()` — reconnects every 5 s if disconnected, called from `loop()`
  - HTTP `/lighton`, `/lightoff`, `/status` and ArduinoOTA preserved unchanged
  - 3-minute auto-off preserved, now also publishes MQTT state on timeout
- [x] Correct relay firmware flashed via OTA (`pio run -e esp01_relay_ota --target upload`)
- [x] **ESP01 MQTT connection verified live:**
  - `home/esp01/lobby/availability` → `online`
  - `home/esp01/lobby/state` → `OFF`
- [x] **Relay MQTT command test passed:**
  - Pi sends `ON` → ESP01 relay clicks ON → publishes `state: ON`
  - Pi sends `OFF` → ESP01 relay clicks OFF → publishes `state: OFF`

#### GitHub — both repos pushed

- [x] `RASPI4-MAIN` commit `b4a381f` pushed to `main`
- [x] `ESP01-LL-RLY` commit `adb055a` pushed to `master`

---

### Session End State — 2026-05-13 session 2

ESP01 MQTT path is fully working at the broker level.
MQTT commands verified: ON and OFF both travel correctly and relay responds.
The Pi `main.py` has not yet been run for end-to-end app testing — that is the next step.

---

### Next Session — Start Here

**Step 1 — Confirm ESP01 is still online**
```bash
mosquitto_sub -h localhost -p 1883 -u mq -P mq -t "home/esp01/lobby/#" -v -W 5
```
Expected: `home/esp01/lobby/availability online` and `home/esp01/lobby/state OFF`

**Step 2 — Run main.py and do full end-to-end app test**
```bash
cd /home/pi/pi4_drive/Git_projects/RASPI4-MAIN
python3 main.py
```
Then toggle the Living Room switch in the Android app and confirm:
1. Firebase SSE delivers command to Pi (`_on_firebase_light_cmd` fires)
2. Pi publishes MQTT command to `home/esp01/lobby/cmd/relay`
3. ESP01 relay clicks and publishes state back
4. Pi writes `lights/living_room/confirmed` to Firebase
5. Android app shows confirmed state

**Step 3 — Fix DHT11_ESP32 auth failure**
- Device `DHT11_ESP32-10B37A-V1` at `192.168.1.87` fails Mosquitto auth every 5 minutes
- Two options:
  - Add its credentials to Mosquitto: `sudo mosquitto_passwd /etc/mosquitto/passwd <username>`
  - Or update its firmware to use `mq / mq`

**Step 4 — Consider running main.py as a systemd service**
- So it auto-starts on Pi reboot
- Service file goes in `/etc/systemd/system/raspi4-automation.service`

---

### Pending

#### End-to-end app test (immediate next task)

- [ ] Run `main.py` and test Living Room switch via Android app
- [ ] Confirm `lights/living_room/confirmed` updates correctly in Firebase
- [ ] Confirm motion-triggered relay works via MQTT (walk in front of radar sensor at night)

#### DHT11_ESP32 auth fix

- [ ] `DHT11_ESP32-10B37A-V1` at `192.168.1.87` — failing Mosquitto auth every 5 min
- [ ] Fix by adding credentials to Mosquitto or reflashing firmware with `mq / mq`

#### Phase 3 — Route all app commands through the Pi MQTT bridge

- [ ] Extend Firebase SSE stream to cover additional device command paths
- [ ] Map each Firebase command path to its MQTT device topic
- [ ] Pi writes confirmation back to Firebase after MQTT state is received

#### Phase 4 — Remove direct cloud logic from ESP devices

- [ ] Remove any Firebase direct writes remaining on ESP firmware
- [ ] Confirm all ESP devices use MQTT only for communication
- [ ] Pi becomes the sole cloud integration point

#### Other devices — MQTT migration

- [ ] ESP01_Porch (`192.168.1.89`) — light, HTTP only, migrate to MQTT
- [ ] ESP32_GSM (`192.168.1.91`) — reed alert, migrate to MQTT
- [ ] ESP8266_DHT (`192.168.1.87`) — DHT11 sensor, fix auth then migrate
- [ ] ESP32_OLED (`192.168.1.102`), ESP32_ENERGY (`192.168.1.131`) — assess and schedule

#### systemd service

- [ ] Create `/etc/systemd/system/raspi4-automation.service` for `main.py`
- [ ] Enable and test auto-start on reboot

#### OTA firmware update architecture

- [ ] Design and implement OTA orchestration on the Pi (see OTA section above)
- [ ] Expose local HTTP firmware endpoint on the Pi
- [ ] Implement OTA MQTT topics per device: `home/<device_id>/cmd/ota`, `home/<device_id>/ota/status`
