"""
Sensor Manager Module

Provides unified interface for managing sensors:
- LD2420 Radar sensor (UART-based motion detection)
- GPIO sensors (PIR, MMS, Reed switch)
- Mock sensors for testing on non-Pi platforms

Usage:
    from sensors import SensorManager
    from config import config

    manager = SensorManager(config.gpio, config.radar)
    manager.initialize()

    while True:
        if manager.check_motion():
            print("Motion detected!")
        time.sleep(0.1)

    manager.cleanup()
"""
import logging
import time
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any, List

from config import GPIOConfig, RadarConfig

__all__ = [
    'SensorState',
    'RadarSensor',
    'GPIOSensorManager',
    'SensorManager',
    'MockRadarSensor',
    'MockGPIOSensorManager',
]

logger = logging.getLogger(__name__)

# Check for Raspberry Pi GPIO availability
try:
    from gpiozero import DigitalInputDevice
    import lgpio
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logger.info("GPIO not available - running in mock mode")

# Check for serial availability
try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    logger.info("Serial not available - radar sensor disabled")


@dataclass
class SensorState:
    """
    Current state of all sensors.

    Attributes:
        pir_active: PIR sensor detecting motion
        mms_active: Microwave sensor detecting motion
        radar_motion: Radar detecting motion
        radar_distance: Last measured radar distance in cm
        door_open: Reed switch state — True = door open, False = door closed
        timestamp: Time when state was captured
    """
    pir_active: bool = False
    mms_active: bool = False
    radar_motion: bool = False
    radar_distance: int = 0
    door_open: bool = False
    timestamp: float = field(default_factory=time.time)

    @property
    def any_motion(self) -> bool:
        """Check if any motion sensor is active."""
        return self.pir_active or self.mms_active or self.radar_motion


class BaseSensor(ABC):
    """Abstract base class for all sensors."""

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the sensor. Returns True on success."""
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Release sensor resources."""
        pass

    @property
    @abstractmethod
    def is_initialized(self) -> bool:
        """Check if sensor is initialized."""
        pass


class RadarSensor(BaseSensor):
    """
    LD2420 Radar Motion Sensor Handler.

    Communicates with LD2420 radar sensor via UART serial port.
    Provides motion detection with configurable range and sensitivity.

    Features:
    - Configurable detection range (min/max distance)
    - Adjustable sensitivity
    - Noise filtering with stable reading requirement
    - Auto-reset after motion timeout
    """

    def __init__(self, config: RadarConfig):
        """
        Initialize radar sensor.

        Args:
            config: RadarConfig with port and detection settings
        """
        self._config = config
        self._serial: Optional['serial.Serial'] = None
        self._last_distance = 0
        self._motion_detected = False
        self._last_motion_time = 0.0
        self._stable_reading_count = 0
        self._initialized = False
        self._lock = threading.Lock()

    def initialize(self) -> bool:
        """Initialize serial connection to radar sensor."""
        if not SERIAL_AVAILABLE:
            logger.warning("Serial library not available")
            return False

        try:
            self._serial = serial.Serial(
                self._config.port,
                self._config.baud_rate,
                timeout=1
            )
            time.sleep(2)  # Allow sensor to stabilize
            self._initialized = True
            logger.info(f"Radar sensor initialized on {self._config.port}")
            return True
        except Exception as e:
            logger.error(f"Radar initialization error: {e}")
            return False

    def cleanup(self) -> None:
        """Close serial connection."""
        with self._lock:
            if self._serial:
                try:
                    self._serial.close()
                except Exception as e:
                    logger.error(f"Error closing radar serial: {e}")
                finally:
                    self._serial = None
                    self._initialized = False
        logger.info("Radar sensor stopped")

    @property
    def is_initialized(self) -> bool:
        return self._initialized and self._serial is not None

    def set_detection_range(
        self,
        min_cm: int,
        max_cm: int,
        sensitivity_cm: int = 5
    ) -> None:
        """
        Configure detection range and sensitivity.

        Args:
            min_cm: Minimum detection distance in centimeters
            max_cm: Maximum detection distance in centimeters
            sensitivity_cm: Minimum distance change to trigger detection
        """
        self._config.detection_min_cm = min_cm
        self._config.detection_max_cm = max_cm
        self._config.sensitivity_cm = sensitivity_cm
        logger.info(
            f"Radar range: {min_cm}-{max_cm}cm, sensitivity: {sensitivity_cm}cm"
        )

    def check_motion(self) -> bool:
        """
        Check for motion detection.

        Returns:
            True if motion is currently detected
        """
        if not self._serial:
            return False

        with self._lock:
            current_time = time.time()

            # Auto-reset motion after timeout
            if self._motion_detected:
                elapsed = current_time - self._last_motion_time
                if elapsed > self._config.motion_timeout:
                    self._motion_detected = False
                    self._stable_reading_count = 0
                    logger.debug("Radar motion reset (timeout)")

            # Read and process serial data
            try:
                if self._serial.in_waiting > 0:
                    data = self._serial.read(
                        self._serial.in_waiting
                    ).decode('ascii', errors='ignore')

                    for line in data.split('\n'):
                        line = line.strip().replace('\r', '')
                        if self._process_line(line, current_time):
                            return True

            except OSError as e:
                if e.errno == 5:
                    # Close broken port immediately — prevents next in_waiting from
                    # blocking indefinitely in the kernel and freezing all threads
                    try:
                        self._serial.close()
                    except Exception:
                        pass
                    self._serial = None
                    self._initialized = False
                    logger.warning("Radar serial I/O error — port closed, will reinitialize")
                else:
                    logger.error(f"Radar read error: {e}")
                self._stable_reading_count = 0
                raise  # let main loop handle sleep + reinit
            except Exception as e:
                logger.error(f"Radar read error: {e}")
                self._stable_reading_count = 0

        return self._motion_detected

    def _process_line(self, line: str, current_time: float) -> bool:
        """Process a single line from radar output."""
        # Parse "Range <number>" format
        if not (line.startswith("Range ") and len(line) > 6):
            return False

        parts = line.split()
        if len(parts) < 2 or not parts[1].isdigit():
            return False

        distance = int(parts[1])

        # Validate against configured range
        min_cm = self._config.detection_min_cm
        max_cm = self._config.detection_max_cm

        if not (min_cm <= distance <= max_cm):
            self._stable_reading_count = 0
            return False

        # Check sensitivity threshold
        if abs(distance - self._last_distance) < self._config.sensitivity_cm:
            return False

        self._stable_reading_count += 1

        # Require stable readings before triggering
        if self._stable_reading_count >= self._config.require_stable_readings:
            self._last_distance = distance
            self._motion_detected = True
            self._last_motion_time = current_time
            return True

        return False

    def get_status(self) -> Dict[str, Any]:
        """Get current radar status."""
        return {
            'initialized': self._initialized,
            'motion_detected': self._motion_detected,
            'last_distance_cm': self._last_distance,
            'detection_range': f"{self._config.detection_min_cm}-{self._config.detection_max_cm}cm",
            'sensitivity': f"{self._config.sensitivity_cm}cm",
        }

    @property
    def last_distance(self) -> int:
        """Get last measured distance in cm."""
        return self._last_distance


class MockRadarSensor(RadarSensor):
    """
    Mock radar sensor for testing on non-Pi platforms.

    Simulates radar behavior without actual hardware.
    """

    def __init__(self, config: RadarConfig):
        super().__init__(config)
        self._simulated_motion = False

    def initialize(self) -> bool:
        self._initialized = True
        logger.info("Mock radar sensor initialized")
        return True

    def cleanup(self) -> None:
        self._initialized = False
        logger.info("Mock radar sensor stopped")

    def check_motion(self) -> bool:
        return self._simulated_motion

    def set_simulated_motion(self, motion: bool, distance: int = 100) -> None:
        """Set simulated motion state for testing."""
        self._simulated_motion = motion
        self._motion_detected = motion
        self._last_distance = distance
        if motion:
            self._last_motion_time = time.time()


class GPIOSensorManager(BaseSensor):
    """
    Manages GPIO-based sensors (PIR, MMS, Reed Switch).

    Provides unified interface for reading sensor states and
    handling callbacks on state changes.

    Reed switch wiring: one leg → GPIO 26, other leg → GND.
    Internal pull-up is enabled so the pin reads HIGH (door open)
    when the switch is open and LOW (door closed) when the magnet
    closes the contact.
    """

    def __init__(self, config: GPIOConfig):
        """
        Initialize GPIO sensor manager.

        Args:
            config: GPIOConfig with pin assignments
        """
        self._config = config
        self._mms_sensor = None
        self._pir_sensor = None
        self._reed_sensor = None
        self._initialized = False
        self._lgpio_handle: Optional[int] = None  # lgpio chip handle for LED + reed

        # Callbacks
        self._on_motion: Optional[Callable[[str], None]] = None
        self._on_door_open: Optional[Callable[[], None]] = None
        self._on_door_close: Optional[Callable[[], None]] = None

    def initialize(self) -> bool:
        """Initialize all GPIO sensors."""
        if not GPIO_AVAILABLE:
            logger.warning("GPIO not available - using mock mode")
            return False

        try:
            # Open lgpio chip — handles LED and reed switch (Pi5-compatible)
            try:
                self._lgpio_handle = lgpio.gpiochip_open(0)
            except Exception as e:
                logger.warning(f"lgpio chip open failed: {e}")
                self._lgpio_handle = None

            # Initialize sensors with error handling for each
            try:
                self._mms_sensor = DigitalInputDevice(
                    self._config.mms_sensor_pin,
                    pull_up=False,
                    bounce_time=0.1
                )
            except Exception as e:
                logger.warning(f"MMS sensor init failed: {e}")

            try:
                self._pir_sensor = DigitalInputDevice(
                    self._config.pir_sensor_pin,
                    pull_up=False,
                    bounce_time=0.1
                )
            except Exception as e:
                logger.warning(f"PIR sensor init failed: {e}")

            # Reed switch: internal pull-up via lgpio, polled in a daemon thread.
            # pull-up HIGH = door open, LOW = door closed (switch pulls to GND).
            # If reed is not physically connected the pin stays HIGH (open) silently.
            reed_ok = False
            if self._lgpio_handle is not None:
                try:
                    lgpio.gpio_claim_input(
                        self._lgpio_handle,
                        self._config.reed_switch_pin,
                        lgpio.SET_PULL_UP
                    )
                    raw = lgpio.gpio_read(self._lgpio_handle, self._config.reed_switch_pin)
                    door_state = "open" if raw else "closed"
                    logger.info(f"Reed switch initialized on GPIO {self._config.reed_switch_pin} — door is {door_state}")
                    reed_ok = True
                except Exception as e:
                    logger.warning(f"Reed switch init failed: {e}")

            # Setup LED output via lgpio
            if self._lgpio_handle is not None:
                try:
                    lgpio.gpio_claim_output(self._lgpio_handle, self._config.led_pin, 0)
                    logger.info(f"LED initialized on GPIO {self._config.led_pin}")
                except Exception as e:
                    logger.warning(f"LED setup failed: {e}")

            # Must set _initialized=True BEFORE starting the poll thread,
            # because the loop checks `while self._initialized`.
            self._initialized = True
            logger.info("GPIO sensors initialized")

            if reed_ok:
                threading.Thread(target=self._reed_poll_loop, daemon=True, name="reed-poll").start()

            return True

        except Exception as e:
            logger.error(f"GPIO initialization error: {e}")
            return False

    def _reed_poll_loop(self) -> None:
        """Poll reed switch at 50 ms intervals with extended debounce + cooldown.

        DEBOUNCE is 2 s (was 0.3 s) to reject EMI bursts from the nearby
        LD2420 24 GHz radar.  MIN_INTERVAL prevents paired false events that
        appear as an open immediately followed by a close (or vice versa).
        """
        pin = self._config.reed_switch_pin
        h = self._lgpio_handle
        DEBOUNCE = 2.0      # seconds new state must be held — rejects sub-2 s EMI bursts
        MIN_INTERVAL = 5.0  # minimum seconds between consecutive door events
        try:
            stable = lgpio.gpio_read(h, pin)
        except Exception:
            return
        candidate = stable
        candidate_since: Optional[float] = None
        last_event_at: float = 0.0
        while self._initialized:
            time.sleep(0.05)
            try:
                raw = lgpio.gpio_read(h, pin)
            except Exception:
                break
            if raw == stable:
                # Back to (or still at) confirmed state — reset candidate
                candidate = stable
                candidate_since = None
            else:
                if raw != candidate:
                    # New candidate; start debounce timer
                    candidate = raw
                    candidate_since = time.monotonic()
                elif candidate_since and (time.monotonic() - candidate_since) >= DEBOUNCE:
                    now = time.monotonic()
                    if (now - last_event_at) >= MIN_INTERVAL:
                        # Held long enough and cooldown elapsed — real event
                        stable = candidate
                        candidate_since = None
                        last_event_at = now
                        self._reed_on_change(stable)
                    else:
                        # Within cooldown — likely EMI artifact paired with previous event
                        logger.warning(
                            "Reed: state change suppressed (%.1fs < %.0fs cooldown) — possible EMI",
                            now - last_event_at, MIN_INTERVAL
                        )
                        candidate = stable
                        candidate_since = None

    def _reed_on_change(self, pin_high: int) -> None:
        """Fire the appropriate door callback when reed switch state changes."""
        if pin_high:
            logger.info("Reed switch: door OPENED")
            if self._on_door_open:
                threading.Thread(target=self._on_door_open, daemon=True).start()
        else:
            logger.info("Reed switch: door CLOSED")
            if self._on_door_close:
                threading.Thread(target=self._on_door_close, daemon=True).start()

    def cleanup(self) -> None:
        """Cleanup GPIO resources. Setting _initialized=False stops the poll loop."""
        self._initialized = False
        if self._lgpio_handle is not None:
            try:
                lgpio.gpiochip_close(self._lgpio_handle)
            except Exception as e:
                logger.error(f"lgpio cleanup error: {e}")
            self._lgpio_handle = None
        logger.info("GPIO cleanup complete")

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def set_callbacks(
        self,
        on_motion: Optional[Callable[[str], None]] = None
    ) -> None:
        """Set motion callback."""
        self._on_motion = on_motion

    def set_reed_callbacks(
        self,
        on_open: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Register callbacks for door reed switch events.

        Args:
            on_open:  Called when door opens (switch opens, pin goes HIGH)
            on_close: Called when door closes (switch closes, pin goes LOW)
        """
        self._on_door_open = on_open
        self._on_door_close = on_close

    def read_mms(self) -> bool:
        """Read MMS sensor state."""
        if self._mms_sensor:
            return bool(self._mms_sensor.value)
        return False

    def read_pir(self) -> bool:
        """Read PIR sensor state."""
        if self._pir_sensor:
            return bool(self._pir_sensor.value)
        return False

    def read_reed(self) -> bool:
        """Read reed switch state. Returns True if door is open."""
        if self._lgpio_handle is not None and self._initialized:
            try:
                return bool(lgpio.gpio_read(self._lgpio_handle, self._config.reed_switch_pin))
            except Exception:
                pass
        return False

    def set_led(self, state: bool) -> None:
        """Set status LED state."""
        if self._lgpio_handle is not None and self._initialized:
            try:
                lgpio.gpio_write(self._lgpio_handle, self._config.led_pin, 1 if state else 0)
            except Exception as e:
                logger.error(f"LED control error: {e}")

    def get_state(self) -> SensorState:
        """Get current state of all GPIO sensors."""
        return SensorState(
            pir_active=self.read_pir(),
            mms_active=self.read_mms(),
            door_open=self.read_reed(),
        )


class MockGPIOSensorManager(GPIOSensorManager):
    """
    Mock GPIO sensor manager for testing.

    Simulates GPIO sensors without actual hardware.
    """

    def __init__(self, config: GPIOConfig):
        super().__init__(config)
        self._mock_pir = False
        self._mock_mms = False
        self._mock_led = False
        self._mock_reed = False  # False = door closed

    def initialize(self) -> bool:
        self._initialized = True
        logger.info("Mock GPIO sensors initialized")
        return True

    def cleanup(self) -> None:
        self._initialized = False
        logger.info("Mock GPIO cleanup complete")

    def read_mms(self) -> bool:
        return self._mock_mms

    def read_pir(self) -> bool:
        return self._mock_pir

    def read_reed(self) -> bool:
        return self._mock_reed

    def set_led(self, state: bool) -> None:
        self._mock_led = state

    def set_mock_state(
        self,
        pir: Optional[bool] = None,
        mms: Optional[bool] = None,
        reed_open: Optional[bool] = None,
    ) -> None:
        """Set mock sensor states for testing."""
        if pir is not None:
            self._mock_pir = pir
        if mms is not None:
            self._mock_mms = mms
        if reed_open is not None:
            prev = self._mock_reed
            self._mock_reed = reed_open
            if reed_open and not prev and self._on_door_open:
                self._on_door_open()
            elif not reed_open and prev and self._on_door_close:
                self._on_door_close()


class SensorManager:
    """
    Unified sensor manager combining GPIO and Radar sensors.

    Provides single interface for all sensor operations with
    automatic fallback to mock sensors when hardware unavailable.

    Example:
        manager = SensorManager(gpio_config, radar_config)
        manager.initialize()

        # Set callbacks
        manager.set_door_callbacks(
            on_open=lambda: print("Door opened!"),
            on_close=lambda: print("Door closed!")
        )

        # Check sensors
        state = manager.get_full_state()
        if state.any_motion:
            print(f"Motion at {state.radar_distance}cm")

        manager.cleanup()
    """

    def __init__(
        self,
        gpio_config: GPIOConfig,
        radar_config: RadarConfig,
        use_mocks: bool = False
    ):
        """
        Initialize sensor manager.

        Args:
            gpio_config: GPIO pin configuration
            radar_config: Radar sensor configuration
            use_mocks: Force use of mock sensors (for testing)
        """
        self._use_mocks = use_mocks

        # Create appropriate sensor instances
        if use_mocks or not GPIO_AVAILABLE:
            self.gpio = MockGPIOSensorManager(gpio_config)
        else:
            self.gpio = GPIOSensorManager(gpio_config)

        if use_mocks or not SERIAL_AVAILABLE or not radar_config.enabled:
            self.radar = MockRadarSensor(radar_config)
        else:
            self.radar = RadarSensor(radar_config)

    def initialize(self) -> bool:
        """
        Initialize all sensors.

        Returns:
            True if at least one sensor initialized successfully
        """
        gpio_ok = self.gpio.initialize()
        radar_ok = self.radar.initialize()

        if not gpio_ok:
            logger.warning("GPIO sensors not available")
        if not radar_ok:
            logger.warning("Radar sensor not available")

        return gpio_ok or radar_ok

    def cleanup(self) -> None:
        """Cleanup all sensor resources."""
        self.gpio.cleanup()
        self.radar.cleanup()

    def get_full_state(self) -> SensorState:
        """Get state of all sensors including radar."""
        state = self.gpio.get_state()
        state.radar_motion = self.radar.check_motion()
        state.radar_distance = self.radar.last_distance
        state.timestamp = time.time()
        return state

    def check_motion(self) -> bool:
        """Check if any motion sensor is detecting movement."""
        return (
            self.radar.check_motion() or
            self.gpio.read_pir() or
            self.gpio.read_mms()
        )

    def set_led(self, state: bool) -> None:
        """Set status LED."""
        self.gpio.set_led(state)

    @property
    def is_initialized(self) -> bool:
        """Check if any sensors are initialized."""
        return self.gpio.is_initialized or self.radar.is_initialized

    def get_status(self) -> Dict[str, Any]:
        """Get status of all sensors."""
        return {
            'gpio_initialized': self.gpio.is_initialized,
            'radar': self.radar.get_status(),
            'current_state': {
                'pir': self.gpio.read_pir(),
                'mms': self.gpio.read_mms(),
                'door_open': self.gpio.read_reed(),
            }
        }
