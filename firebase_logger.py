"""
Firebase Realtime Database Logger for Raspberry Pi Home Automation System

Writes live status to the existing Firebase schema (no auth required —
database rules allow public read/write on these nodes):

    /devices/RASPI-4/     — Pi heartbeat (lastSeen, reachable, cpuTemp, …)
    /devices/ESP01-LL-RLY/ — Lobby relay status (192.168.1.85)
    /devices/esp01_relay/  — Porch relay status (192.168.1.111)
    /lights/live/          — Live motion & light state for the Android app

start_command_stream() subscribes to a Firebase RTDB SSE stream for any
light node.  Multiple streams can run simultaneously (keyed by light_id).
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
        # Multiple SSE streams, keyed by light_id
        self._streams: dict = {}  # light_id -> (thread, stop_event)

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

    def push_porch_relay_status(
        self,
        reachable: bool,
        relay_on: bool,
    ) -> bool:
        """
        Update /devices/esp01_relay/ with the porch relay (192.168.1.111) status.

        Written by Pi when it receives ESP01-RELAY state via MQTT — replaces the
        heartbeat that ESP32-RADAR previously sent via checkESP01Health().
        """
        data: Dict[str, Any] = {
            'lastSeen':   _ms_now(),
            'reachable':  reachable,
            'relayState': relay_on,
        }
        return self._patch('devices/esp01_relay', data)

    def push_lp_rly_status(
        self,
        reachable: bool,
        relay_on: bool,
    ) -> bool:
        """
        Update /devices/ESP8266-LP-RLY/ with the LP porch relay status.

        Called whenever the Pi receives state or availability from the
        ESP8266-LP-RLY (192.168.1.89) via MQTT topic
        home/switches/L-Porch-Light/state or .../availability.
        The app reads this node to show the L-Porch-Light switch status.
        """
        data: Dict[str, Any] = {
            'lastSeen':   _ms_now(),
            'reachable':  reachable,
            'relayState': relay_on,
            'switchName': 'L-Porch-Light',
        }
        ok = self._patch('devices/ESP8266-LP-RLY', data)
        # Mirror confirmed state so the app switch reflects physical state
        self._patch('lights/L-Porch-Light', {'confirmed': relay_on, 'lastUpdate': _ms_now()})
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

        Calls callback(bool) when the value changes.  The stream reconnects
        automatically on network errors.  Multiple streams can run in parallel
        (e.g. 'living_room' and 'lobby2').  A second call with the same
        light_id is a no-op if that stream is already alive.

        Args:
            light_id: Firebase light key, e.g. 'living_room' or 'lobby2'
            callback: Called with True (ON) or False (OFF) on each change
        """
        existing = self._streams.get(light_id)
        if existing and existing[0].is_alive():
            return

        stop = threading.Event()

        def _loop() -> None:
            url     = self._url(f'lights/{light_id}/state')
            headers = {'Accept': 'text/event-stream'}
            while not stop.is_set():
                try:
                    with requests.get(
                        url,
                        headers=headers,
                        stream=True,
                        timeout=(10, None),
                    ) as resp:
                        event_type: Optional[str] = None
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

        thread = threading.Thread(
            target=_loop, name=f'FirebaseStream-{light_id}', daemon=True
        )
        self._streams[light_id] = (thread, stop)
        thread.start()
        logger.info(f'Firebase: SSE stream started for lights/{light_id}/state')

    def stop_command_stream(self) -> None:
        """Signal all SSE background streams to stop."""
        for _thread, stop in self._streams.values():
            stop.set()
        self._streams.clear()

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
