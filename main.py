#!/usr/bin/env python3
"""
Raspberry Pi 5 Home Automation System - Main Application

This is the main entry point for the home automation system featuring:
- Motion detection with LD2420 radar and GPIO sensors
- Automated video recording on motion
- Telegram bot for remote monitoring and control
- ESP device integration for smart lighting
- InfluxDB logging for data analytics

Usage:
    python main.py

Environment Variables (optional):
    TELEGRAM_BOT_TOKEN: Override default bot token
    TELEGRAM_CHAT_ID: Override default chat ID
    INFLUXDB_TOKEN: Override default InfluxDB token

Author: Raspberry Pi Home Automation
Version: 26.01.27
"""
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time
import traceback
from datetime import datetime
from typing import Optional

from config import AppConfig, config
from telegram_handler import TelegramHandler
from sensors import SensorManager
from video_recorder import VideoRecorder, RecordingResult
from esp_devices import ESPDeviceManager
from influxdb_logger import InfluxDBLogger
from bot_commands import BotCommandHandler
from firebase_logger import FirebaseLogger
from mqtt_bridge import MqttBridge
from light_scheduler import LightScheduler
from local_api_server import LocalApiServer
from aws_iot_publisher import AwsIoTPublisher

__version__ = '26.5.16'
__author__ = 'Raspberry Pi Home Automation'

logger = logging.getLogger(__name__)


class RaspberryPiController:
    """
    Main controller for the Raspberry Pi home automation system.

    Coordinates all subsystems:
    - Telegram bot for remote control
    - Motion sensors (radar, PIR, MMS)
    - Video recording
    - ESP device control
    - InfluxDB logging

    Example:
        controller = RaspberryPiController()
        controller.start()
    """

    def __init__(self, app_config: Optional[AppConfig] = None):
        """
        Initialize the controller.

        Args:
            app_config: Application configuration. Uses global config if None.
        """
        self.config = app_config or config
        self._running = False
        self._shutdown_event = threading.Event()

        # Software watchdog
        self._watchdog_last_ping: float = time.time()
        self._watchdog_timeout: int = 60   # seconds — restart if loop frozen this long
        self._watchdog_thread: Optional[threading.Thread] = None

        # Subsystem instances
        self.telegram: Optional[TelegramHandler] = None
        self.sensors: Optional[SensorManager] = None
        self.recorder: Optional[VideoRecorder] = None
        self.esp: Optional[ESPDeviceManager] = None
        self.influx: Optional[InfluxDBLogger] = None
        self.bot_handler: Optional[BotCommandHandler] = None
        self.firebase: Optional[FirebaseLogger] = None
        self.mqtt_bridge: Optional[MqttBridge] = None
        self.scheduler: Optional[LightScheduler] = None
        self.local_api: Optional[LocalApiServer] = None
        self.aws_door: Optional[AwsIoTPublisher] = None

        # Motion detection state
        self._last_motion_time: float = 0
        self._last_light_activation: float = 0
        self._last_motion_message_time: float = 0
        self._recording_start_time: float = 0
        self._prev_motion_state: bool = False
        self._motion_stable_start: float = 0

        # ESP01 relay heartbeat
        self._last_relay_poll: float = 0
        self._last_relay_state: object = object()  # sentinel: "never polled"

        # Firebase heartbeat
        self._last_firebase_push: float = 0

        # Last light command EXECUTED — used to skip duplicate reconnect replays
        self._last_living_room_cmd: Optional[bool] = None
        # Debounce timer — cancelled/reset on each rapid incoming command
        self._light_cmd_timer: Optional[threading.Timer] = None
        # Timestamp of last manual turn-off; blocks motion auto-ON for 2 minutes
        self._living_room_manual_off_time: float = 0

        # Porch relay state (managed by MQTT radar motion + Firebase lobby2 stream)
        self._porch_light_on: bool = False
        self._porch_light_off_timer: Optional[threading.Timer] = None
        self._last_porch_cmd: Optional[bool] = None
        self._porch_cmd_timer: Optional[threading.Timer] = None
        # Timestamp of last manual turn-off; blocks radar auto-ON for 2 minutes
        self._porch_manual_off_time: float = 0

        # LP porch relay state (ESP32-LP-RLY / L-Porch-Light app switch)
        self._lp_rly_light_on: bool = False
        self._last_lp_rly_cmd: Optional[bool] = None
        self._lp_rly_cmd_timer: Optional[threading.Timer] = None

        # MQTT availability flags — used by _get_local_device_states()
        self._porch_reachable: bool = False
        self._lp_rly_reachable: bool = False

        # Setup logging
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Configure application logging with rotation to prevent large log files."""
        # Create log directory if needed
        log_dir = os.path.dirname(self.config.log_file_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        log_format = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(name)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Rotating file handler: max 1MB per file, keep 3 backups
        # Total max log storage: 4MB (error_log.txt + .1 + .2 + .3)
        file_handler = logging.handlers.RotatingFileHandler(
            self.config.log_file_path,
            maxBytes=1 * 1024 * 1024,  # 1 MB
            backupCount=3
        )
        file_handler.setFormatter(log_format)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(log_format)

        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

    def initialize(self) -> bool:
        """
        Initialize all subsystems.

        Returns:
            True if initialization successful, False otherwise
        """
        logger.info("=" * 50)
        logger.info("Initializing Raspberry Pi Controller")
        logger.info(f"Version: {self.config.script_version}")
        logger.info("=" * 50)

        try:
            # Initialize Telegram handler
            logger.info("Initializing Telegram handler...")
            self.telegram = TelegramHandler(self.config.telegram)
            if not self.telegram.start():
                logger.error("Failed to initialize Telegram handler")
                return False
            logger.info("Telegram handler: OK")

            # Initialize ESP device manager
            logger.info("Initializing ESP device manager...")
            self.esp = ESPDeviceManager(self.config.esp_devices)
            logger.info("ESP device manager: OK")

            # Initialize InfluxDB logger
            logger.info("Initializing InfluxDB logger...")
            self.influx = InfluxDBLogger(self.config.influxdb)
            if self.influx.connect():
                logger.info("InfluxDB logger: OK")
            else:
                logger.warning("InfluxDB connection failed - logging disabled")

            # Initialize sensor manager
            logger.info("Initializing sensor manager...")
            self.sensors = SensorManager(self.config.gpio, self.config.radar)
            if self.sensors.initialize():
                logger.info("Sensor manager: OK")
            else:
                logger.warning("Sensor initialization partial - some sensors unavailable")

            # Pi5 has no physical reed switch — callbacks intentionally disabled
            # to prevent EMI from the 24 GHz radar triggering phantom door events.
            logger.info("Reed switch door callbacks: disabled (no hardware on Pi5)")

            # aws_door not needed — Pi5 has no door sensor
            self.aws_door = None
            logger.info("AWS IoT door publisher: skipped (no reed switch on Pi5)")

            # Initialize video recorder
            logger.info("Initializing video recorder...")
            self.recorder = VideoRecorder(self.config.video)
            self.recorder.set_callbacks(
                on_complete=self._on_recording_complete,
                on_cleanup=self._on_disk_cleanup
            )
            if self.recorder.initialize():
                logger.info("Video recorder: OK")
            else:
                logger.warning("Camera initialization failed - recording disabled")

            # Initialize bot command handler
            logger.info("Initializing bot command handler...")
            self.bot_handler = BotCommandHandler(
                config=self.config,
                telegram_handler=self.telegram,
                esp_manager=self.esp,
                video_recorder=self.recorder,
                influx_logger=self.influx,
                sensor_manager=self.sensors
            )

            # Initialize Firebase logger
            logger.info("Initializing Firebase logger...")
            self.firebase = FirebaseLogger(self.config.firebase)
            if self.firebase.connect():
                logger.info("Firebase logger: OK")
                self.firebase.start_command_stream(
                    'living_room', self._on_firebase_light_cmd
                )
                self.firebase.start_command_stream(
                    'lobby', self._on_firebase_porch_light_cmd
                )
                self.firebase.start_command_stream(
                    'lower_porch_light', self._on_firebase_lp_rly_cmd
                )
                logger.info("Firebase light command streams: started (living_room + lobby + lower_porch_light)")
            else:
                logger.warning("Firebase connection failed - live status disabled")

            # Initialize MQTT bridge
            logger.info("Initializing MQTT bridge...")
            self.mqtt_bridge = MqttBridge(
                self.config.mqtt,
                on_lobby_state=self._on_lobby_mqtt_state,
                on_porch_state=self._on_porch_mqtt_state,
                on_porch_availability=self._on_porch_availability_changed,
                on_lp_rly_state=self._on_lp_rly_mqtt_state,
                on_lp_rly_availability=self._on_lp_rly_availability_changed,
                on_lp_rly_ota_status=self._on_lp_rly_ota_status,
                on_lp_rly_telegram=self._on_lp_rly_telegram,
                on_radar_motion=self._on_radar_motion,
            )
            if self.mqtt_bridge.start():
                logger.info("MQTT bridge: started")
            else:
                logger.warning("MQTT bridge: start failed - HTTP fallback active")

            # Initialize local API server (LAN fallback when Firebase is down)
            logger.info("Initializing local API server...")
            self.local_api = LocalApiServer(
                port=self.config.local_api_port,
                on_light_cmd=self._on_local_api_cmd,
                get_device_states=self._get_local_device_states,
            )
            self.local_api.start()
            logger.info(f"Local API server: port {self.config.local_api_port}")

            # Initialize light scheduler (Firebase-backed cron timers)
            logger.info("Initializing light scheduler...")
            self.scheduler = LightScheduler(
                send_lobby=lambda s: self.mqtt_bridge and self.mqtt_bridge.send_lobby_relay(s),
                send_porch=lambda s: self.mqtt_bridge and self.mqtt_bridge.send_porch_relay(s),
                send_lp_rly=lambda s: self.mqtt_bridge and self.mqtt_bridge.send_lp_rly_relay(s),
            )
            self.scheduler.start()
            if self.firebase:
                initial = self.firebase.get_schedules()
                if initial:
                    self.scheduler.apply_schedules(initial)
                    logger.info(f"Loaded {len(initial)} schedule(s) from Firebase")
                self.firebase.start_schedule_stream(self.scheduler.apply_schedules)
            logger.info("Light scheduler: OK")

            # Start bot message loop
            self.telegram.start_message_loop(self.bot_handler.handle_message)
            logger.info("Bot message loop: Started")

            # Register commands with Telegram menu (shows on '/' press)
            self.telegram.set_my_commands(self.bot_handler.get_commands_list())
            logger.info("Bot commands menu: Registered")

            logger.info("=" * 50)
            logger.info("Initialization complete")
            logger.info("=" * 50)
            return True

        except Exception as e:
            logger.error(f"Initialization error: {e}")
            logger.error(traceback.format_exc())
            return False

    def start(self) -> None:
        """Start the main control loop."""
        if not self.initialize():
            logger.error("Initialization failed, exiting")
            return

        # Send startup notification
        self._send_startup_message()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._running = True
        logger.info("Starting main loop...")

        # Start software watchdog thread
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="SoftwareWatchdog",
            daemon=True
        )
        self._watchdog_thread.start()
        logger.info(f"Software watchdog started (timeout: {self._watchdog_timeout}s)")

        # Wait for sensors to stabilize
        logger.info("Waiting for sensors to stabilize (5 seconds)...")
        time.sleep(5)
        logger.info("Sensors ready - monitoring started")

        try:
            self._main_loop()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            logger.error(traceback.format_exc())
            if self.telegram:
                self.telegram.send_text(f"Main loop error: {e}")
        finally:
            self.cleanup()

    def _watchdog_loop(self) -> None:
        """Software watchdog — exits process if main loop stops responding."""
        while self._running:
            time.sleep(10)  # check every 10 seconds
            elapsed = time.time() - self._watchdog_last_ping
            if elapsed > self._watchdog_timeout:
                logger.critical(
                    f"WATCHDOG: Main loop frozen for {elapsed:.0f}s "
                    f"(timeout={self._watchdog_timeout}s) — forcing restart"
                )
                if self.telegram:
                    self.telegram.send_text(
                        f"⚠️ Watchdog triggered — main loop frozen {elapsed:.0f}s. Restarting..."
                    )
                time.sleep(2)  # allow telegram message to send
                sys.exit(1)    # systemd will restart the service

    def _main_loop(self) -> None:
        """Main control loop - monitors sensors and handles events."""
        while self._running and not self._shutdown_event.is_set():
            try:
                time.sleep(0.2)  # 200ms loop interval

                # Pet the software watchdog
                self._watchdog_last_ping = time.time()

                # ESP01 relay heartbeat poll (runs regardless of motion state)
                if self.esp and (
                    time.time() - self._last_relay_poll
                    >= self.config.relay_heartbeat_interval
                ):
                    self._last_relay_poll = time.time()
                    threading.Thread(
                        target=self._poll_relay_heartbeat,
                        daemon=True
                    ).start()

                # Firebase heartbeat push
                if self.firebase and (
                    time.time() - self._last_firebase_push
                    >= self.config.firebase.heartbeat_interval
                ):
                    self._last_firebase_push = time.time()
                    threading.Thread(
                        target=self._push_firebase_status,
                        daemon=True
                    ).start()

                # Check if motion detection is enabled
                if self.bot_handler and not self.bot_handler.is_motion_enabled():
                    continue

                # Check sensors
                if self.sensors and self.sensors.radar.is_initialized:
                    motion_detected = self.sensors.radar.check_motion()

                    # Update status LED
                    self.sensors.set_led(motion_detected)

                    # Process motion event
                    self._process_motion(motion_detected)

            except Exception as e:
                logger.error(f"Loop iteration error: {e}")

    def _process_motion(self, motion_detected: bool) -> None:
        """
        Process motion detection events.

        Args:
            motion_detected: True if motion is currently detected
        """
        current_time = time.time()
        motion_state_changed = (motion_detected != self._prev_motion_state)
        self._prev_motion_state = motion_detected

        if motion_detected:
            self._last_motion_time = current_time

            # Trigger light on motion start
            if motion_state_changed:
                self._trigger_light_control()

            # Handle video recording
            if self.bot_handler and self.bot_handler.is_video_recording_enabled():
                self._handle_video_recording(current_time)

            # Handle InfluxDB logging
            self._handle_influx_logging(motion_detected, motion_state_changed, current_time)

            # Send motion notification (throttled)
            if motion_state_changed:
                cooldown = self.config.motion_message_cooldown
                if current_time - self._last_motion_message_time > cooldown:
                    self.telegram.send_text("Motion detected by LD2420 radar sensor")
                    self._last_motion_message_time = current_time

            # Push motion start to Firebase
            if motion_state_changed and self.firebase:
                threading.Thread(
                    target=self._push_firebase_status,
                    daemon=True
                ).start()

        else:
            # Motion stopped
            if motion_state_changed:
                if self.influx:
                    self.influx.log_motion_state(False)
                self._motion_stable_start = 0
                if self.firebase:
                    threading.Thread(
                        target=self._push_firebase_status,
                        daemon=True
                    ).start()

            # Check if recording should stop
            self._check_stop_recording(current_time)

    def _trigger_light_control(self) -> None:
        """Activate light on motion during night hours."""
        current_time = time.time()
        current_hour = datetime.now().hour

        # Only during night (6PM - 8AM)
        if not (current_hour < 8 or current_hour >= 18):
            return

        # Check cooldown
        if current_time - self._last_light_activation < self.config.light_cooldown:
            return

        # Respect manual override: if user turned it off within 2 minutes, skip
        if current_time - self._living_room_manual_off_time < 120:
            logger.debug('Motion trigger: living room manual override active — skipping auto-ON')
            return

        self._last_light_activation = current_time

        def activate():
            try:
                if self.mqtt_bridge and self.mqtt_bridge.is_connected:
                    if self.mqtt_bridge.send_lobby_relay(True):
                        return
                # HTTP fallback — used until ESP01 firmware supports MQTT
                success, response = self.esp.send_to_lobby("lighton")
                if success:
                    logger.debug(f"Light activated (HTTP): {response}")
            except Exception as e:
                logger.error(f"Light activation error: {e}")

        threading.Thread(target=activate, daemon=True).start()

    def _poll_relay_heartbeat(self) -> None:
        """Poll ESP01 relay at 192.168.1.85 and push status to Firebase."""
        try:
            state = self.esp.get_relay_state()
            reachable = state is not None
            relay_on = (state == 'ON') if reachable else False
            msg = f"ESP01 Relay: {state}" if reachable else "ESP01 Relay: OFFLINE"
            logger.info(f"Relay heartbeat — {msg}")

            # Push to Firebase whenever we get a response (or failure)
            if self.firebase:
                self.firebase.push_lobby_relay_status(
                    reachable=reachable,
                    relay_on=relay_on,
                )

            if state != self._last_relay_state:
                self._last_relay_state = state
        except Exception as e:
            logger.error(f"Relay heartbeat error: {e}")

    def _on_firebase_light_cmd(self, cmd: bool) -> None:
        """
        Handle a living room light command delivered by the Firebase SSE stream.

        Debounces rapid bursts (e.g. Firebase replaying queued ON/OFF/ON on
        reconnect) — only the final command in a 400 ms window is executed.
        Dedup runs at execute-time so reconnect replays of the current state
        are silently skipped without resetting the debounce window.
        """
        logger.info(f'Firebase stream: living room {"ON" if cmd else "OFF"}')

        # Cancel any pending execution and arm a fresh timer
        if self._light_cmd_timer is not None:
            self._light_cmd_timer.cancel()

        self._light_cmd_timer = threading.Timer(
            0.4, self._execute_light_cmd, args=(cmd,)
        )
        self._light_cmd_timer.daemon = True
        self._light_cmd_timer.start()

    def _execute_light_cmd(self, cmd: bool) -> None:
        """Execute the debounced light command — skip if already in this state."""
        if cmd == self._last_living_room_cmd:
            logger.debug(f'Light cmd {"ON" if cmd else "OFF"} skipped — same as last executed')
            return
        if not cmd and self._last_living_room_cmd:
            # User explicitly turned it off while ON — block motion re-activation
            self._living_room_manual_off_time = time.time()
            logger.debug('Living room manual OFF recorded — motion auto-ON suppressed for 2 min')
        elif cmd:
            # User explicitly turned it ON — clear the manual override immediately
            self._living_room_manual_off_time = 0
            logger.debug('Living room manual ON — motion auto-ON override cleared')
        self._last_living_room_cmd = cmd
        logger.info(f'Executing light command: {"ON" if cmd else "OFF"}')

        try:
            if self.mqtt_bridge and self.mqtt_bridge.is_connected:
                if self.mqtt_bridge.send_lobby_relay(cmd):
                    # Confirmation arrives via MQTT state topic → _on_lobby_mqtt_state
                    return
            # HTTP fallback
            if not self.esp:
                return
            if cmd:
                success, _ = self.esp.lobby_light_on()
            else:
                success, _ = self.esp.lobby_light_off()
            if self.firebase:
                confirmed = success and cmd
                self.firebase.set_light_confirmed('living_room', confirmed)
                self.firebase.set_light_state('living_room', confirmed)
            logger.info(
                f'Living room confirmed (HTTP): {"ON" if (success and cmd) else "OFF"}'
            )
        except Exception as e:
            logger.warning(f'Light command execute error: {e}')

    def _on_door_open(self) -> None:
        """Called by reed switch edge interrupt when door opens."""
        now = datetime.now().strftime('%d/%m/%y %I:%M:%S %p')
        msg = f"Door OPENED — {now}"
        logger.info(msg)
        if self.telegram:
            self.telegram.send_text(f"🚪 {msg}")
        if self.aws_door:
            self.aws_door.publish_door_event("open")

    def _on_door_close(self) -> None:
        """Called by reed switch edge interrupt when door closes."""
        now = datetime.now().strftime('%d/%m/%y %I:%M:%S %p')
        msg = f"Door CLOSED — {now}"
        logger.info(msg)
        if self.telegram:
            self.telegram.send_text(f"🔒 {msg}")
        if self.aws_door:
            self.aws_door.publish_door_event("closed")

    def _on_lobby_mqtt_state(self, payload: str) -> None:
        """
        Handle an ESP01 Lobby state message arriving over MQTT.

        Updates Firebase relay status and living_room/confirmed so the
        Android app sees the result of the last MQTT command.
        """
        import json as _json
        relay_on = False
        try:
            data = _json.loads(payload)
            relay_on = bool(data.get('relay', False))
        except (ValueError, AttributeError):
            relay_on = payload.upper() == 'ON'

        # Set dedup flag before Firebase write so the SSE command stream skips
        # re-execution when it sees the updated state value.
        self._last_living_room_cmd = relay_on

        def _update() -> None:
            if self.firebase:
                self.firebase.push_lobby_relay_status(
                    reachable=True, relay_on=relay_on
                )
                self.firebase.set_light_confirmed('living_room', relay_on)
                self.firebase.set_light_state('living_room', relay_on)
        threading.Thread(target=_update, daemon=True).start()

    def _on_porch_mqtt_state(self, payload: str) -> None:
        """
        Handle an ESP01-RELAY (porch relay) state message arriving over MQTT.

        Updates /devices/esp01_relay and lights/lobby2/confirmed so the
        Android app reflects the actual physical relay state.
        """
        relay_on = payload.upper() == 'ON'
        self._porch_light_on = relay_on
        self._porch_reachable = True
        logger.info(f'Porch relay state via MQTT: {"ON" if relay_on else "OFF"}')

        self._last_porch_cmd = relay_on

        def _update() -> None:
            if self.firebase:
                self.firebase.push_porch_relay_status(
                    reachable=True, relay_on=relay_on
                )
                self.firebase.set_light_confirmed('lobby', relay_on)
                self.firebase.set_light_state('lobby', relay_on)
        threading.Thread(target=_update, daemon=True).start()

    def _on_porch_availability_changed(self, available: bool) -> None:
        """
        Handle ESP01-RELAY MQTT availability changes (LWT online / offline).

        Previously this callback was never wired into MqttBridge, so Firebase
        never learned when the porch relay went offline or came back.  The app
        therefore either kept showing ONLINE (stale reachable=True) or showed
        the red dot only after the 3-minute lastSeen timeout expired.

        Now:
          - "online"  → reachable=True, relay_on=last known state → green dot
          - "offline" → reachable=False, relay_on=False → red dot immediately
        """
        self._porch_reachable = available
        logger.info(f'Porch relay availability: {"online" if available else "offline"}')

        def _update() -> None:
            if self.firebase:
                self.firebase.push_porch_relay_status(
                    reachable=available,
                    relay_on=self._porch_light_on if available else False,
                )
        threading.Thread(target=_update, daemon=True).start()

    def _on_radar_motion(self, payload: str) -> None:
        """
        Handle a radar motion event from ESP32-RADAR via MQTT.

        During night hours (18:00–06:00) a motion=ON event turns on the
        porch relay.  A motion=OFF event starts a 5-minute countdown; if no
        further ON arrives within that window the relay is turned off.
        """
        motion_on = payload.upper() == 'ON'
        current_hour = datetime.now().hour
        is_night = (current_hour >= 18) or (current_hour < 6)

        if motion_on:
            # Cancel any pending off timer
            if self._porch_light_off_timer is not None:
                self._porch_light_off_timer.cancel()
                self._porch_light_off_timer = None

            if is_night and self.mqtt_bridge:
                # Respect manual override: if user turned porch OFF within 2 min, skip
                if time.time() - self._porch_manual_off_time < 120:
                    logger.debug('Radar motion: porch manual override active — skipping auto-ON')
                    return
                logger.info('Radar motion ON (night) → porch relay ON')
                self.mqtt_bridge.send_porch_relay(True)
        else:
            # Motion stopped — schedule light off after 5 minutes
            if self._porch_light_on:
                logger.info('Radar motion OFF → porch light off in 5 min')

                def _turn_off() -> None:
                    if self.mqtt_bridge:
                        logger.info('Porch light off timer fired')
                        self.mqtt_bridge.send_porch_relay(False)
                    self._porch_light_off_timer = None

                self._porch_light_off_timer = threading.Timer(300.0, _turn_off)
                self._porch_light_off_timer.daemon = True
                self._porch_light_off_timer.start()

    def _on_firebase_porch_light_cmd(self, cmd: bool) -> None:
        """
        Handle a porch light command from the Firebase SSE stream (lights/lobby2/state).

        Debounces rapid bursts, then sends the final command to ESP01-RELAY via MQTT.
        """
        logger.info(f'Firebase stream: porch light {"ON" if cmd else "OFF"}')

        if self._porch_cmd_timer is not None:
            self._porch_cmd_timer.cancel()

        self._porch_cmd_timer = threading.Timer(
            0.4, self._execute_porch_cmd, args=(cmd,)
        )
        self._porch_cmd_timer.daemon = True
        self._porch_cmd_timer.start()

    def _execute_porch_cmd(self, cmd: bool) -> None:
        """Execute the debounced porch relay command."""
        if cmd == self._last_porch_cmd:
            logger.debug(f'Porch cmd {"ON" if cmd else "OFF"} skipped — same as last')
            return
        if not cmd and self._porch_light_on:
            # User explicitly turned it off while ON — block radar re-activation
            self._porch_manual_off_time = time.time()
            logger.debug('Porch manual OFF recorded — radar auto-ON suppressed for 2 min')
        elif cmd:
            # User explicitly turned it ON — clear the manual override immediately
            self._porch_manual_off_time = 0
            logger.debug('Porch manual ON — radar auto-ON override cleared')
        self._last_porch_cmd = cmd
        logger.info(f'Executing porch command: {"ON" if cmd else "OFF"}')

        try:
            if self.mqtt_bridge and self.mqtt_bridge.is_connected:
                self.mqtt_bridge.send_porch_relay(cmd)
                # Confirmation arrives via MQTT porch state → _on_porch_mqtt_state
            # No HTTP fallback for porch: ESP01-RELAY's own HTTP poll handles it
        except Exception as e:
            logger.warning(f'Porch command execute error: {e}')

    # ------------------------------------------------------------------
    # ESP32-LP-RLY (L-Porch-Light) callbacks
    # ------------------------------------------------------------------

    def _on_lp_rly_mqtt_state(self, payload: str) -> None:
        """
        Handle ESP32-LP-RLY relay state arriving over MQTT.

        Updates /devices/ESP32-LP-RLY/ and lights/lower_porch_light/confirmed
        so the app switch reflects the actual physical relay state.
        """
        relay_on = payload.upper() == 'ON'
        self._lp_rly_light_on = relay_on
        self._lp_rly_reachable = True
        logger.info(f'LP-RLY state via MQTT: {"ON" if relay_on else "OFF"}')

        self._last_lp_rly_cmd = relay_on

        def _update() -> None:
            if self.firebase:
                self.firebase.push_lp_rly_status(reachable=True, relay_on=relay_on)
                self.firebase.set_light_confirmed('lower_porch_light', relay_on)
                self.firebase.set_light_state('lower_porch_light', relay_on)
        threading.Thread(target=_update, daemon=True).start()

    def _on_lp_rly_availability_changed(self, available: bool) -> None:
        """
        Handle ESP32-LP-RLY MQTT LWT (online / offline).

        Immediately marks the Firebase device node reachable/unreachable
        so the app switch shows the correct dot colour without waiting.
        """
        self._lp_rly_reachable = available
        logger.info(f'LP-RLY availability: {"online" if available else "offline"}')

        def _update() -> None:
            if self.firebase:
                self.firebase.push_lp_rly_status(
                    reachable=available,
                    relay_on=self._lp_rly_light_on if available else False,
                )
        threading.Thread(target=_update, daemon=True).start()

    def _on_firebase_lp_rly_cmd(self, cmd: bool) -> None:
        """
        Handle an L-Porch-Light command from the Firebase SSE stream.

        Debounces rapid bursts (Firebase reconnect replays), then sends
        the final ON/OFF to ESP32-LP-RLY via MQTT.
        """
        logger.info(f'Firebase stream: L-Porch-Light {"ON" if cmd else "OFF"}')

        if self._lp_rly_cmd_timer is not None:
            self._lp_rly_cmd_timer.cancel()

        self._lp_rly_cmd_timer = threading.Timer(
            0.4, self._execute_lp_rly_cmd, args=(cmd,)
        )
        self._lp_rly_cmd_timer.daemon = True
        self._lp_rly_cmd_timer.start()

    def _execute_lp_rly_cmd(self, cmd: bool) -> None:
        """Execute the debounced LP-RLY relay command."""
        if cmd == self._last_lp_rly_cmd:
            logger.debug(f'LP-RLY cmd {"ON" if cmd else "OFF"} skipped — same as last')
            return
        self._last_lp_rly_cmd = cmd
        logger.info(f'Executing LP-RLY command: {"ON" if cmd else "OFF"}')

        try:
            if self.mqtt_bridge and self.mqtt_bridge.is_connected:
                self.mqtt_bridge.send_lp_rly_relay(cmd)
                # Confirmation arrives via MQTT state → _on_lp_rly_mqtt_state
        except Exception as e:
            logger.warning(f'LP-RLY command execute error: {e}')

    def _on_lp_rly_ota_status(self, payload: str) -> None:
        """Forward ESP32-LP-RLY OTA progress JSON to Telegram."""
        try:
            import json as _json
            data = _json.loads(payload)
            status   = data.get('status', '')
            version  = data.get('version', '')
            progress = data.get('progress', '')
            message  = data.get('message', '')
            text = f"LP-RLY OTA [{status}] v{version} {progress}% — {message}".strip(' —')
            logger.info(f'LP-RLY OTA: {text}')
            if self.telegram:
                threading.Thread(
                    target=self.telegram.send_text, args=(text,), daemon=True
                ).start()
        except Exception as e:
            logger.warning(f'LP-RLY OTA status parse error: {e}  raw={payload}')

    def _on_lp_rly_telegram(self, message: str) -> None:
        """Forward a Telegram message published by ESP32-LP-RLY firmware."""
        logger.info(f'LP-RLY telegram: {message}')
        if self.telegram:
            threading.Thread(
                target=self.telegram.send_text, args=(message,), daemon=True
            ).start()

    def _push_firebase_status(self) -> None:
        """Push current Pi status snapshot to Firebase."""
        if not self.firebase:
            return
        try:
            recording = bool(self.recorder and self.recorder.is_recording)
            self.firebase.push_pi_status(
                motion=self._prev_motion_state,
                recording=recording,
            )
        except Exception as e:
            logger.warning(f"Firebase status push error: {e}")

    def _handle_video_recording(self, current_time: float) -> None:
        """Handle video recording logic."""
        if not self.recorder:
            return

        if not self.recorder.is_recording:
            self._recording_start_time = current_time
            filename = time.strftime("%d%b%y_%H%M%S")
            self.recorder.start_recording(filename)
            logger.info(f"Recording started: {filename}")
        else:
            self.recorder.extend_recording()

    def _check_stop_recording(self, current_time: float) -> None:
        """Check if recording should be stopped."""
        if not self.recorder or not self.recorder.is_recording:
            return

        # Never auto-stop a manual recording — it runs its full duration
        if self.recorder.is_manual_recording:
            return

        time_since_motion = current_time - self._last_motion_time
        total_duration = self.recorder.recording_duration  # use recorder's own timer
        min_dur = self.config.video.min_duration
        max_dur = self.config.video.max_duration

        should_stop = (
            (time_since_motion > self.config.video.motion_timeout and total_duration >= min_dur) or
            total_duration >= max_dur
        )

        if should_stop:
            self.recorder.stop_recording()
            reason = "max duration" if total_duration >= max_dur else "no motion"
            logger.info(f"Recording stopped: {reason} (duration: {total_duration:.1f}s)")

    def _handle_influx_logging(
        self,
        motion_detected: bool,
        state_changed: bool,
        current_time: float
    ) -> None:
        """Handle InfluxDB motion logging with stability check."""
        if not self.influx:
            return

        if self._motion_stable_start == 0:
            self._motion_stable_start = current_time
            return

        # Wait for 2 seconds of stable motion, then log once per motion event
        if current_time - self._motion_stable_start >= 2:
            self.influx.log_motion_state(motion_detected)
            self._motion_stable_start = float('inf')  # prevent re-firing until motion resets

    def _on_recording_complete(self, result: RecordingResult) -> None:
        """Callback when video recording completes."""
        if result.success:
            if self.bot_handler and self.bot_handler.is_bot_video_enabled():
                self.telegram.send_video(result.file_path)
                logger.info(f"Video sent: {result.file_path} ({result.duration:.1f}s)")
        else:
            if self.telegram:
                self.telegram.send_text(f"Recording error: {result.error_message}")

    def _on_disk_cleanup(self, files_removed: int, space_freed: float) -> None:
        """Callback when disk cleanup occurs."""
        if self.telegram:
            msg = (
                f"Automatic cleanup:\n"
                f"Removed {files_removed} files\n"
                f"Freed {space_freed:.1f} MB"
            )
            self.telegram.send_text(msg)

    def _send_startup_message(self) -> None:
        """Send startup notification."""
        now = datetime.now()
        formatted_time = now.strftime('%A %d/%m/%y %I:%M:%S %p')

        msg = (
            f"Raspberry Pi 5 Home Automation\n"
            f"{'=' * 30}\n"
            f"Version: {self.config.script_version}\n"
            f"Updated: {self.config.last_updated}\n"
            f"Started: {formatted_time}"
        )

        logger.info(msg)
        if self.telegram:
            self.telegram.send_text(msg)

            # Camera status
            camera_status = "OK" if (self.recorder and self.recorder._camera) else "Not available"
            self.telegram.send_text(f"Camera: {camera_status}")

        if self.firebase:
            self._push_firebase_status()

    def _on_local_api_cmd(self, light_id: str, state: bool) -> None:
        """
        Route a command from the local LAN API to the correct execute method.

        Bypasses the Firebase debounce timer — the execute methods themselves
        deduplicate consecutive identical commands via _last_*_cmd guards.
        """
        logger.info(f'Local API: {light_id} → {"ON" if state else "OFF"}')
        if light_id == 'living_room':
            self._execute_light_cmd(state)
        elif light_id == 'lobby':
            self._execute_porch_cmd(state)
        elif light_id == 'lower_porch_light':
            self._execute_lp_rly_cmd(state)
        else:
            logger.warning(f'Local API: unknown light_id "{light_id}"')

    def _get_local_device_states(self) -> dict:
        """
        Return current device states for GET /devices.

        Uses the same field names as Firebase /devices/ so the Flutter app can
        parse both sources with identical code.  lastSeen is always 'now' since
        the Pi is live when this is called.
        """
        import time as _time
        now_ms = int(_time.time() * 1000)

        lr_state = self._last_relay_state
        lr_reachable = isinstance(lr_state, str)  # 'ON' / 'OFF' → online; sentinel/None → offline

        return {
            'RASPI-5': {
                'reachable': True,
                'lastSeen': now_ms,
            },
            'ESP01-LL-RLY': {
                'reachable': lr_reachable,
                'relay': lr_state == 'ON',
                'lastSeen': now_ms,
            },
            'esp01_relay': {
                'reachable': self._porch_reachable,
                'relay': self._porch_light_on,
                'lastSeen': now_ms,
            },
            'ESP32-LP-RLY': {
                'reachable': self._lp_rly_reachable,
                'relay': self._lp_rly_light_on,
                'lastSeen': now_ms,
            },
        }

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        self._running = False
        self._shutdown_event.set()

    def cleanup(self) -> None:
        """Cleanup all resources."""
        logger.info("Cleaning up resources...")

        if self.recorder:
            logger.info("Closing video recorder...")
            self.recorder.close()

        if self.sensors:
            logger.info("Cleaning up sensors...")
            self.sensors.cleanup()

        if self.influx:
            logger.info("Closing InfluxDB connection...")
            self.influx.close()

        if self._light_cmd_timer is not None:
            self._light_cmd_timer.cancel()

        if self._lp_rly_cmd_timer is not None:
            self._lp_rly_cmd_timer.cancel()

        if self.scheduler:
            logger.info("Stopping light scheduler...")
            self.scheduler.stop()

        if self.local_api:
            logger.info("Stopping local API server...")
            self.local_api.stop()

        if self.aws_door:
            logger.info("Disconnecting AWS IoT door publisher...")
            self.aws_door.disconnect()

        if self.mqtt_bridge:
            logger.info("Stopping MQTT bridge...")
            self.mqtt_bridge.stop()

        if self.firebase:
            logger.info("Marking Firebase offline...")
            self.firebase.mark_offline()

        if self.telegram:
            logger.info("Stopping Telegram handler...")
            self.telegram.stop()

        logger.info("Cleanup complete. Goodbye!")


def main():
    """Application entry point."""
    print(f"\nRaspberry Pi 5 Home Automation System v{__version__}")
    print("=" * 50)

    controller = RaspberryPiController()
    controller.start()


if __name__ == "__main__":
    main()
