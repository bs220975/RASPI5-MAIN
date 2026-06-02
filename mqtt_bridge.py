"""
MQTT bridge between local Mosquitto and the Pi home automation system.

Manages four MQTT-native devices:
  ESP01-LL-RLY    (lower-lobby relay,  192.168.1.85)  — lower lobby light
  ESP01-UL-RLY    (upper-lobby relay,  192.168.1.111) — upper lobby light
  ESP32-LP-RLY  (LP porch relay,     192.168.1.89)  — L-Porch-Light app switch
  ESP32-RADAR     (radar sensor,       192.168.1.87)  — motion detection

Topics managed:
    home/esp01/lower-lobby/cmd/relay    Pi → ESP01-LL-RLY:   ON / OFF  (QoS 1)
    home/esp01/lower-lobby/state        ESP01-LL-RLY → Pi:   ON / OFF
    home/esp01/lower-lobby/availability ESP01-LL-RLY → Pi:   online / offline

    home/esp01/upper-lobby/cmd/relay    Pi → ESP01-UL-RLY:   ON / OFF  (QoS 1)
    home/esp01/upper-lobby/state        ESP01-UL-RLY → Pi:   ON / OFF
    home/esp01/upper-lobby/availability ESP01-UL-RLY → Pi:   online / offline

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

# ── Lower-Lobby relay (ESP01-LL-RLY at 192.168.1.85) ────────────────────────
_LL_CMD_TOPIC   = 'home/esp01/lower-lobby/cmd/relay'
_LL_STATE_TOPIC = 'home/esp01/lower-lobby/state'
_LL_AVAIL_TOPIC = 'home/esp01/lower-lobby/availability'

# ── Upper-Lobby relay (ESP01-UL-RLY at 192.168.1.111) ───────────────────────
_UL_CMD_TOPIC   = 'home/esp01/upper-lobby/cmd/relay'
_UL_STATE_TOPIC = 'home/esp01/upper-lobby/state'
_UL_AVAIL_TOPIC = 'home/esp01/upper-lobby/availability'

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
_FLOW_TEST_TOPIC        = 'home/test/upper-lobby/flow'          # ESP32 → Pi:    JSON {t1, device}
_ESP01_TEST_CMD_TOPIC   = 'home/test/upper-lobby/esp01/cmd'     # Pi → ESP01:    JSON {t1, t2, device}
_ESP01_TEST_ACK_TOPIC   = 'home/test/upper-lobby/esp01/ack'     # ESP01 → Pi:    JSON {t1, t2, t3, relay}
_RADAR_PI_STATUS_TOPIC  = 'home/test/radar/pi_status'           # Pi → ESP32:    JSON {step, ...}


class MqttBridge:
    """
    Manages the Pi's MQTT client session against local Mosquitto.

    Subscribes to ESP device state and availability topics.
    Publishes relay commands to lower-lobby and upper-lobby devices.

    Usage:
        bridge = MqttBridge(
            config.mqtt,
            on_ll_state=...,
            on_ul_state=...,
            on_radar_motion=...,
        )
        bridge.start()
        bridge.send_ll_relay(True)
        bridge.send_ul_relay(True)
        bridge.stop()
    """

    def __init__(
        self,
        config,
        on_ll_state: Optional[Callable[[str], None]] = None,
        on_ll_availability: Optional[Callable[[bool], None]] = None,
        on_ul_state: Optional[Callable[[str], None]] = None,
        on_ul_availability: Optional[Callable[[bool], None]] = None,
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
        self._on_ll_state           = on_ll_state
        self._on_ll_availability    = on_ll_availability
        self._on_ul_state           = on_ul_state
        self._on_ul_availability    = on_ul_availability
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
        self._ll_available = False
        self._ul_available = False
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
    def ll_available(self) -> bool:
        """True if ESP01-LL-RLY last published 'online'."""
        return self._ll_available

    @property
    def ul_available(self) -> bool:
        """True if ESP01-UL-RLY last published 'online'."""
        return self._ul_available

    @property
    def lp_rly_available(self) -> bool:
        """True if ESP32-LP-RLY last published 'online'."""
        return self._lp_rly_available

    def send_ll_relay(self, state: bool) -> bool:
        """Publish ON or OFF to the lower-lobby relay command topic (QoS 1)."""
        return self._publish(_LL_CMD_TOPIC, 'ON' if state else 'OFF')

    def send_ul_relay(self, state: bool) -> bool:
        """Publish ON or OFF to the upper-lobby relay command topic (QoS 1)."""
        return self._publish(_UL_CMD_TOPIC, 'ON' if state else 'OFF')

    def send_lp_rly_relay(self, state: bool) -> bool:
        """Publish ON or OFF to the ESP32-LP-RLY (L-Porch-Light) command topic (QoS 1)."""
        return self._publish(_LP_RLY_CMD_TOPIC, 'ON' if state else 'OFF')

    def send_radar_trigger(self) -> bool:
        """Publish TRIGGER to ESP32-RADAR cmd topic — ESP32 simulates motion ON/OFF."""
        return self._publish(_RADAR_CMD_TOPIC, 'TRIGGER')

    def send_esp01_test_cmd(self, payload: str) -> bool:
        """Publish flow-test JSON to ESP01-UL-RLY (Pi adds T2, ESP01 responds with T3 ack)."""
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
                (_LL_STATE_TOPIC,           1),
                (_LL_AVAIL_TOPIC,           1),
                (_UL_STATE_TOPIC,           1),
                (_UL_AVAIL_TOPIC,           1),
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
        self._ll_available = False
        self._ul_available = False
        self._lp_rly_available = False
        if rc != 0:
            logger.warning(
                f"MQTT bridge: unexpected disconnect rc={rc} — "
                "paho will reconnect automatically"
            )

    def _on_message(self, client, userdata, msg) -> None:
        topic   = msg.topic
        payload = msg.payload.decode('utf-8', errors='replace').strip()

        # ── Lower-Lobby relay (ESP01-LL-RLY) ────────────────────────────
        if topic == _LL_AVAIL_TOPIC:
            available = payload.lower() == 'online'
            self._ll_available = available
            logger.info(f"MQTT: lower-lobby availability = {payload}")
            if self._on_ll_availability:
                self._on_ll_availability(available)

        elif topic == _LL_STATE_TOPIC:
            logger.info(f"MQTT: lower-lobby state = {payload}")
            if self._on_ll_state:
                self._on_ll_state(payload)

        # ── Upper-Lobby relay (ESP01-UL-RLY) ────────────────────────────
        elif topic == _UL_AVAIL_TOPIC:
            available = payload.lower() == 'online'
            self._ul_available = available
            logger.info(f"MQTT: upper-lobby availability = {payload}")
            if self._on_ul_availability:
                self._on_ul_availability(available)

        elif topic == _UL_STATE_TOPIC:
            logger.info(f"MQTT: upper-lobby state = {payload}")
            if self._on_ul_state:
                self._on_ul_state(payload)

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
            logger.info(f"MQTT: flow test ack from ESP01-UL-RLY = {payload}")
            if self._on_esp01_test_ack:
                self._on_esp01_test_ack(payload)
