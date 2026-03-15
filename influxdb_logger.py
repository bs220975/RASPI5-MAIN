"""
InfluxDB Logger Module
Handles logging sensor data to InfluxDB 2.x
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from config import InfluxDBConfig


class InfluxDBLogger:
    """
    Manages InfluxDB 2.x connections and data logging.

    Provides a persistent connection to avoid creating new clients
    for each write operation (fixes memory leak in original code).

    Usage:
        logger = InfluxDBLogger(config)
        logger.connect()
        logger.log_motion_state(True)
        logger.close()
    """

    # Indian timezone for logging
    INDIAN_TZ = pytz.timezone('Asia/Kolkata')

    def __init__(self, config: InfluxDBConfig):
        self.config = config
        self._client: Optional[InfluxDBClient] = None
        self._write_api = None
        self._query_api = None
        self._logger = logging.getLogger(__name__)
        self._prev_motion_state: Optional[bool] = None

    def connect(self) -> bool:
        """Establish connection to InfluxDB"""
        try:
            self._client = InfluxDBClient(
                url=self.config.url,
                token=self.config.token,
                org=self.config.org
            )
            self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
            self._query_api = self._client.query_api()
            self._logger.info("Connected to InfluxDB")
            return True
        except Exception as e:
            self._logger.error(f"InfluxDB connection error: {e}")
            return False

    def close(self) -> None:
        """Close InfluxDB connection"""
        try:
            if self._write_api:
                self._write_api.close()
            if self._client:
                self._client.close()
            self._logger.info("InfluxDB connection closed")
        except Exception as e:
            self._logger.error(f"Error closing InfluxDB: {e}")
        finally:
            self._client = None
            self._write_api = None
            self._query_api = None

    def is_connected(self) -> bool:
        """Check if connected to InfluxDB"""
        return self._client is not None

    def get_indian_timestamp(self) -> str:
        """Get current time in Indian timezone formatted for logging"""
        return datetime.now(self.INDIAN_TZ).strftime('%I:%M:%S %p')

    def log_motion_state(self, motion_detected: bool) -> bool:
        """
        Log motion sensor state to InfluxDB.

        Only logs when state changes from previous value.

        Args:
            motion_detected: Current motion detection state

        Returns:
            True if logged successfully, False otherwise
        """
        # Skip if state hasn't changed
        if motion_detected == self._prev_motion_state:
            return True

        if not self._write_api:
            if not self.connect():
                return False

        try:
            point = Point("motion_sensor") \
                .tag("sensor", "LD2420") \
                .field("motion_status", int(motion_detected)) \
                .time(datetime.utcnow())

            self._write_api.write(bucket=self.config.bucket, record=point)

            self._logger.info(
                f"[{self.get_indian_timestamp()}] Motion state: "
                f"{self._prev_motion_state} -> {motion_detected}"
            )

            self._prev_motion_state = motion_detected
            return True

        except Exception as e:
            self._logger.error(f"InfluxDB write error: {e}")
            return False

    def log_sensor_data(
        self,
        measurement: str,
        tags: Dict[str, str],
        fields: Dict[str, Any]
    ) -> bool:
        """
        Log arbitrary sensor data to InfluxDB.

        Args:
            measurement: Measurement name
            tags: Dictionary of tags
            fields: Dictionary of field values

        Returns:
            True if logged successfully
        """
        if not self._write_api:
            if not self.connect():
                return False

        try:
            point = Point(measurement)

            for key, value in tags.items():
                point = point.tag(key, value)

            for key, value in fields.items():
                point = point.field(key, value)

            point = point.time(datetime.utcnow())

            self._write_api.write(bucket=self.config.bucket, record=point)
            return True

        except Exception as e:
            self._logger.error(f"InfluxDB write error: {e}")
            return False

    def query_sensor_data(
        self,
        measurement: str,
        fields: List[str],
        minutes_back: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Query sensor data from InfluxDB.

        Args:
            measurement: Measurement name to query
            fields: List of field names to retrieve
            minutes_back: How many minutes of data to retrieve

        Returns:
            List of data points
        """
        if not self._query_api:
            if not self.connect():
                return []

        try:
            now = datetime.utcnow()
            start_time = now - timedelta(minutes=minutes_back)

            # Build field filter
            field_filter = " or ".join(
                f'r._field == "{f}"' for f in fields
            )

            query = f'''
            from(bucket: "{self.config.bucket}")
              |> range(start: {start_time.isoformat()}Z, stop: {now.isoformat()}Z)
              |> filter(fn: (r) => r._measurement == "{measurement}")
              |> filter(fn: (r) => {field_filter})
              |> sort(columns: ["_time"])
            '''

            results = self._query_api.query(query)

            data = []
            for table in results:
                for record in table.records:
                    data.append({
                        'time': record.get_time(),
                        'field': record.get_field(),
                        'value': record.get_value()
                    })

            return data

        except Exception as e:
            self._logger.error(f"InfluxDB query error: {e}")
            return []

    def query_motion_data(self, minutes_back: int = 60) -> List[Tuple[datetime, bool]]:
        """
        Query motion sensor data.

        Args:
            minutes_back: How many minutes of data to retrieve

        Returns:
            List of (timestamp, motion_state) tuples
        """
        data = self.query_sensor_data(
            measurement="motion_sensor",
            fields=["motion_status"],
            minutes_back=minutes_back
        )

        return [
            (item['time'], bool(item['value']))
            for item in data
            if item['field'] == 'motion_status'
        ]

    @property
    def previous_motion_state(self) -> Optional[bool]:
        """Get the previous motion state"""
        return self._prev_motion_state

    def reset_state(self) -> None:
        """Reset tracked state"""
        self._prev_motion_state = None


# Convenience function for backward compatibility
def log_to_influxdb(
    motion_status: bool,
    prev_state: bool,
    config: Optional[InfluxDBConfig] = None
) -> bool:
    """
    Legacy function for logging motion state.

    Note: Creates a new connection for each call. For better performance,
    use InfluxDBLogger class with persistent connection.
    """
    if config is None:
        config = InfluxDBConfig()

    if motion_status == prev_state:
        return prev_state

    logger = InfluxDBLogger(config)
    logger._prev_motion_state = prev_state

    if logger.connect():
        try:
            logger.log_motion_state(motion_status)
            return motion_status
        finally:
            logger.close()

    return prev_state


def get_indian_timestamp() -> str:
    """Get current Indian timestamp - for backward compatibility"""
    return datetime.now(InfluxDBLogger.INDIAN_TZ).strftime('%I:%M:%S %p')
