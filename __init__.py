"""
Raspberry Pi 4 Home Automation System

A modular home automation system for Raspberry Pi featuring:
- Motion detection (LD2420 radar, PIR, MMS sensors)
- Video recording with automatic cloud upload
- Telegram bot for remote control
- ESP device integration (lights, door sensors)
- InfluxDB logging for sensor data

Modules:
    config: Configuration management
    telegram_handler: Telegram bot messaging
    sensors: Sensor management (radar, GPIO)
    video_recorder: Camera and video recording
    esp_devices: ESP8266/ESP32 device control
    influxdb_logger: InfluxDB data logging
    bot_commands: Telegram bot command handling
    main: Main application controller

Quick Start:
    from main import RaspberryPiController

    controller = RaspberryPiController()
    controller.start()

For configuration, set environment variables or modify config.py:
    TELEGRAM_BOT_TOKEN: Your Telegram bot token
    TELEGRAM_CHAT_ID: Your Telegram chat ID
    INFLUXDB_TOKEN: InfluxDB authentication token
"""

__version__ = '26.01.27'
__author__ = 'Raspberry Pi Home Automation'
__license__ = 'MIT'

# Convenience imports
from config import config, AppConfig, load_config
from telegram_handler import TelegramHandler
from sensors import SensorManager, SensorState
from video_recorder import VideoRecorder, RecordingResult
from esp_devices import ESPDeviceManager
from influxdb_logger import InfluxDBLogger
from bot_commands import BotCommandHandler

__all__ = [
    # Version info
    '__version__',
    '__author__',
    '__license__',

    # Configuration
    'config',
    'AppConfig',
    'load_config',

    # Core classes
    'TelegramHandler',
    'SensorManager',
    'SensorState',
    'VideoRecorder',
    'RecordingResult',
    'ESPDeviceManager',
    'InfluxDBLogger',
    'BotCommandHandler',
]
