"""
Firebase Realtime Database Logger for Raspberry Pi Home Automation System

Writes live status to the existing Firebase schema (no auth required —
database rules allow public read/write on these nodes):

    /devices/RASPI-4/   — Pi heartbeat (lastSeen, reachable, cpuTemp, …)
    /devices/esp01_relay/ — Relay status (lastSeen, reachable, relayState)
    /lights/live/         — Live motion & light state for the Android app
"""
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

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
        return self._patch('devices/RASPI-4', {
            'lastSeen':  _ms_now(),
            'reachable': False,
        })

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
