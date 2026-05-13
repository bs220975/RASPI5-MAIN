"""
MQTT bridge between local Mosquitto and the Pi home automation system.

Phase 2 of the MQTT + Firebase bridge migration.  Handles the ESP01 Lobby
relay as the first MQTT-native device.  HTTP fallback in main.py remains
active until the ESP01 firmware is updated.

Topics managed:
    home/esp01/lobby/cmd/relay   — Pi publishes ON / OFF commands  (QoS 1)
    home/esp01/lobby/state       — ESP publishes relay state        (QoS 1)
    home/esp01/lobby/availability — ESP publishes online / offline  (QoS 1)
"""
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
    _PAHO_AVAILABLE = True
except ImportError:
    mqtt = None  # type: ignore
    _PAHO_AVAILABLE = False

_LOBBY_CMD_TOPIC   = 'home/esp01/lobby/cmd/relay'
_LOBBY_STATE_TOPIC = 'home/esp01/lobby/state'
_LOBBY_AVAIL_TOPIC = 'home/esp01/lobby/availability'


class MqttBridge:
    """
    Manages the Pi's MQTT client session against local Mosquitto.

    Subscribes to ESP01 Lobby state and availability topics.
    Publishes relay commands.  Designed to coexist with the HTTP fallback
    path during the firmware migration period.

    Usage:
        bridge = MqttBridge(config.mqtt,
                            on_lobby_state=...,
                            on_lobby_availability=...)
        bridge.start()
        bridge.send_lobby_relay(True)
        bridge.stop()
    """

    def __init__(
        self,
        config,
        on_lobby_state: Optional[Callable[[str], None]] = None,
        on_lobby_availability: Optional[Callable[[bool], None]] = None,
    ) -> None:
        self._config = config
        self._on_lobby_state = on_lobby_state
        self._on_lobby_availability = on_lobby_availability
        self._client: Optional[object] = None
        self._connected = False
        self._lobby_available = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Connect to the broker and start the paho background loop."""
        if not _PAHO_AVAILABLE:
            logger.error(
                "paho-mqtt not installed — MQTT bridge disabled. "
                "Run: pip install paho-mqtt"
            )
            return False
        try:
            self._client = mqtt.Client(client_id=self._config.client_id)
            if self._config.username:
                self._client.username_pw_set(
                    self._config.username, self._config.password
                )
            self._client.on_connect    = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message    = self._on_message
            self._client.reconnect_delay_set(min_delay=5, max_delay=60)
            self._client.connect(
                self._config.host, self._config.port, self._config.keepalive
            )
            self._client.loop_start()
            logger.info(
                f"MQTT bridge: connecting to "
                f"{self._config.host}:{self._config.port}"
            )
            return True
        except Exception as e:
            logger.error(f"MQTT bridge start failed: {e}")
            return False

    def stop(self) -> None:
        """Disconnect cleanly and stop the background loop."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def lobby_available(self) -> bool:
        """True if the ESP01 Lobby last published 'online' on its availability topic."""
        return self._lobby_available

    def send_lobby_relay(self, state: bool) -> bool:
        """
        Publish ON or OFF to the lobby relay command topic (QoS 1).

        Returns True if the message was accepted by paho, False otherwise.
        Callers should fall back to HTTP when this returns False.
        """
        if not self._connected or self._client is None:
            return False
        payload = 'ON' if state else 'OFF'
        result = self._client.publish(
            _LOBBY_CMD_TOPIC, payload, qos=1, retain=False
        )
        ok = result.rc == mqtt.MQTT_ERR_SUCCESS
        if ok:
            logger.info(f"MQTT: published {payload} -> {_LOBBY_CMD_TOPIC}")
        else:
            logger.warning(f"MQTT: publish failed rc={result.rc}")
        return ok

    # ------------------------------------------------------------------
    # Paho callbacks — called from the paho background thread
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self._connected = True
            logger.info("MQTT bridge: connected to broker")
            client.subscribe([
                (_LOBBY_STATE_TOPIC, 1),
                (_LOBBY_AVAIL_TOPIC, 1),
            ])
            logger.info("MQTT bridge: subscribed to lobby topics")
        else:
            logger.error(f"MQTT bridge: connection refused rc={rc}")

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected = False
        self._lobby_available = False
        if rc != 0:
            logger.warning(
                f"MQTT bridge: unexpected disconnect rc={rc} — "
                "paho will reconnect automatically"
            )

    def _on_message(self, client, userdata, msg) -> None:
        topic   = msg.topic
        payload = msg.payload.decode('utf-8', errors='replace').strip()

        if topic == _LOBBY_AVAIL_TOPIC:
            available = payload.lower() == 'online'
            self._lobby_available = available
            logger.info(f"MQTT: lobby availability = {payload}")
            if self._on_lobby_availability:
                self._on_lobby_availability(available)

        elif topic == _LOBBY_STATE_TOPIC:
            logger.info(f"MQTT: lobby state = {payload}")
            if self._on_lobby_state:
                self._on_lobby_state(payload)
