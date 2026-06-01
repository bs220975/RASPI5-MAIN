"""
MQTT bridge between local Mosquitto and the Pi home automation system.

Manages four MQTT-native devices:
  ESP01-LL-RLY    (lobby relay,      192.168.1.85)  — lobby light
  ESP01-RELAY     (porch relay,      192.168.1.111) — porch / entrance light
  ESP32-LP-RLY  (LP porch relay,   192.168.1.89)  — L-Porch-Light app switch
  ESP32-RADAR     (radar sensor,     192.168.1.87)  — motion detection

Topics managed:
    home/esp01/lobby/cmd/relay          Pi → ESP01-LL-RLY:   ON / OFF  (QoS 1)
    home/esp01/lobby/state              ESP01-LL-RLY → Pi:   ON / OFF
    home/esp01/lobby/availability       ESP01-LL-RLY → Pi:   online / offline

    home/esp01/porch/cmd/relay          Pi → ESP01-RELAY:    ON / OFF  (QoS 1)
    home/esp01/porch/state              ESP01-RELAY → Pi:    ON / OFF
    home/esp01/porch/availability       ESP01-RELAY → Pi:    online / offline

    home/switches/L-Porch-Light/cmd          Pi → ESP32-LP-RLY: ON / OFF  (QoS 1)
    home/switches/L-Porch-Light/state        ESP32-LP-RLY → Pi: ON / OFF
    home/switches/L-Porch-Light/availability ESP32-LP-RLY → Pi: online / offline
    home/esp32/lp-rly/ota/status           ESP32-LP-RLY → Pi: OTA progress JSON
    home/esp32/lp-rly/telegram             ESP32-LP-RLY → Pi: plain-text Telegram msg

    home/esp32/radar2/motion            ESP32-RADAR → Pi:    ON / OFF
    home/esp32/radar2/availability      ESP32-RADAR → Pi:    online / offline
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

# ── Lobby relay (ESP01-LL-RLY at 192.168.1.85) ─────────────────────────────
_LOBBY_CMD_TOPIC   = 'home/esp01/lobby/cmd/relay'
_LOBBY_STATE_TOPIC = 'home/esp01/lobby/state'
_LOBBY_AVAIL_TOPIC = 'home/esp01/lobby/availability'

# ── Porch relay (ESP01-RELAY at 192.168.1.111) ──────────────────────────────
_PORCH_CMD_TOPIC   = 'home/esp01/porch/cmd/relay'
_PORCH_STATE_TOPIC = 'home/esp01/porch/state'
_PORCH_AVAIL_TOPIC = 'home/esp01/porch/availability'

# ── LP Porch relay (ESP32-LP-RLY at 192.168.1.89) — app switch L-Porch-Light
_LP_RLY_CMD_TOPIC        = 'home/switches/L-Porch-Light/cmd'
_LP_RLY_STATE_TOPIC      = 'home/switches/L-Porch-Light/state'
_LP_RLY_AVAIL_TOPIC      = 'home/switches/L-Porch-Light/availability'
_LP_RLY_OTA_STATUS_TOPIC = 'home/esp32/lp-rly/ota/status'
_LP_RLY_TELEGRAM_TOPIC   = 'home/esp32/lp-rly/telegram'

# ── Radar sensor (ESP32-RADAR at 192.168.1.87) ──────────────────────────────
_RADAR_MOTION_TOPIC = 'home/esp32/radar2/motion'
_RADAR_AVAIL_TOPIC  = 'home/esp32/radar2/availability'
_RADAR_CMD_TOPIC    = 'home/esp32/radar2/cmd'          # Pi → ESP32: TRIGGER

# ── Flow test (/testflow command chain) ─────────────────────────────────────
_FLOW_TEST_TOPIC        = 'home/test/porch/flow'          # ESP32 → Pi:    JSON {t1, device}
_ESP01_TEST_CMD_TOPIC   = 'home/test/porch/esp01/cmd'     # Pi → ESP01:    JSON {t1, t2, device}
_ESP01_TEST_ACK_TOPIC   = 'home/test/porch/esp01/ack'     # ESP01 → Pi:    JSON {t1, t2, t3, relay}
_RADAR_PI_STATUS_TOPIC  = 'home/test/radar/pi_status'     # Pi → ESP32:    JSON {step, ...}


class MqttBridge:
    """
    Manages the Pi's MQTT client session against local Mosquitto.

    Subscribes to ESP device state and availability topics.
    Publishes relay commands to lobby and porch devices.

    Usage:
        bridge = MqttBridge(
            config.mqtt,
            on_lobby_state=...,
            on_porch_state=...,
            on_radar_motion=...,
        )
        bridge.start()
        bridge.send_lobby_relay(True)
        bridge.send_porch_relay(True)
        bridge.stop()
    """

    def __init__(
        self,
        config,
        on_lobby_state: Optional[Callable[[str], None]] = None,
        on_lobby_availability: Optional[Callable[[bool], None]] = None,
        on_porch_state: Optional[Callable[[str], None]] = None,
        on_porch_availability: Optional[Callable[[bool], None]] = None,
        on_lp_rly_state: Optional[Callable[[str], None]] = None,
        on_lp_rly_availability: Optional[Callable[[bool], None]] = None,
        on_lp_rly_ota_status: Optional[Callable[[str], None]] = None,
        on_lp_rly_telegram: Optional[Callable[[str], None]] = None,
        on_radar_motion: Optional[Callable[[str], None]] = None,
        on_radar_availability: Optional[Callable[[bool], None]] = None,
        on_flow_test: Optional[Callable[[str], None]] = None,
        on_esp01_test_ack: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._config = config
        self._on_lobby_state        = on_lobby_state
        self._on_lobby_availability = on_lobby_availability
        self._on_porch_state        = on_porch_state
        self._on_porch_availability = on_porch_availability
        self._on_lp_rly_state        = on_lp_rly_state
        self._on_lp_rly_availability = on_lp_rly_availability
        self._on_lp_rly_ota_status   = on_lp_rly_ota_status
        self._on_lp_rly_telegram     = on_lp_rly_telegram
        self._on_radar_motion       = on_radar_motion
        self._on_radar_availability = on_radar_availability
        self._on_flow_test          = on_flow_test
        self._on_esp01_test_ack     = on_esp01_test_ack
        self._client: Optional[object] = None
        self._connected = False
        self._lobby_available = False
        self._porch_available = False
        self._lp_rly_available = False

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
        """True if ESP01-LL-RLY last published 'online'."""
        return self._lobby_available

    @property
    def porch_available(self) -> bool:
        """True if ESP01-RELAY last published 'online'."""
        return self._porch_available

    @property
    def lp_rly_available(self) -> bool:
        """True if ESP32-LP-RLY last published 'online'."""
        return self._lp_rly_available

    def send_lobby_relay(self, state: bool) -> bool:
        """Publish ON or OFF to the lobby relay command topic (QoS 1)."""
        return self._publish(_LOBBY_CMD_TOPIC, 'ON' if state else 'OFF')

    def send_porch_relay(self, state: bool) -> bool:
        """Publish ON or OFF to the porch relay command topic (QoS 1)."""
        return self._publish(_PORCH_CMD_TOPIC, 'ON' if state else 'OFF')

    def send_lp_rly_relay(self, state: bool) -> bool:
        """Publish ON or OFF to the ESP32-LP-RLY (L-Porch-Light) command topic (QoS 1)."""
        return self._publish(_LP_RLY_CMD_TOPIC, 'ON' if state else 'OFF')

    def send_radar_trigger(self) -> bool:
        """Publish TRIGGER to ESP32-RADAR cmd topic — ESP32 simulates motion ON/OFF."""
        return self._publish(_RADAR_CMD_TOPIC, 'TRIGGER')

    def send_esp01_test_cmd(self, payload: str) -> bool:
        """Publish flow-test JSON to ESP01 (Pi adds T2, ESP01 responds with T3 ack)."""
        return self._publish(_ESP01_TEST_CMD_TOPIC, payload)

    def send_pi_flow_status(self, payload: str) -> bool:
        """Publish Pi flow-test status back to ESP32-RADAR for Telegram reporting."""
        return self._publish(_RADAR_PI_STATUS_TOPIC, payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _publish(self, topic: str, payload: str) -> bool:
        if not self._connected or self._client is None:
            return False
        result = self._client.publish(topic, payload, qos=1, retain=False)
        ok = result.rc == mqtt.MQTT_ERR_SUCCESS
        if ok:
            logger.info(f"MQTT: published {payload} -> {topic}")
        else:
            logger.warning(f"MQTT: publish failed rc={result.rc} topic={topic}")
        return ok

    # ------------------------------------------------------------------
    # Paho callbacks — called from the paho background thread
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self._connected = True
            logger.info("MQTT bridge: connected to broker")
            client.subscribe([
                (_LOBBY_STATE_TOPIC,   1),
                (_LOBBY_AVAIL_TOPIC,   1),
                (_PORCH_STATE_TOPIC,   1),
                (_PORCH_AVAIL_TOPIC,   1),
                (_LP_RLY_STATE_TOPIC,       1),
                (_LP_RLY_AVAIL_TOPIC,       1),
                (_LP_RLY_OTA_STATUS_TOPIC,  1),
                (_LP_RLY_TELEGRAM_TOPIC,    1),
                (_RADAR_MOTION_TOPIC,       1),
                (_RADAR_AVAIL_TOPIC,        1),
                (_FLOW_TEST_TOPIC,          1),
                (_ESP01_TEST_ACK_TOPIC,     1),
            ])
            logger.info("MQTT bridge: subscribed to all device topics")
        else:
            logger.error(f"MQTT bridge: connection refused rc={rc}")

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected = False
        self._lobby_available = False
        self._porch_available = False
        self._lp_rly_available = False
        if rc != 0:
            logger.warning(
                f"MQTT bridge: unexpected disconnect rc={rc} — "
                "paho will reconnect automatically"
            )

    def _on_message(self, client, userdata, msg) -> None:
        topic   = msg.topic
        payload = msg.payload.decode('utf-8', errors='replace').strip()

        # ── Lobby relay ──────────────────────────────────────────────────
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

        # ── Porch relay ──────────────────────────────────────────────────
        elif topic == _PORCH_AVAIL_TOPIC:
            available = payload.lower() == 'online'
            self._porch_available = available
            logger.info(f"MQTT: porch availability = {payload}")
            if self._on_porch_availability:
                self._on_porch_availability(available)

        elif topic == _PORCH_STATE_TOPIC:
            logger.info(f"MQTT: porch state = {payload}")
            if self._on_porch_state:
                self._on_porch_state(payload)

        # ── LP Porch relay (ESP32-LP-RLY / L-Porch-Light) ─────────────
        elif topic == _LP_RLY_AVAIL_TOPIC:
            available = payload.lower() == 'online'
            self._lp_rly_available = available
            logger.info(f"MQTT: LP-RLY availability = {payload}")
            if self._on_lp_rly_availability:
                self._on_lp_rly_availability(available)

        elif topic == _LP_RLY_STATE_TOPIC:
            logger.info(f"MQTT: LP-RLY state = {payload}")
            if self._on_lp_rly_state:
                self._on_lp_rly_state(payload)

        elif topic == _LP_RLY_OTA_STATUS_TOPIC:
            logger.info(f"MQTT: LP-RLY OTA status = {payload}")
            if self._on_lp_rly_ota_status:
                self._on_lp_rly_ota_status(payload)

        elif topic == _LP_RLY_TELEGRAM_TOPIC:
            logger.info(f"MQTT: LP-RLY telegram = {payload}")
            if self._on_lp_rly_telegram:
                self._on_lp_rly_telegram(payload)

        # ── Radar motion ─────────────────────────────────────────────────
        elif topic == _RADAR_AVAIL_TOPIC:
            available = payload.lower() == 'online'
            logger.info(f"MQTT: radar availability = {payload}")
            if self._on_radar_availability:
                self._on_radar_availability(available)

        elif topic == _RADAR_MOTION_TOPIC:
            logger.info(f"MQTT: radar motion = {payload}")
            if self._on_radar_motion:
                self._on_radar_motion(payload)

        # ── Flow test chain ──────────────────────────────────────────────
        elif topic == _FLOW_TEST_TOPIC:
            logger.info(f"MQTT: flow test from ESP32 = {payload}")
            if self._on_flow_test:
                self._on_flow_test(payload)

        elif topic == _ESP01_TEST_ACK_TOPIC:
            logger.info(f"MQTT: flow test ack from ESP01 = {payload}")
            if self._on_esp01_test_ack:
                self._on_esp01_test_ack(payload)
