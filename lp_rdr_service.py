#!/usr/bin/env python3
"""
lp_rdr_service.py — Lower-porch radar monitor (ESP32-LP-RDR1)

Subscribes to ESP32-LP-RDR1 motion events via MQTT.
On confirmed motion: sends Telegram notification and starts video recording.
On recording complete: sends video to Telegram.
Controlled via MQTT topic home/pi5/lp-rdr/cmd.

Run as: mybot-lp-rdr.service
"""
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time
from typing import Optional

from config import config
from telegram_handler import TelegramHandler
from video_recorder import VideoRecorder, RecordingResult

__version__ = '1.0.0'

logger = logging.getLogger(__name__)

_MOTION_TOPIC = 'home/pi5/lp-rdr/motion'  # ESP32 → Pi5 direct (Pi4-independent)
_CMD_TOPIC    = 'home/pi5/lp-rdr/cmd'     # VIDEO_ON | VIDEO_OFF | RECORD_<sec>

_LOG_ERROR = '/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/logs/lp_rdr_error.log'
_LOG_SVC   = '/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/logs/lp_rdr_service.log'


def _setup_logging() -> None:
    os.makedirs(os.path.dirname(_LOG_ERROR), exist_ok=True)
    fmt = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    fh = logging.handlers.RotatingFileHandler(
        _LOG_ERROR, maxBytes=1 * 1024 * 1024, backupCount=3
    )
    fh.setLevel(logging.WARNING)
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    root.addHandler(ch)


class LpRdrService:
    """
    Subscribes to ESP32-LP-RDR1 motion over MQTT and handles:
      - Telegram notification on confirmed motion
      - Video recording triggered by motion
      - Video sent to Telegram on recording complete
      - Control commands from main mybot service via MQTT
    """

    def __init__(self) -> None:
        self._shutdown = threading.Event()
        self._video_enabled: bool = True
        self._last_motion_time: float = 0
        self._last_notification_time: float = 0

        self._confirm_timer: Optional[threading.Timer] = None
        self._rec_stop_timer: Optional[threading.Timer] = None

        self.telegram: Optional[TelegramHandler] = None
        self.recorder: Optional[VideoRecorder] = None
        self._mqtt = None   # paho Client

    # ------------------------------------------------------------------
    # Init / teardown
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        try:
            import paho.mqtt.client as mqtt_lib
        except ImportError:
            logger.error('paho-mqtt not installed — run: pip install paho-mqtt')
            return False

        try:
            self.telegram = TelegramHandler(config.telegram)
            if not self.telegram.start():
                logger.warning('Telegram unavailable at startup — continuing without it')
                self.telegram = None
            else:
                logger.info('Telegram handler: OK')

            self.recorder = VideoRecorder(config.video)
            self.recorder.set_callbacks(
                on_complete=self._on_recording_complete,
                on_cleanup=self._on_disk_cleanup,
            )
            if self.recorder.initialize():
                logger.info('Video recorder: OK')
            else:
                logger.warning('Camera init failed — recording disabled')

            self._mqtt = mqtt_lib.Client(client_id='pi5-lp-rdr-monitor')
            self._mqtt.username_pw_set(config.mqtt.username, config.mqtt.password)
            self._mqtt.on_connect    = self._on_mqtt_connect
            self._mqtt.on_message    = self._on_mqtt_message
            self._mqtt.on_disconnect = self._on_mqtt_disconnect
            self._mqtt.connect(config.mqtt.host, config.mqtt.port, keepalive=60)
            self._mqtt.loop_start()
            logger.info(f'MQTT: connecting to {config.mqtt.host}:{config.mqtt.port}')

            return True

        except Exception as e:
            logger.error(f'Initialization failed: {e}')
            return False

    def _stop(self) -> None:
        logger.info('Stopping LP-RDR service...')
        for t in (self._confirm_timer, self._rec_stop_timer):
            if t:
                t.cancel()
        if self._mqtt:
            self._mqtt.loop_stop()
            self._mqtt.disconnect()
        if self.recorder:
            self.recorder.close()
        logger.info('LP-RDR service stopped')

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    def _on_mqtt_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            client.subscribe([(_MOTION_TOPIC, 1), (_CMD_TOPIC, 1)])
            logger.info('MQTT: connected — subscribed to motion + cmd topics')
        else:
            logger.error(f'MQTT: connect failed rc={rc}')

    def _on_mqtt_disconnect(self, client, userdata, rc) -> None:
        logger.warning(f'MQTT: disconnected rc={rc}')

    def _on_mqtt_message(self, client, userdata, msg) -> None:
        topic   = msg.topic
        payload = msg.payload.decode('utf-8', errors='replace').strip()
        if topic == _MOTION_TOPIC:
            self._handle_motion(payload)
        elif topic == _CMD_TOPIC:
            self._handle_cmd(payload)

    # ------------------------------------------------------------------
    # Motion handling
    # ------------------------------------------------------------------

    def _handle_motion(self, payload: str) -> None:
        motion_on = payload.upper() == 'ON'
        now = time.time()

        if motion_on:
            self._last_motion_time = now

            if self._rec_stop_timer:
                self._rec_stop_timer.cancel()
                self._rec_stop_timer = None

            if self._confirm_timer:
                self._confirm_timer.cancel()

            def _confirmed() -> None:
                self._confirm_timer = None
                self._do_motion_on()

            self._confirm_timer = threading.Timer(
                config.radar_confirm_window_s, _confirmed
            )
            self._confirm_timer.daemon = True
            self._confirm_timer.start()
            logger.debug(f'Motion ON pending — confirm in {config.radar_confirm_window_s}s')

        else:
            if self._confirm_timer:
                self._confirm_timer.cancel()
                self._confirm_timer = None
                logger.info('Motion OFF before confirm window — suppressed (likely EMI burst)')
                return

            def _stop() -> None:
                self._check_stop_recording(time.time())
                self._rec_stop_timer = None

            self._rec_stop_timer = threading.Timer(config.video.motion_timeout, _stop)
            self._rec_stop_timer.daemon = True
            self._rec_stop_timer.start()

    def _do_motion_on(self) -> None:
        now = time.time()

        if now - self._last_notification_time > config.motion_message_cooldown:
            if self.telegram:
                self.telegram.send_text('Motion detected by ESP32-LP-RDR1')
            self._last_notification_time = now

        if self._video_enabled:
            self._start_motion_recording(now)

    def _start_motion_recording(self, current_time: float) -> None:
        if not self.recorder:
            return
        if not self.recorder.is_recording:
            filename = time.strftime('%d%b%y_%H%M%S')
            self.recorder.start_recording(filename, trigger='radar')
            logger.info(f'Recording started: {filename}')
        else:
            self.recorder.extend_recording()

    def _check_stop_recording(self, current_time: float) -> None:
        if not self.recorder or not self.recorder.is_recording:
            return
        if self.recorder.is_manual_recording:
            return
        time_since_motion = current_time - self._last_motion_time
        total_dur = self.recorder.recording_duration
        should_stop = (
            (time_since_motion > config.video.motion_timeout
             and total_dur >= config.video.min_duration)
            or total_dur >= config.video.max_duration
        )
        if should_stop:
            self.recorder.stop_recording()
            reason = 'max duration' if total_dur >= config.video.max_duration else 'no motion'
            logger.info(f'Recording stopped: {reason} ({total_dur:.1f}s)')

    # ------------------------------------------------------------------
    # Control command handler (from main mybot via MQTT)
    # ------------------------------------------------------------------

    def _handle_cmd(self, payload: str) -> None:
        p = payload.strip().upper()
        if p == 'VIDEO_ON':
            self._video_enabled = True
            logger.info('LP-RDR: video recording enabled')
        elif p == 'VIDEO_OFF':
            self._video_enabled = False
            logger.info('LP-RDR: video recording disabled')
        elif p.startswith('RECORD_'):
            try:
                sec = int(p.split('_', 1)[1])
                sec = max(5, min(sec, 120))
                self._start_manual_recording(sec)
            except (IndexError, ValueError):
                logger.warning(f'LP-RDR: invalid RECORD cmd payload: {payload}')
        else:
            logger.warning(f'LP-RDR: unknown cmd: {payload}')

    def _start_manual_recording(self, duration: int) -> None:
        if not self.recorder:
            if self.telegram:
                self.telegram.send_text('Camera not available')
            return
        self.recorder.start_recording(max_duration=duration, manual=True)
        logger.info(f'Manual recording started: {duration}s')

    # ------------------------------------------------------------------
    # Recording callbacks
    # ------------------------------------------------------------------

    def _on_recording_complete(self, result: RecordingResult) -> None:
        if result.success:
            send = result.manual or self._video_enabled
            if send and self.telegram:
                if result.manual:
                    caption = f'Manual recording — {result.duration:.0f}s'
                else:
                    caption = f'ESP32-LP-RDR1 motion — {result.duration:.0f}s'
                self.telegram.send_video(result.file_path, caption=caption)
                logger.info(f'Video sent: {result.file_path} ({result.duration:.1f}s)')
        else:
            if self.telegram:
                label = 'Manual recording' if result.manual else 'Recording'
                self.telegram.send_text(f'{label} failed: {result.error_message}')

    def _on_disk_cleanup(self, files_removed: int, space_freed: float) -> None:
        if self.telegram:
            self.telegram.send_text(
                f'Automatic cleanup:\n'
                f'Removed {files_removed} video(s)\n'
                f'Space freed: {space_freed:.1f} MB'
            )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        def _sig(signum, frame):
            logger.info('Shutdown signal received')
            self._shutdown.set()

        signal.signal(signal.SIGTERM, _sig)
        signal.signal(signal.SIGINT, _sig)

        logger.info(f'LP-RDR service v{__version__} started')
        self._shutdown.wait()
        self._stop()


def main() -> None:
    _setup_logging()
    svc = LpRdrService()
    if not svc.initialize():
        sys.exit(1)
    svc.run()


if __name__ == '__main__':
    main()
