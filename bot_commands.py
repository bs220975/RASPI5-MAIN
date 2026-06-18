"""
Bot Commands Handler Module
Handles Telegram bot commands and user interactions
"""
import logging
import os
import socket
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional, Any

from config import AppConfig


@dataclass
class BotState:
    """Tracks the current state of bot-controlled features"""
    motion_enabled: bool = True
    video_recording_enabled: bool = True
    bot_video_enabled: bool = True
    drive_upload_enabled: bool = False
    start_time: float = field(default_factory=time.time)


class BotCommandHandler:
    """
    Handles Telegram bot commands.

    Provides a clean interface for processing bot commands and
    managing application state through the bot.

    Usage:
        handler = BotCommandHandler(config, telegram, esp_manager, recorder)
        bot.message_loop(handler.handle_message)
    """

    def __init__(
        self,
        config: AppConfig,
        telegram_handler: Any,  # TelegramHandler
        esp_manager: Any,  # ESPDeviceManager
        video_recorder: Any,  # VideoRecorder
        influx_logger: Optional[Any] = None,  # InfluxDBLogger
        sensor_manager: Optional[Any] = None,  # SensorManager
        mqtt_bridge: Optional[Any] = None  # MqttBridge
    ):
        self.config = config
        self.telegram = telegram_handler
        self.esp = esp_manager
        self.recorder = video_recorder
        self.influx = influx_logger
        self.sensors = sensor_manager
        self.mqtt_bridge = mqtt_bridge
        self.state = BotState()
        self._logger = logging.getLogger(__name__)

        # Command handlers registry
        self._commands: Dict[str, Callable] = self._register_commands()

    def _register_commands(self) -> Dict[str, Callable]:
        """Register all available commands"""
        return {
            '/display_commands': self._cmd_display_commands,
            '/script_runtime': self._cmd_script_runtime,
            '/script_filename': self._cmd_script_filename,

            # Video controls
            '/test_cam': self._cmd_test_cam,
            '/enable_botvideo': self._cmd_enable_bot_video,
            '/disable_botvideo': self._cmd_disable_bot_video,
            '/stop_video_rec': self._cmd_stop_video_rec,
            '/start_video_rec': self._cmd_start_video_rec,

            # Sensor controls
            '/activate_mms_sensor': self._cmd_activate_sensor,
            '/deactivate_mms_sensor': self._cmd_deactivate_sensor,

            # System info
            '/diskuse_status': self._cmd_disk_status,
            '/raspi_temprature': self._cmd_temperature,
            '/current_time': self._cmd_current_time,
            '/speedtest': self._cmd_speedtest,

            # Cloud sync
            '/sync_drive_to_pi': self._cmd_sync_to_pi,
            '/sync_pi_to_drive': self._cmd_sync_to_drive,
            '/enable_drive_upload': self._cmd_enable_drive_upload,
            '/disable_drive_upload': self._cmd_disable_drive_upload,

            # Storage management
            '/delete_disk_storage': self._cmd_delete_storage,

            # Light controls
            '/lobby_light_on': self._cmd_lobby_light_on,
            '/lobby_light_off': self._cmd_lobby_light_off,
            '/porch_light_on': self._cmd_porch_light_on,
            '/porch_light_off': self._cmd_porch_light_off,
            '/porch_light_timer_on': self._cmd_porch_timer_on,
            '/porch_light_timer_off': self._cmd_porch_timer_off,

            # ESP controls
            '/reset_esp01_lobby': self._cmd_reset_lobby,
            '/reset_esp8266_porch': self._cmd_reset_porch,
            '/oled': self._cmd_oled,
            '/esp_status_check': self._cmd_esp_status,

            # ESP01 relay
            '/relay_status': self._cmd_relay_status,
            '/relay_on': self._cmd_relay_on,
            '/relay_off': self._cmd_relay_off,

            # Reed switch
            '/reed_switch_on': self._cmd_reed_on,
            '/reed_switch_off': self._cmd_reed_off,

            # System controls
            '/reboot_raspi': self._cmd_reboot,
            '/script_restart': self._cmd_restart_script,

            # Data/Reports
            '/weather': self._cmd_weather,
            '/energy_table': self._cmd_energy_table,
            '/system_check': self._cmd_system_check,
            '/sensors_data_plot': self._cmd_sensors_plot,

            # Log files
            '/get_error_log': self._cmd_get_error_log,
            '/get_service_log': self._cmd_get_service_log,
            '/clear_logs': self._cmd_clear_logs,
        }

    def handle_message(self, msg: Dict) -> None:
        """
        Main message handler for the Telegram bot.

        Args:
            msg: Telegram message dictionary
        """
        try:
            # Only process commands when this Pi holds the floating VIP (192.168.1.100).
            # When Pi4 is MASTER it holds the VIP and handles all Telegram commands.
            # Dropping here prevents duplicate responses without stopping Pi5's
            # hardware duties (video recording, lobby lights, RADAR1 handling).
            vip_result = subprocess.run(
                ['ip', 'addr', 'show', 'wlan0'],
                capture_output=True, text=True, timeout=2
            )
            if '192.168.1.100' not in vip_result.stdout:
                return  # BACKUP: Pi4 is MASTER, let it handle commands

            chat_id = msg['chat']['id']
            command_text = msg.get('text', '')

            # Strip @botname suffix (e.g. /cmd@MyBot -> /cmd)
            if '@' in command_text:
                command_text = command_text.split('@')[0]

            # Normalize to lowercase so menu taps and manual typing both match
            command_text = command_text.lower()

            self._logger.info(f"Received command: {command_text}")

            # Handle /record_video with duration argument
            if command_text.startswith('/record_video'):
                self._cmd_record_video(command_text)
                return

            # Look up and execute command
            handler = self._commands.get(command_text)
            if handler:
                handler()
            else:
                self._logger.warning(f"Unknown command: {command_text}")

        except Exception as e:
            self._logger.error(f"Error handling message: {e}")
            self.telegram.send_text(f"Error: {e}")

    # === Command Implementations ===

    def _cmd_display_commands(self) -> None:
        """Display all available commands with HTML formatting"""
        msg = (
            "<b>🤖 Raspberry Pi 5 — Bot Commands</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            "<b>📹 Video Controls</b>\n"
            "/test_cam — Full flow test: trigger ESP32 → MQTT → Pi records → sends video\n"
            "/record_video &lt;sec&gt; — Record N sec, send to bot (default 10s, max 120s)\n"
            "/stop_video_rec — Stop sensor recording\n"
            "/start_video_rec — Start sensor recording\n"
            "/disable_botvideo — Disable auto video to bot\n"
            "/enable_botvideo — Enable auto video to bot\n\n"

            "<b>🚶 Sensor Controls</b>\n"
            "/deactivate_mms_sensor — Disable motion sensor\n"
            "/activate_mms_sensor — Enable motion sensor\n\n"

            "<b>💡 Lights</b>\n"
            "/lobby_light_on — Lobby light ON\n"
            "/lobby_light_off — Lobby light OFF\n"
            "/porch_light_on — Porch light ON\n"
            "/porch_light_off — Porch light OFF\n"
            "/porch_light_timer_on — Porch timer ON\n"
            "/porch_light_timer_off — Porch timer OFF\n\n"

            "<b>📡 ESP Devices</b>\n"
            "/esp_status_check — Check all ESP devices\n"
            "/reset_esp01_lobby — Reset lobby ESP\n"
            "/reset_esp8266_porch — Reset porch ESP\n"
            "/oled — ESP32 OLED display\n"
            "/reed_switch_on — Door sensor ON\n"
            "/reed_switch_off — Door sensor OFF\n"
            "/relay_status — Check ESP01 relay state\n"
            "/relay_on — Turn relay ON\n"
            "/relay_off — Turn relay OFF\n\n"

            "<b>☁️ Cloud Sync</b>\n"
            "/sync_drive_to_pi — Drive → Pi\n"
            "/sync_pi_to_drive — Pi → Drive\n"
            "/enable_drive_upload — Enable auto upload\n"
            "/disable_drive_upload — Disable auto upload\n\n"

            "<b>🗂️ Storage</b>\n"
            "/delete_disk_storage — Clear video storage\n\n"

            "<b>📊 System Info</b>\n"
            "/diskuse_status — Disk usage\n"
            "/raspi_temprature — CPU temperature\n"
            "/current_time — Current time\n"
            "/speedtest — Network speed test\n"
            "/system_check — System diagnostics\n"
            "/sensors_data_plot — Sensor data plot\n"
            "/weather — Weather report\n"
            "/energy_table — Energy data\n\n"

            "<b>📋 Logs</b>\n"
            "/get_error_log — Download error log file\n"
            "/get_service_log — Download service output log\n"
            "/clear_logs — Clear all log files\n\n"

            "<b>⚙️ System</b>\n"
            "/script_runtime — Script uptime\n"
            "/script_filename — Script name\n"
            "/script_restart — Restart script\n"
            "/reboot_raspi — Reboot Raspberry Pi\n"
        )
        self.telegram.send_text(msg, parse_mode='HTML')

    def get_commands_list(self) -> list:
        """Return commands list for Telegram setMyCommands menu registration"""
        return [
            {'command': 'display_commands',      'description': 'Show all commands'},
            {'command': 'script_runtime',         'description': 'Show script uptime'},
            {'command': 'script_filename',        'description': 'Show script name'},
            {'command': 'test_cam',               'description': 'Full flow: ESP32 → MQTT → Pi records → video sent'},
            {'command': 'record_video',           'description': 'Record video: /record_video <sec>'},
            {'command': 'stop_video_rec',         'description': 'Stop sensor recording'},
            {'command': 'start_video_rec',        'description': 'Start sensor recording'},
            {'command': 'disable_botvideo',       'description': 'Disable video to bot'},
            {'command': 'enable_botvideo',        'description': 'Enable video to bot'},
            {'command': 'deactivate_mms_sensor',  'description': 'Disable motion sensor'},
            {'command': 'activate_mms_sensor',    'description': 'Enable motion sensor'},
            {'command': 'lobby_light_on',         'description': 'Lobby light ON'},
            {'command': 'lobby_light_off',        'description': 'Lobby light OFF'},
            {'command': 'porch_light_on',         'description': 'Porch light ON'},
            {'command': 'porch_light_off',        'description': 'Porch light OFF'},
            {'command': 'porch_light_timer_on',   'description': 'Porch timer ON'},
            {'command': 'porch_light_timer_off',  'description': 'Porch timer OFF'},
            {'command': 'esp_status_check',       'description': 'Check all ESP devices'},
            {'command': 'reset_esp01_lobby',      'description': 'Reset lobby ESP'},
            {'command': 'reset_esp8266_porch',    'description': 'Reset porch ESP'},
            {'command': 'oled',                   'description': 'ESP32 OLED display'},
            {'command': 'reed_switch_on',         'description': 'Door sensor ON'},
            {'command': 'reed_switch_off',        'description': 'Door sensor OFF'},
            {'command': 'relay_status',           'description': 'Check ESP01 relay state'},
            {'command': 'relay_on',               'description': 'Turn relay ON'},
            {'command': 'relay_off',              'description': 'Turn relay OFF'},
            {'command': 'diskuse_status',         'description': 'Disk usage'},
            {'command': 'raspi_temprature',       'description': 'CPU temperature'},
            {'command': 'current_time',           'description': 'Current time'},
            {'command': 'speedtest',              'description': 'Network speed test'},
            {'command': 'system_check',           'description': 'System diagnostics'},
            {'command': 'sensors_data_plot',      'description': 'Sensor data plot'},
            {'command': 'sync_drive_to_pi',       'description': 'Sync Drive to Pi'},
            {'command': 'sync_pi_to_drive',       'description': 'Sync Pi to Drive'},
            {'command': 'enable_drive_upload',    'description': 'Enable auto upload'},
            {'command': 'disable_drive_upload',   'description': 'Disable auto upload'},
            {'command': 'delete_disk_storage',    'description': 'Clear video storage'},
            {'command': 'get_error_log',          'description': 'Download error log file'},
            {'command': 'get_service_log',        'description': 'Download service output log'},
            {'command': 'clear_logs',             'description': 'Clear all log files'},
            {'command': 'script_restart',         'description': 'Restart script'},
            {'command': 'reboot_raspi',           'description': 'Reboot Raspberry Pi'},
        ]

    def _cmd_script_runtime(self) -> None:
        """Show script runtime"""
        elapsed = time.time() - self.state.start_time
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        msg = f"Script runtime: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
        self.telegram.send_text(msg)

    def _cmd_script_filename(self) -> None:
        """Show script filename"""
        self.telegram.send_text(f"Script: {os.path.basename(__file__)}")

    def _cmd_enable_bot_video(self) -> None:
        """Enable sending video to bot"""
        if self.state.bot_video_enabled:
            self.telegram.send_text("Already enabled!")
            return
        self.state.bot_video_enabled = True
        self.telegram.send_text("Video sending to bot: ENABLED")

    def _cmd_disable_bot_video(self) -> None:
        """Disable sending video to bot"""
        if not self.state.bot_video_enabled:
            self.telegram.send_text("Already disabled!")
            return
        self.state.bot_video_enabled = False
        self.telegram.send_text("Video sending to bot: DISABLED")

    def _cmd_stop_video_rec(self) -> None:
        """Stop sensor-triggered video recording"""
        if not self.state.video_recording_enabled:
            self.telegram.send_text("Already disabled!")
            return
        self.state.video_recording_enabled = False
        self.telegram.send_text("Sensor video recording: DISABLED")

    def _cmd_start_video_rec(self) -> None:
        """Start sensor-triggered video recording"""
        if self.state.video_recording_enabled:
            self.telegram.send_text("Already enabled!")
            return
        self.state.video_recording_enabled = True
        self.telegram.send_text("Sensor video recording: ENABLED")

    def _cmd_activate_sensor(self) -> None:
        """Activate motion sensor"""
        if self.state.motion_enabled:
            self.telegram.send_text("Already activated!")
            return
        self.state.motion_enabled = True
        self.telegram.send_text("Motion sensor: ACTIVATED")

    def _cmd_deactivate_sensor(self) -> None:
        """Deactivate motion sensor"""
        if not self.state.motion_enabled:
            self.telegram.send_text("Already deactivated!")
            return
        self.state.motion_enabled = False
        self.telegram.send_text("Motion sensor: DEACTIVATED")

    def _cmd_disk_status(self) -> None:
        """Show disk usage status"""
        try:
            import psutil
            msg = "Disk Space:\n"
            for partition in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    msg += f"{partition.device}: {usage.percent}% used\n"
                except PermissionError:
                    continue
            self.telegram.send_text(msg)
        except Exception as e:
            self.telegram.send_text(f"Error: {e}")

    def _cmd_temperature(self) -> None:
        """Show Raspberry Pi temperature"""
        try:
            temp = os.popen("vcgencmd measure_temp").readline()
            self.telegram.send_text(f"Raspberry Pi {temp}")
        except Exception as e:
            self.telegram.send_text(f"Error: {e}")

    def _cmd_current_time(self) -> None:
        """Show current time"""
        now = datetime.now()
        formatted = now.strftime("%A, %d %B %Y %I:%M %p")
        self.telegram.send_text(formatted)

    def _cmd_speedtest(self) -> None:
        """Run network speed test"""
        try:
            self.telegram.send_text("Running speed test, please wait...")

            # Get local IP
            local_ip = ""
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
            except Exception:
                pass

            # Get Wi-Fi SSID (network name)
            ssid = ""
            try:
                r = subprocess.run(
                    ["iwgetid", "-r"], text=True, timeout=5,
                    capture_output=True
                )
                ssid = r.stdout.strip()
            except Exception:
                pass

            proc = subprocess.run(
                ["speedtest-cli"],
                text=True,
                timeout=120,
                capture_output=True
            )
            result = proc.stdout
            isp = ""
            server = ""
            ping = ""
            download = ""
            upload = ""
            for line in result.splitlines():
                if line.startswith("Testing from"):
                    isp = line.replace("Testing from ", "").replace("...", "").strip()
                elif line.startswith("Hosted by"):
                    server = line.replace("Hosted by ", "").strip()
                elif line.startswith("Download:"):
                    download = line.strip()
                elif line.startswith("Upload:"):
                    upload = line.strip()
                elif line.startswith("Ping:"):
                    ping = line.strip()

            if not download and not upload:
                error_detail = proc.stderr.strip() or result.strip() or "No output"
                self.telegram.send_text(f"Speed test failed: {error_detail}")
                return

            local_info = f"Local Network: {ssid}\nLocal IP: {local_ip}\n" if ssid or local_ip else ""
            msg = (
                f"{local_info}"
                f"Network: {isp}\n"
                f"Server: {server}\n"
                f"{ping}\n"
                f"{download}\n"
                f"{upload}"
            )
            self.telegram.send_text(msg)
        except subprocess.TimeoutExpired:
            self.telegram.send_text("Speed test timed out")
        except Exception as e:
            self.telegram.send_text(f"Error: {e}")

    def _cmd_sync_to_pi(self) -> None:
        """Sync from Google Drive to Pi"""
        self._run_rclone_sync("gdrive:/pi5_drive", "/home/pi5/pi5_drive")

    def _cmd_sync_to_drive(self) -> None:
        """Sync from Pi to Google Drive"""
        self._run_rclone_sync("/home/pi5/pi5_drive", "gdrive:/pi5_drive")

    def _run_rclone_sync(self, source: str, dest: str) -> None:
        """Run rclone sync command"""
        self.telegram.send_text("Starting sync...")
        try:
            result = subprocess.run(
                ["rclone", "sync", source, dest],
                timeout=900,
                check=True
            )
            self.telegram.send_text("Sync completed successfully!")
        except subprocess.TimeoutExpired:
            self.telegram.send_text("Sync timed out after 15 minutes")
        except subprocess.CalledProcessError as e:
            self.telegram.send_text(f"Sync failed: exit code {e.returncode}")
        except Exception as e:
            self.telegram.send_text(f"Sync error: {e}")

    def _cmd_enable_drive_upload(self) -> None:
        """Enable automatic drive upload"""
        if self.state.drive_upload_enabled:
            self.telegram.send_text("Already enabled!")
            return
        self.state.drive_upload_enabled = True
        self.telegram.send_text("Drive upload: ENABLED")

    def _cmd_disable_drive_upload(self) -> None:
        """Disable automatic drive upload"""
        if not self.state.drive_upload_enabled:
            self.telegram.send_text("Already disabled!")
            return
        self.state.drive_upload_enabled = False
        self.telegram.send_text("Drive upload: DISABLED")

    def _cmd_delete_storage(self) -> None:
        """Delete all recorded videos"""
        try:
            os.system('rm -rf /home/pi5/raspi_camera_videos/*')
            self.telegram.send_text("Video storage cleared")
            self._cmd_disk_status()
        except Exception as e:
            self.telegram.send_text(f"Error: {e}")

    def _cmd_lobby_light_on(self) -> None:
        """Turn on lobby light"""
        success, response = self.esp.lobby_light_on()
        self.telegram.send_text("Lobby Light: ON" if success else f"Error: {response}")

    def _cmd_lobby_light_off(self) -> None:
        """Turn off lobby light"""
        success, response = self.esp.lobby_light_off()
        self.telegram.send_text("Lobby Light: OFF" if success else f"Error: {response}")

    def _cmd_porch_light_on(self) -> None:
        """Turn on porch light"""
        success, response = self.esp.porch_light_on()
        self.telegram.send_text("Porch Light: ON" if success else f"Error: {response}")

    def _cmd_porch_light_off(self) -> None:
        """Turn off porch light"""
        success, response = self.esp.porch_light_off()
        self.telegram.send_text("Porch Light: OFF" if success else f"Error: {response}")

    def _cmd_porch_timer_on(self) -> None:
        """Enable porch light timer"""
        success, response = self.esp.send_to_porch("timeron")
        self.telegram.send_text("Porch timer: ON" if success else f"Error: {response}")

    def _cmd_porch_timer_off(self) -> None:
        """Disable porch light timer"""
        success, response = self.esp.send_to_porch("timeroff")
        self.telegram.send_text("Porch timer: OFF" if success else f"Error: {response}")

    def _cmd_reset_lobby(self) -> None:
        """Reset lobby ESP"""
        success, response = self.esp.send_to_lobby("reset")
        self.telegram.send_text("Reset sent to ESP01 Lobby" if success else f"Error: {response}")

    def _cmd_reset_porch(self) -> None:
        """Reset porch ESP"""
        success, response = self.esp.send_to_porch("reset")
        self.telegram.send_text("Reset sent to ESP8266 Porch" if success else f"Error: {response}")

    def _cmd_oled(self) -> None:
        """Send command to ESP32 OLED"""
        success, response = self.esp.send_to_oled("oled")
        if success:
            self.telegram.send_text(f"ESP32 OLED response:\n{response}")
        else:
            self.telegram.send_text(f"Error: {response}")

    def _cmd_esp_status(self) -> None:
        """Check and display ESP device status"""
        try:
            buffer = self.esp.get_status_image_buffer()
            self.telegram.send_image_buffer(buffer, "ESP Device Status")
        except Exception as e:
            self.telegram.send_text(f"Error: {e}")

    def _cmd_relay_status(self) -> None:
        """Check ESP01 relay state"""
        state = self.esp.get_relay_state()
        self.telegram.send_text(
            f"ESP01 Relay: {state}" if state is not None else "ESP01 Relay: OFFLINE"
        )

    def _cmd_relay_on(self) -> None:
        """Turn ESP01 relay ON"""
        success, response = self.esp.relay_on()
        self.telegram.send_text("Relay: ON" if success else f"Error: {response}")

    def _cmd_relay_off(self) -> None:
        """Turn ESP01 relay OFF"""
        success, response = self.esp.relay_off()
        self.telegram.send_text("Relay: OFF" if success else f"Error: {response}")

    def _cmd_reed_on(self) -> None:
        """Check reed switch state on GPIO pin 26"""
        if not self.sensors:
            self.telegram.send_text("Sensor manager not available")
            return
        state = self.sensors.gpio.read_reed()
        door_status = "CLOSED" if state else "OPEN"
        self.telegram.send_text(f"Reed switch (GPIO 26): {door_status}")

    def _cmd_reed_off(self) -> None:
        """Check reed switch state on GPIO pin 26"""
        if not self.sensors:
            self.telegram.send_text("Sensor manager not available")
            return
        state = self.sensors.gpio.read_reed()
        door_status = "CLOSED" if state else "OPEN"
        self.telegram.send_text(f"Reed switch (GPIO 26): {door_status}")

    def _cmd_reboot(self) -> None:
        """Reboot Raspberry Pi"""
        self.telegram.send_text("Rebooting Raspberry Pi...")
        time.sleep(1)
        subprocess.run(["sudo", "reboot"])

    def _cmd_restart_script(self) -> None:
        """Restart the Python script"""
        self.telegram.send_text("Restarting script...")
        os.system("sudo systemctl restart mybot.service")

    def _cmd_weather(self) -> None:
        """Get weather report (placeholder)"""
        self.telegram.send_text("Weather report feature - coming soon")

    def _cmd_energy_table(self) -> None:
        """Get energy table (placeholder)"""
        self.telegram.send_text("Energy table feature - coming soon")

    def _cmd_system_check(self) -> None:
        """Run system diagnostics (placeholder)"""
        self.telegram.send_text("System check feature - coming soon")

    def _cmd_sensors_plot(self) -> None:
        """Generate sensor data plot (placeholder)"""
        self.telegram.send_text("Sensor plot feature - coming soon")

    def _cmd_test_cam(self) -> None:
        """Send TRIGGER to ESP32-RADAR via MQTT → ESP32 publishes motion ON/OFF → Pi records and sends video."""
        if not self.mqtt_bridge:
            self.telegram.send_text("MQTT bridge not available")
            return
        if not self.mqtt_bridge.is_connected:
            self.telegram.send_text("MQTT not connected — cannot reach ESP32-RADAR")
            return
        ok = self.mqtt_bridge.send_radar_trigger()
        if ok:
            self.telegram.send_text(
                "Test trigger sent to ESP32-RADAR.\n"
                "ESP32 will publish motion ON → Pi records 5s → video sent here."
            )
        else:
            self.telegram.send_text("Failed to publish trigger — check MQTT broker")

    def _cmd_record_video(self, command_text: str) -> None:
        """Record video for specified duration"""
        try:
            # Parse duration from command
            parts = command_text.split()
            duration = 10  # Default
            if len(parts) > 1:
                try:
                    duration = int(parts[1])
                except ValueError:
                    self.telegram.send_text(f"Invalid duration. Using default: {duration}s")

            if duration > 120:
                self.telegram.send_text("Maximum duration is 120 seconds")
                duration = 120

            # Turn on light
            self.esp.lobby_light_on()

            # Record video — manual=True prevents motion-stop logic interrupting it
            self.telegram.send_text(f"Recording {duration}s video...")
            self.recorder.start_recording(max_duration=duration, manual=True)

        except Exception as e:
            self._logger.error(f"Record video error: {e}")
            self.telegram.send_text(f"Error: {e}")

    # === Log File Commands ===

    LOG_FILES = {
        'error':   '/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/logs/error_log.txt',
        'service': '/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/logs/Output_mybot_service.log',
        'stderr':  '/home/pi5/pi5_drive/Git_projects/RASPI5-MAIN/logs/Error_mybot_service.log',
    }
    MAX_TAIL_LINES = 100           # lines to send as text if file is too large
    MAX_SEND_BYTES = 45 * 1024 * 1024  # 45 MB — Telegram document limit is 50 MB

    def _send_log_file(self, log_path: str, label: str) -> None:
        """Send a log file to Telegram. Sends as document if small, last N lines if large."""
        if not os.path.exists(log_path):
            self.telegram.send_text(f"{label}: file not found")
            return

        size = os.path.getsize(log_path)

        if size == 0:
            self.telegram.send_text(f"{label}: log is empty (no errors recorded)")
            return

        size_kb = size / 1024
        if size > self.MAX_SEND_BYTES:
            # File too large — send last N lines as text instead
            try:
                result = subprocess.run(
                    ['tail', f'-{self.MAX_TAIL_LINES}', log_path],
                    capture_output=True, text=True, timeout=10
                )
                self.telegram.send_text(
                    f"{label} (last {self.MAX_TAIL_LINES} lines — file too large {size_kb:.0f} KB):\n\n"
                    f"<pre>{result.stdout[-3500:]}</pre>",
                    parse_mode='HTML'
                )
            except Exception as e:
                self.telegram.send_text(f"Error reading {label}: {e}")
        else:
            self.telegram.send_document(log_path, caption=f"{label} ({size_kb:.1f} KB)")

    def _cmd_get_error_log(self) -> None:
        """Send the application error log file"""
        self._send_log_file(self.LOG_FILES['error'], 'Error Log')

    def _cmd_get_service_log(self) -> None:
        """Send the service output log file"""
        self._send_log_file(self.LOG_FILES['service'], 'Service Output Log')

    def _cmd_clear_logs(self) -> None:
        """Clear all log files remotely"""
        try:
            cleared = []
            for label, path in self.LOG_FILES.items():
                if os.path.exists(path):
                    open(path, 'w').close()
                    cleared.append(os.path.basename(path))
            self.telegram.send_text(f"Logs cleared:\n" + "\n".join(f"- {f}" for f in cleared))
        except Exception as e:
            self.telegram.send_text(f"Error clearing logs: {e}")

    # === State Access Methods ===

    def is_motion_enabled(self) -> bool:
        """Check if motion detection is enabled"""
        return self.state.motion_enabled

    def is_video_recording_enabled(self) -> bool:
        """Check if video recording is enabled"""
        return self.state.video_recording_enabled

    def is_bot_video_enabled(self) -> bool:
        """Check if sending video to bot is enabled"""
        return self.state.bot_video_enabled

    def is_drive_upload_enabled(self) -> bool:
        """Check if drive upload is enabled"""
        return self.state.drive_upload_enabled
