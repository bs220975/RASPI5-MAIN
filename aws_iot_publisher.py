"""
Lightweight AWS IoT Core publisher for door reed-switch events.
Uses paho-mqtt with mutual TLS (same certs as influx_aws_publish).
Maintains a persistent connection; reconnects automatically on drop.
"""
import json
import logging
import ssl
import time
import threading
import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

# ── AWS IoT endpoint (same as influx_aws_publish) ──────────────────────────
_ENDPOINT  = "a3m8azs2x620qd-ats.iot.us-east-1.amazonaws.com"
_PORT      = 8883
_CLIENT_ID = "RaspberryPi5-DoorPublisher"

_CERT_DIR  = "/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/aws_certs"
_CA_CERT   = f"{_CERT_DIR}/AmazonRootCA1.pem"
_CERT_FILE = f"{_CERT_DIR}/certificate.pem.crt"
_KEY_FILE  = f"{_CERT_DIR}/private.pem.key"

# ── Door number this Pi controls (change if wiring changes) ────────────────
DOOR_NUMBER = "1"   # → publishes to REED_DOOR/1 → FCM topic aws_door1


class AwsIoTPublisher:
    def __init__(self):
        self._lock          = threading.Lock()
        self._client        = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=_CLIENT_ID,
        )
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._connected     = False
        self._tls_done      = False  # tls_set() must only be called once per client
        self._loop_started  = False  # loop_start() must only be called once per client

    def connect(self) -> bool:
        try:
            if not self._tls_done:
                self._client.tls_set(
                    ca_certs=_CA_CERT,
                    certfile=_CERT_FILE,
                    keyfile=_KEY_FILE,
                    tls_version=ssl.PROTOCOL_TLSv1_2,
                )
                self._tls_done = True

            self._client.connect(_ENDPOINT, _PORT, keepalive=60)

            if not self._loop_started:
                self._client.loop_start()
                self._loop_started = True

            # Wait up to 5 s for the broker to confirm
            for _ in range(50):
                if self._connected:
                    break
                time.sleep(0.1)
            if self._connected:
                logger.info("AwsIoTPublisher: connected to AWS IoT")
            else:
                logger.warning("AwsIoTPublisher: connect timeout — will retry on publish")
            return self._connected
        except Exception as e:
            logger.error(f"AwsIoTPublisher: connect error: {e}")
            return False

    def publish_door_event(self, state: str) -> bool:
        """
        Publish a door open/close event to AWS IoT.
        state must be 'open' or 'closed'.
        Returns True if the message was queued successfully.
        """
        if state not in ("open", "closed"):
            logger.warning(f"AwsIoTPublisher: invalid state '{state}' — skipping")
            return False

        topic   = f"REED_DOOR/{DOOR_NUMBER}"
        payload = json.dumps({
            "state":     state,
            "timestamp": int(time.time()),
        })

        if not self._connected:
            logger.warning("AwsIoTPublisher: not connected — attempting reconnect")
            self.connect()

        try:
            with self._lock:
                result = self._client.publish(topic, payload, qos=1)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"AwsIoTPublisher: published {state} → {topic}")
                return True
            else:
                logger.error(f"AwsIoTPublisher: publish failed rc={result.rc}")
                return False
        except Exception as e:
            logger.error(f"AwsIoTPublisher: publish error: {e}")
            return False

    def disconnect(self):
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self._connected = (reason_code == 0)
        if self._connected:
            logger.info("AwsIoTPublisher: MQTT connected")
        else:
            logger.warning(f"AwsIoTPublisher: MQTT connect failed ({reason_code})")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._connected = False
        logger.warning(f"AwsIoTPublisher: MQTT disconnected ({reason_code})")
