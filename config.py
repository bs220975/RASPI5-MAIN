"""
Configuration Module for Raspberry Pi 5 Home Automation System

This module provides centralized configuration management with:
- Environment variable support for sensitive data
- Validation of configuration values
- Type-safe dataclass-based configuration
- Easy customization through config files or environment

Environment Variables:
    TELEGRAM_BOT_TOKEN: Telegram bot API token
    TELEGRAM_CHAT_ID: Telegram chat ID for notifications
    INFLUXDB_TOKEN: InfluxDB authentication token
    INFLUXDB_URL: InfluxDB server URL
    INFLUXDB_ORG: InfluxDB organization
    INFLUXDB_BUCKET: InfluxDB bucket name

Usage:
    from config import config
    print(config.telegram.bot_token)
    print(config.video.max_duration)
"""
import os
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional
from pathlib import Path

__all__ = [
    'TelegramConfig',
    'InfluxDBConfig',
    'ESPDeviceConfig',
    'GPIOConfig',
    'VideoConfig',
    'RadarConfig',
    'FirebaseConfig',
    'MqttConfig',
    'AppConfig',
    'config',
    'load_config',
]

logger = logging.getLogger(__name__)


def _get_env(key: str, default: str = '') -> str:
    """Get environment variable with fallback to default."""
    return os.environ.get(key, default)


def _get_env_int(key: str, default: int) -> int:
    """Get environment variable as integer with fallback."""
    try:
        return int(os.environ.get(key, str(default)))
    except ValueError:
        logger.warning(f"Invalid integer for {key}, using default: {default}")
        return default


def _get_env_float(key: str, default: float) -> float:
    """Get environment variable as float with fallback."""
    try:
        return float(os.environ.get(key, str(default)))
    except ValueError:
        logger.warning(f"Invalid float for {key}, using default: {default}")
        return default


@dataclass(frozen=False)
class TelegramConfig:
    """
    Telegram bot configuration.

    Attributes:
        bot_token: Telegram Bot API token from @BotFather
        chat_id: Target chat ID for sending messages
        retry_attempts: Number of retry attempts for failed messages
        retry_delay: Delay between retries in seconds
        rate_limit_delay: Minimum delay between messages in seconds
    """
    bot_token: str = field(
        default_factory=lambda: _get_env(
            'TELEGRAM_BOT_TOKEN',
            '6457653240:AAHxGnjzebcVb9gwXJ9LyEar0ZYZ2USFCyw'
        )
    )
    chat_id: str = field(
        default_factory=lambda: _get_env('TELEGRAM_CHAT_ID', '6825638285')
    )
    retry_attempts: int = 3
    retry_delay: int = 5
    rate_limit_delay: float = 1.0

    def validate(self) -> bool:
        """Validate configuration values."""
        if not self.bot_token or len(self.bot_token) < 20:
            logger.error("Invalid Telegram bot token")
            return False
        if not self.chat_id:
            logger.error("Missing Telegram chat ID")
            return False
        return True


@dataclass(frozen=False)
class InfluxDBConfig:
    """
    InfluxDB 2.x configuration.

    Attributes:
        url: InfluxDB server URL
        token: Authentication token
        org: Organization name
        bucket: Default bucket for writes
        timeout: Connection timeout in milliseconds
    """
    url: str = field(
        default_factory=lambda: _get_env('INFLUXDB_URL', 'http://[::1]:8086')
    )
    token: str = field(
        default_factory=lambda: _get_env('INFLUXDB_TOKEN', 'mytoken')
    )
    org: str = field(
        default_factory=lambda: _get_env('INFLUXDB_ORG', 'pi5org')
    )
    bucket: str = field(
        default_factory=lambda: _get_env('INFLUXDB_BUCKET', 'pi5data')
    )
    timeout: int = 10000

    # Legacy InfluxDB 1.x settings (for backward compatibility)
    legacy_address: str = 'localhost'
    legacy_port: int = 8086
    legacy_user: str = 'admin'
    legacy_password: str = 'admin'
    legacy_database: str = 'pi5data'

    def validate(self) -> bool:
        """Validate configuration values."""
        if not self.url:
            logger.error("Missing InfluxDB URL")
            return False
        if not self.token:
            logger.error("Missing InfluxDB token")
            return False
        return True


@dataclass(frozen=False)
class ESPDeviceConfig:
    """
    ESP device network configuration.

    Stores IP addresses and ports for all ESP8266/ESP32 devices.
    Format: 'device_name': 'ip_address:port'
    """
    devices: Dict[str, str] = field(default_factory=lambda: {
        'ESP01_Lobby':    '192.168.1.85',
        'ESP32_LP_RLY': '192.168.1.89:1089',   # ESP32-LP-RLY (L-Porch-Light)
        'ESP32_OLED':     '192.168.1.102:1020',
        'ESP32_GSM':      '192.168.1.91:9191',
        'ESP32_ENERGY':   '192.168.1.131:1031',
        'ESP8266_DHT':    '192.168.1.107:1007',
        'ESP32_Test':     '192.168.1.132:1032',
        'ESP01_Relay':    '192.168.1.85',
    })
    request_timeout: int = 5  # seconds

    @property
    def lobby_ip(self) -> str:
        """Get lobby ESP device IP:port."""
        return self.devices.get('ESP01_Lobby', '')

    @property
    def porch_ip(self) -> str:
        """Get LP porch relay IP:port (ESP32-LP-RLY)."""
        return self.devices.get('ESP32_LP_RLY', '')

    @property
    def oled_ip(self) -> str:
        """Get OLED ESP device IP:port."""
        return self.devices.get('ESP32_OLED', '')

    @property
    def gsm_ip(self) -> str:
        """Get GSM ESP device IP:port."""
        return self.devices.get('ESP32_GSM', '')

    def get_device_url(self, device_name: str, endpoint: str = '') -> Optional[str]:
        """
        Get full URL for a device endpoint.

        Args:
            device_name: Name of the device
            endpoint: Optional endpoint path

        Returns:
            Full URL or None if device not found
        """
        ip_port = self.devices.get(device_name)
        if not ip_port:
            return None
        return f"http://{ip_port}/{endpoint}" if endpoint else f"http://{ip_port}"


@dataclass(frozen=False)
class GPIOConfig:
    """
    GPIO pin configuration for Raspberry Pi.

    Uses BCM pin numbering (not BOARD).

    Attributes:
        mms_sensor_pin: Microwave motion sensor pin
        pir_sensor_pin: PIR motion sensor pin
        led_pin: Status LED pin
        reed_switch_pin: Door reed switch pin (GPIO 26, other leg to GND)
    """
    mms_sensor_pin: int = 27
    pir_sensor_pin: int = 25
    led_pin: int = 18
    reed_switch_pin: int = 26  # BCM GPIO 26, wired to GND; pull-up enabled internally

    def validate(self) -> bool:
        """Validate GPIO pin numbers are in valid range."""
        valid_pins = set(range(2, 28))  # BCM GPIO 2-27
        pins = [self.mms_sensor_pin, self.pir_sensor_pin, self.led_pin, self.reed_switch_pin]

        for pin in pins:
            if pin not in valid_pins:
                logger.error(f"Invalid GPIO pin: {pin}")
                return False

        if len(set(pins)) != len(pins):
            logger.error("Duplicate GPIO pins configured")
            return False

        return True


@dataclass(frozen=False)
class VideoConfig:
    """
    Video recording configuration.

    Attributes:
        video_dir: Directory to store recorded videos
        min_duration: Minimum video duration in seconds
        max_duration: Maximum video duration in seconds
        motion_timeout: Seconds to wait after motion stops
        bitrate: Video encoding bitrate
        disk_usage_threshold: Disk usage percentage to trigger cleanup
    """
    video_dir: str = '/home/pi5/raspi_camera_videos'
    min_duration: int = 10
    max_duration: int = 120
    motion_timeout: int = 10
    bitrate: int = 1_000_000
    disk_usage_threshold: float = 75.0

    def __post_init__(self):
        """Ensure video directory exists."""
        Path(self.video_dir).mkdir(parents=True, exist_ok=True)

    def validate(self) -> bool:
        """Validate video configuration."""
        if self.min_duration < 1:
            logger.error("min_duration must be at least 1 second")
            return False
        if self.max_duration < self.min_duration:
            logger.error("max_duration must be >= min_duration")
            return False
        if not 0 < self.disk_usage_threshold <= 100:
            logger.error("disk_usage_threshold must be between 0 and 100")
            return False
        return True


@dataclass(frozen=False)
class RadarConfig:
    """
    LD2420 radar sensor configuration.

    Attributes:
        port: Serial port path
        baud_rate: Serial baud rate
        motion_timeout: Seconds before motion state resets
        detection_min_cm: Minimum detection distance in cm
        detection_max_cm: Maximum detection distance in cm
        sensitivity_cm: Minimum distance change to trigger
        require_stable_readings: Consecutive readings required
    """
    port: str = '/dev/serial0'
    baud_rate: int = 115200
    motion_timeout: float = 2.0
    detection_min_cm: int = 50
    detection_max_cm: int = 450
    sensitivity_cm: int = 5
    require_stable_readings: int = 2

    def validate(self) -> bool:
        """Validate radar configuration."""
        if self.detection_min_cm >= self.detection_max_cm:
            logger.error("detection_min_cm must be < detection_max_cm")
            return False
        if self.sensitivity_cm < 1:
            logger.error("sensitivity_cm must be at least 1")
            return False
        return True


@dataclass
class FirebaseConfig:
    """
    Firebase Realtime Database configuration.

    No auth required — database rules allow public write on
    devices/, lights/, and commands/ nodes.
    """
    database_url: str = 'https://home-security-app-555cf-default-rtdb.asia-southeast1.firebasedatabase.app'
    project_id: str = 'home-security-app-555cf'
    request_timeout: int = 5        # seconds per HTTP call
    heartbeat_interval: int = 60    # seconds between Pi status pushes


@dataclass
class MqttConfig:
    """
    Local Mosquitto broker configuration.

    Set credentials via environment variables — never hardcode in source.

    Environment variables:
        MQTT_HOST: Broker hostname or IP (default: localhost)
        MQTT_PORT: Broker port (default: 1883)
        MQTT_USER: Username
        MQTT_PASS: Password
    """
    host: str = field(default_factory=lambda: _get_env('MQTT_HOST', 'localhost'))
    port: int = field(default_factory=lambda: _get_env_int('MQTT_PORT', 1883))
    username: str = field(default_factory=lambda: _get_env('MQTT_USER', 'mq'))
    password: str = field(default_factory=lambda: _get_env('MQTT_PASS', 'mq'))
    client_id: str = 'raspi5-bridge'
    keepalive: int = 60


@dataclass(frozen=False)
class AppConfig:
    """
    Main application configuration container.

    Aggregates all sub-configurations and provides application-wide settings.
    """
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    influxdb: InfluxDBConfig = field(default_factory=InfluxDBConfig)
    esp_devices: ESPDeviceConfig = field(default_factory=ESPDeviceConfig)
    gpio: GPIOConfig = field(default_factory=GPIOConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    radar: RadarConfig = field(default_factory=RadarConfig)
    firebase: FirebaseConfig = field(default_factory=FirebaseConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)

    # Application metadata
    script_version: str = 'V26.5.16'
    last_updated: str = '16 May 2026'

    # Paths
    log_file_path: str = '/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/logs/error_log.txt'
    pdf_file_path: str = '/home/pi5/esp32/python_raspi/Running_codes/DTH11_temperature_Humidity.pdf'
    image_file_path: str = '/home/pi5/esp32/python_raspi/Running_codes/temperature_humidity_plot.png'

    # Timing settings
    light_cooldown: int = 30  # seconds between light activations
    motion_message_cooldown: int = 120  # seconds between motion notifications
    relay_heartbeat_interval: int = 120  # seconds between ESP01 relay polls

    # Local API server (LAN fallback when Firebase is down)
    local_api_port: int = 5757

    def validate(self) -> bool:
        """Validate all configurations."""
        validators = [
            self.telegram.validate(),
            self.influxdb.validate(),
            self.gpio.validate(),
            self.video.validate(),
            self.radar.validate(),
        ]
        return all(validators)

    def setup_logging(self) -> None:
        """Configure application logging."""
        log_dir = Path(self.log_file_path).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            filename=self.log_file_path,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(name)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


def load_config() -> AppConfig:
    """
    Load and validate application configuration.

    Returns:
        Validated AppConfig instance

    Raises:
        ValueError: If configuration validation fails
    """
    cfg = AppConfig()

    if not cfg.validate():
        raise ValueError("Configuration validation failed. Check logs for details.")

    return cfg


# Global configuration instance
# Use load_config() for validated config, or access directly for quick use
config = AppConfig()
