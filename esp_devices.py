"""
ESP Device Manager Module
Handles communication with ESP8266/ESP32 devices on the network
"""
import io
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

import requests
from PIL import Image, ImageDraw, ImageFont
from tabulate import tabulate

from config import ESPDeviceConfig


@dataclass
class ESPDeviceStatus:
    """Status information for an ESP device"""
    name: str
    ip_address: str
    port: str
    wifi_status: str
    internet_status: str
    wifi_signal_dbm: Optional[int]
    wifi_signal_percent: int
    is_connected: bool
    error_message: Optional[str] = None


class ESPDeviceManager:
    """
    Manages communication with ESP devices on the network.

    Provides methods to:
    - Query device status
    - Send commands to devices
    - Generate status reports

    Usage:
        manager = ESPDeviceManager(config)
        status = manager.get_device_status('ESP01_Lobby')
        manager.send_command('ESP01_Lobby', 'lighton')
    """

    def __init__(self, config: ESPDeviceConfig):
        self.config = config
        self._logger = logging.getLogger(__name__)
        self._timeout = 5  # Request timeout in seconds

    @staticmethod
    def signal_to_percentage(rssi: int) -> int:
        """Convert RSSI (dBm) to signal strength percentage"""
        if rssi <= -100:
            return 0
        elif rssi >= -50:
            return 100
        else:
            return 2 * (rssi + 100)

    def get_device_status(
        self,
        device_name: str,
        retries: int = 1
    ) -> ESPDeviceStatus:
        """
        Get status of a specific ESP device.

        Args:
            device_name: Name of the device (key in config)
            retries: Number of retry attempts

        Returns:
            ESPDeviceStatus with device information
        """
        device_ip = self.config.devices.get(device_name)
        if not device_ip:
            return ESPDeviceStatus(
                name=device_name,
                ip_address="Unknown",
                port="Unknown",
                wifi_status="Unknown",
                internet_status="Unknown",
                wifi_signal_dbm=None,
                wifi_signal_percent=0,
                is_connected=False,
                error_message=f"Device '{device_name}' not found in config"
            )

        for attempt in range(retries):
            try:
                response = requests.get(
                    f"http://{device_ip}/status",
                    timeout=self._timeout
                )

                if response.status_code == 200:
                    data = response.json()

                    # Support both old format (wifi_signal_dBm, ip_address, wifi_status,
                    # internet_status) and new ESP32 format (rssi, ip, mqtt, has_internet).
                    ip_address = (data.get("ip_address") or data.get("ip")
                                  or device_ip.split(':')[0])
                    port = (data.get("port")
                            or (device_ip.split(':')[1] if ':' in device_ip else "80"))

                    wifi_signal_dbm = data.get("wifi_signal_dBm") or data.get("rssi")

                    wifi_status = data.get("wifi_status")
                    if wifi_status is None:
                        ssid = data.get("ssid")
                        mqtt_state = data.get("mqtt")
                        if ssid:
                            wifi_status = ssid
                        elif mqtt_state:
                            wifi_status = f"MQTT:{mqtt_state}"
                        else:
                            wifi_status = "Unknown"

                    internet_status = data.get("internet_status")
                    if internet_status is None:
                        has_internet = data.get("has_internet")
                        if has_internet is not None:
                            internet_status = "Connected" if has_internet else "No Internet"
                        else:
                            internet_status = "Unknown"

                    wifi_signal_percent = 0
                    if wifi_signal_dbm is not None:
                        try:
                            wifi_signal_percent = self.signal_to_percentage(
                                int(wifi_signal_dbm)
                            )
                        except (ValueError, TypeError):
                            pass

                    return ESPDeviceStatus(
                        name=device_name,
                        ip_address=ip_address,
                        port=port,
                        wifi_status=wifi_status,
                        internet_status=internet_status,
                        wifi_signal_dbm=wifi_signal_dbm,
                        wifi_signal_percent=wifi_signal_percent,
                        is_connected=True
                    )

            except requests.exceptions.Timeout:
                self._logger.warning(
                    f"Attempt {attempt + 1}/{retries}: Timeout connecting to {device_name}"
                )
            except requests.exceptions.RequestException as e:
                self._logger.warning(
                    f"Attempt {attempt + 1}/{retries}: Error connecting to {device_name}: {e}"
                )
            except Exception as e:
                self._logger.error(f"Unexpected error for {device_name}: {e}")

        return ESPDeviceStatus(
            name=device_name,
            ip_address=device_ip.split(':')[0] if device_ip else "Unknown",
            port=device_ip.split(':')[1] if device_ip and ':' in device_ip else "Unknown",
            wifi_status="Not Connected",
            internet_status="Not Connected",
            wifi_signal_dbm=None,
            wifi_signal_percent=0,
            is_connected=False,
            error_message="Failed to connect after all retries"
        )

    def get_all_device_status(self, retries: int = 1) -> List[ESPDeviceStatus]:
        """Get status of all configured ESP devices"""
        return [
            self.get_device_status(name, retries)
            for name in self.config.devices.keys()
        ]

    def send_command(
        self,
        device_name: str,
        command: str,
        timeout: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Send a command to an ESP device.

        Args:
            device_name: Name of the device
            command: Command to send (e.g., 'lighton', 'motion', 'reset')
            timeout: Optional request timeout

        Returns:
            Tuple of (success, response_text)
        """
        device_ip = self.config.devices.get(device_name)
        if not device_ip:
            return False, f"Device '{device_name}' not found"

        try:
            url = f"http://{device_ip}/{command}"
            self._logger.info(f"Sending request to {device_name}: {url}")

            response = requests.get(url, timeout=timeout or self._timeout)
            response.raise_for_status()

            self._logger.info(f"Response from {device_name}: {response.text}")
            return True, response.text

        except requests.exceptions.Timeout:
            error_msg = f"Timeout connecting to {device_name}"
            self._logger.error(error_msg)
            return False, error_msg

        except requests.exceptions.RequestException as e:
            error_msg = f"Error connecting to {device_name}: {e}"
            self._logger.error(error_msg)
            return False, error_msg

    # Convenience methods for specific devices
    def send_to_lobby(self, command: str = "motion") -> Tuple[bool, str]:
        """Send command to ESP01 Lobby device"""
        return self.send_command('ESP01_Lobby', command)

    def send_to_porch(self, command: str = "motion") -> Tuple[bool, str]:
        """Send command to ESP32-LP-RLY porch device"""
        return self.send_command('ESP32_LP_RLY', command)

    def send_to_oled(self, command: str = "oled") -> Tuple[bool, str]:
        """Send command to ESP32 OLED device"""
        return self.send_command('ESP32_OLED', command)

    def send_to_gsm(self, command: str = "reedon") -> Tuple[bool, str]:
        """Send command to ESP32 GSM device"""
        return self.send_command('ESP32_GSM', command)

    def lobby_light_on(self) -> Tuple[bool, str]:
        """Turn on lobby light"""
        return self.send_to_lobby("lighton")

    def lobby_light_off(self) -> Tuple[bool, str]:
        """Turn off lobby light"""
        return self.send_to_lobby("lightoff")

    def porch_light_on(self) -> Tuple[bool, str]:
        """Turn on LP porch light (ESP32-LP-RLY)"""
        return self.send_to_porch("lighton")

    def porch_light_off(self) -> Tuple[bool, str]:
        """Turn off LP porch light (ESP32-LP-RLY)"""
        return self.send_to_porch("lightoff")

    def get_relay_state(self) -> Optional[str]:
        """
        Poll ESP01 relay at /status.

        The relay returns plain text 'ON' or 'OFF' (not JSON).

        Returns:
            'ON', 'OFF', or None if unreachable.
        """
        relay_ip = self.config.devices.get('ESP01_Relay')
        if not relay_ip:
            self._logger.warning("ESP01_Relay not found in config")
            return None
        try:
            response = requests.get(
                f"http://{relay_ip}/status",
                timeout=self._timeout
            )
            if response.status_code == 200:
                return response.text.strip().upper()
        except requests.exceptions.RequestException as e:
            self._logger.warning(f"ESP01 Relay poll failed: {e}")
        return None

    def relay_on(self) -> Tuple[bool, str]:
        """Turn ESP01 relay ON"""
        return self.send_command('ESP01_Relay', 'lighton')

    def relay_off(self) -> Tuple[bool, str]:
        """Turn ESP01 relay OFF"""
        return self.send_command('ESP01_Relay', 'lightoff')

    def generate_status_table(self) -> str:
        """Generate a text table of all device statuses"""
        statuses = self.get_all_device_status()

        table_data = []
        for status in statuses:
            signal_info = "N/A"
            if status.wifi_signal_dbm is not None:
                signal_info = f"{status.wifi_signal_dbm} dBm ({status.wifi_signal_percent}%)"

            table_data.append([
                status.name,
                status.ip_address,
                status.port,
                status.wifi_status,
                status.internet_status,
                signal_info
            ])

        return tabulate(
            table_data,
            headers=["Device", "IP Address", "Port", "Wi-Fi", "Internet", "Signal"],
            tablefmt="grid"
        )

    def generate_status_image(self, table_text: Optional[str] = None) -> Image.Image:
        """
        Generate an image from the status table.

        Args:
            table_text: Pre-generated table text. If None, generates automatically.

        Returns:
            PIL Image object
        """
        if table_text is None:
            table_text = self.generate_status_table()

        try:
            font = ImageFont.load_default()
            lines = table_text.splitlines()

            # Calculate dimensions using getbbox (fixes deprecated getsize)
            max_width = 0
            line_height = 0
            for line in lines:
                bbox = font.getbbox(line)
                width = bbox[2] - bbox[0]
                height = bbox[3] - bbox[1]
                max_width = max(max_width, width)
                line_height = max(line_height, height)

            # Add padding
            padding = 20
            image_width = max_width + 2 * padding
            image_height = (line_height * len(lines)) + 2 * padding

            # Create image
            image = Image.new('RGB', (image_width, image_height), color=(255, 255, 255))
            draw = ImageDraw.Draw(image)
            draw.text((padding, padding), table_text, font=font, fill=(0, 0, 0))

            return image

        except Exception as e:
            self._logger.error(f"Error generating status image: {e}")
            # Return a minimal error image
            image = Image.new('RGB', (200, 50), color=(255, 200, 200))
            draw = ImageDraw.Draw(image)
            draw.text((10, 10), f"Error: {e}", fill=(255, 0, 0))
            return image

    def get_status_image_buffer(self) -> io.BytesIO:
        """
        Get status table as image in a bytes buffer.

        Returns:
            BytesIO buffer containing PNG image
        """
        image = self.generate_status_image()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer
