"""
Firebase Realtime Database Logger for Raspberry Pi Home Automation System

Writes live status to the existing Firebase schema (no auth required —
database rules allow public read/write on these nodes):

    /devices/RASPI-4/   — Pi heartbeat (lastSeen, reachable, cpuTemp, …)
    /devices/esp01_relay/ — Relay status (lastSeen, reachable, relayState)
    /lights/live/         — Live motion & light state for the Android app

Phase 1 addition: start_command_stream() replaces the 1-second REST poll
with a Firebase RTDB SSE (Server-Sent Events) stream that delivers changes
in near-real time with a fraction of the read traffic.
"""
import json
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional, Dict, Any

import requests

logger = logging.getLogger(__name__)

_IST = timedelta(hours=5, minutes=30)


def _ms_now() -> int:
    """Current time as Unix milliseconds (matches existing Firebase schema)."""
    return int(time.time() * 1000)


def _cpu_temp() -> Optional[float]:
    """Read CPU temperature from Pi thermal zone."""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        return None


def _uptime_seconds() -> int:
    """Read system uptime in seconds."""
    try:
        with open('/proc/uptime') as f:
            return int(float(f.read().split()[0]))
    except Exception:
        return 0


class FirebaseLogger:
    """
    Pushes Pi and relay status to Firebase Realtime Database via REST API.

    No authentication needed — database rules allow public write on the
    relevant nodes (devices, lights, commands).

    Schema written:
        /devices/RASPI-4/   lastSeen, reachable, cpuTemp, uptime,
                              motionDetected, recording
        /devices/esp01_relay/ lastSeen, reachable, relayState
        /lights/live/         motionDetected, lobbyLight, lastUpdate

    Example:
        fb = FirebaseLogger(config.firebase)
        fb.connect()
        fb.push_pi_status(motion=True, recording=False)
        fb.push_relay_status(reachable=True, relay_on=True)
    """

    def __init__(self, config) -> None:
        self._db_url = config.database_url.rstrip('/')
        self._timeout = config.request_timeout
        self._stream_stop: Optional[threading.Event] = None
        self._stream_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Verify database is reachable with a lightweight GET."""
        try:
            resp = requests.get(
                f'{self._db_url}/devices/RASPI-4/reachable.json',
                timeout=self._timeout,
            )
            if resp.status_code == 200:
                logger.info('Firebase: connected (no auth)')
                return True
            logger.warning(f'Firebase connect probe: HTTP {resp.status_code}')
        except Exception as e:
            logger.warning(f'Firebase connect failed: {e}')
        return False

    def push_pi_status(
        self,
        motion: bool = False,
        recording: bool = False,
    ) -> bool:
        """
        Overwrite /devices/RASPI-4/ with current Pi snapshot.

        Args:
            motion:    Current radar motion state
            recording: Whether video is currently recording
        """
        data: Dict[str, Any] = {
            'lastSeen':       _ms_now(),
            'reachable':      True,
            'cpuTemp':        _cpu_temp(),
            'uptime':         _uptime_seconds(),
            'motionDetected': motion,
            'recording':      recording,
        }
        ok = self._patch('devices/RASPI-4', data)

        # Update lights/live so the Android app sees motion in real time
        self._patch('lights/live', {
            'motionDetected': motion,
            'lastUpdate':     _ms_now(),
        })

        return ok

    def push_lobby_relay_status(
        self,
        reachable: bool,
        relay_on: bool,
    ) -> bool:
        """
        Update /devices/ESP01-LL-RLY/ with the ESP01 at 192.168.1.85 status.

        Called by the Pi after each successful (or failed) poll of the relay.

        Args:
            reachable: True if the ESP01 responded to the HTTP poll
            relay_on:  True = relay ON, False = OFF (only valid if reachable)
        """
        data: Dict[str, Any] = {
            'lastSeen':   _ms_now(),
            'reachable':  reachable,
            'relayState': relay_on,
        }
        return self._patch('devices/ESP01-LL-RLY', data)

    def get_light_command(self, light_id: str) -> Optional[bool]:
        """
        Read lights/{light_id}/state from RTDB (app-commanded value).

        Returns:
            True = ON, False = OFF, None = read error / node absent
        """
        try:
            resp = requests.get(
                self._url(f'lights/{light_id}/state'),
                timeout=self._timeout,
            )
            if resp.status_code == 200:
                val = resp.json()
                if isinstance(val, bool):
                    return val
        except Exception as e:
            logger.debug(f'Firebase get_light_command({light_id}) error: {e}')
        return None

    def set_light_confirmed(self, light_id: str, confirmed: bool) -> bool:
        """
        Write lights/{light_id}/confirmed — tells the app the relay actually changed.

        Args:
            light_id:  Firebase light key e.g. 'living_room'
            confirmed: True = relay is ON, False = relay is OFF
        """
        return self._patch(f'lights/{light_id}', {'confirmed': confirmed})

    def mark_offline(self) -> bool:
        """Mark Pi as offline in Firebase on clean shutdown."""
        self.stop_command_stream()
        return self._patch('devices/RASPI-4', {
            'lastSeen':  _ms_now(),
            'reachable': False,
        })

    def start_command_stream(
        self, light_id: str, callback: Callable[[bool], None]
    ) -> None:
        """
        Start a background SSE listener on lights/{light_id}/state.

        Calls callback(bool) immediately when the value changes.  The stream
        reconnects automatically on network errors.  Replaces the 1-second
        REST polling loop that was previously used for light commands.

        Args:
            light_id: Firebase light key, e.g. 'living_room'
            callback: Called with True (ON) or False (OFF) on each change
        """
        if self._stream_thread and self._stream_thread.is_alive():
            return

        self._stream_stop = threading.Event()
        stop = self._stream_stop

        def _loop() -> None:
            url     = self._url(f'lights/{light_id}/state')
            headers = {'Accept': 'text/event-stream'}
            while not stop.is_set():
                try:
                    with requests.get(
                        url,
                        headers=headers,
                        stream=True,
                        timeout=(10, None),  # (connect_timeout, no_read_timeout)
                    ) as resp:
                        event_type: Optional[str] = None
                        # chunk_size=1 eliminates the default 512-byte read
                        # buffer so each SSE line is yielded the instant it
                        # arrives — no event batching delay.
                        for line in resp.iter_lines(chunk_size=1,
                                                    decode_unicode=True):
                            if stop.is_set():
                                return
                            if not line:
                                event_type = None
                                continue
                            if line.startswith('event:'):
                                event_type = line[6:].strip()
                            elif line.startswith('data:') and event_type in ('put', 'patch'):
                                try:
                                    payload = json.loads(line[5:].strip())
                                    data = payload.get('data')
                                    if isinstance(data, bool):
                                        callback(data)
                                except Exception:
                                    pass
                except Exception as e:
                    if not stop.is_set():
                        logger.warning(
                            f'Firebase stream (lights/{light_id}/state) error: {e}'
                            ' — reconnecting in 5s'
                        )
                        stop.wait(5)

        self._stream_thread = threading.Thread(
            target=_loop, name='FirebaseStream', daemon=True
        )
        self._stream_thread.start()
        logger.info(f'Firebase: SSE stream started for lights/{light_id}/state')

    def stop_command_stream(self) -> None:
        """Signal the SSE background thread to stop."""
        if self._stream_stop:
            self._stream_stop.set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f'{self._db_url}/{path}.json'

    def _patch(self, path: str, data: Dict) -> bool:
        """HTTP PATCH — partial update, preserves sibling fields."""
        try:
            resp = requests.patch(self._url(path), json=data, timeout=self._timeout)
            if resp.status_code == 200:
                return True
            logger.warning(f'Firebase PATCH {path} failed: HTTP {resp.status_code}')
        except Exception as e:
            logger.warning(f'Firebase PATCH {path} error: {e}')
        return False
