"""
Video Recorder Module
Handles camera initialization, video recording, and file management
"""
import glob
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from threading import Event, Lock
from typing import Optional, Callable, Tuple

import psutil

from config import VideoConfig

# Conditional imports for Raspberry Pi camera
try:
    from picamera2 import Picamera2
    from picamera2.encoders import H264Encoder
    CAMERA_AVAILABLE = True
except ImportError:
    CAMERA_AVAILABLE = False


class RecordingState(Enum):
    """Video recording states"""
    IDLE = 'idle'
    RECORDING = 'recording'
    PROCESSING = 'processing'
    ERROR = 'error'


@dataclass
class RecordingResult:
    """Result of a recording session"""
    success: bool
    file_path: Optional[str]
    duration: float
    error_message: Optional[str] = None


class VideoRecorder:
    """
    Manages video recording with the Raspberry Pi camera.

    Features:
    - Thread-safe recording control
    - Automatic disk space management
    - Video conversion (H264 to MP4)
    - Configurable duration limits

    Usage:
        recorder = VideoRecorder(config)
        recorder.initialize()
        recorder.start_recording("filename")
        time.sleep(10)
        recorder.stop_recording()
    """

    def __init__(self, config: VideoConfig):
        self.config = config
        self._camera = None
        self._state = RecordingState.IDLE
        self._current_file_path: Optional[str] = None
        self._recording_start_time: float = 0
        self._stop_event = Event()
        self._recording_thread: Optional[threading.Thread] = None
        self._camera_lock = Lock()
        self._logger = logging.getLogger(__name__)
        self._manual_recording: bool = False

        # Callbacks
        self._on_recording_complete: Optional[Callable[[RecordingResult], None]] = None
        self._on_disk_cleanup: Optional[Callable[[int, float], None]] = None

    def initialize(self) -> bool:
        """Initialize the camera"""
        if not CAMERA_AVAILABLE:
            self._logger.warning("PiCamera2 not available")
            return False

        try:
            with self._camera_lock:
                self._camera = Picamera2()
                # Pi 5 (PiSP/RP1) requires an explicit resolution — full sensor
                # resolution (4608x2592) causes "Failed to start media pipeline: -32"
                video_config = self._camera.create_video_configuration(
                    main={"size": (1920, 1080)},
                    buffer_count=6
                )
                self._camera.configure(video_config)
                time.sleep(0.15)

            self._logger.info("Camera initialized successfully")
            return True

        except Exception as e:
            self._logger.error(f"Camera initialization error: {e}")
            self._camera = None
            return False

    def close(self) -> None:
        """Close the camera"""
        with self._camera_lock:
            if self._camera:
                try:
                    if self._state == RecordingState.RECORDING:
                        self._camera.stop_recording()
                    self._camera.close()
                except Exception as e:
                    self._logger.error(f"Error closing camera: {e}")
                finally:
                    self._camera = None
                    self._state = RecordingState.IDLE

    def set_callbacks(
        self,
        on_complete: Optional[Callable[[RecordingResult], None]] = None,
        on_cleanup: Optional[Callable[[int, float], None]] = None
    ) -> None:
        """Set callbacks for recording events"""
        self._on_recording_complete = on_complete
        self._on_disk_cleanup = on_cleanup

    def start_recording(
        self,
        filename: Optional[str] = None,
        max_duration: Optional[int] = None,
        manual: bool = False
    ) -> bool:
        """
        Start video recording.

        Args:
            filename: Base filename (without extension). If None, uses timestamp.
            max_duration: Maximum recording duration in seconds. Uses config default if None.
            manual: If True, main loop motion-stop logic will not interrupt this recording.

        Returns:
            True if recording started successfully.
        """
        if self._state in (RecordingState.RECORDING, RecordingState.PROCESSING):
            self._logger.warning(f"Cannot start recording: currently {self._state.value}")
            return False

        # Wait for previous recording thread to fully finish before starting new one
        # This prevents "Encoder already running" errors from picamera2
        if self._recording_thread and self._recording_thread.is_alive():
            self._logger.info("Waiting for previous recording thread to finish...")
            self._recording_thread.join(timeout=5)
            if self._recording_thread.is_alive():
                self._logger.error("Previous recording thread still running - cannot start new recording")
                return False

        if not self._camera:
            if not self.initialize():
                return False

        # Generate filename if not provided
        if filename is None:
            filename = time.strftime("%d%b%y_%H%M%S")

        max_duration = max_duration or self.config.max_duration
        self._current_file_path = os.path.join(self.config.video_dir, filename)

        # Ensure video directory exists
        os.makedirs(self.config.video_dir, exist_ok=True)

        # Start recording in separate thread
        self._manual_recording = manual
        self._stop_event.clear()
        self._recording_thread = threading.Thread(
            target=self._recording_worker,
            args=(max_duration,),
            name=f"VideoRec-{filename}"
        )
        self._recording_thread.start()

        self._logger.info(f"Recording started: {filename}, max: {max_duration}s, manual: {manual}")
        return True

    def stop_recording(self) -> None:
        """Signal the recording to stop"""
        if self._state == RecordingState.RECORDING:
            self._stop_event.set()
            self._logger.info("Stop recording signaled")

    def extend_recording(self) -> None:
        """Extend the recording by clearing the stop event"""
        if self._state == RecordingState.RECORDING:
            self._stop_event.clear()

    def _recording_worker(self, max_duration: int) -> None:
        """Worker thread for recording"""
        start_time = time.time()
        h264_file = self._current_file_path + '.h264'
        mp4_file = self._current_file_path + '.mp4'

        try:
            with self._camera_lock:
                if not self._camera:
                    raise RuntimeError("Camera not initialized")

                # Create a fresh encoder for each recording — reusing a stopped
                # encoder causes "Broken pipe" on Pi 5 (no hardware H264 encoder)
                encoder = H264Encoder(bitrate=self.config.bitrate)
                self._camera.start_recording(encoder, h264_file)
                self._state = RecordingState.RECORDING
                self._recording_start_time = start_time

            # Wait for stop event or timeout
            while not self._stop_event.is_set():
                elapsed = time.time() - start_time
                if elapsed >= max_duration:
                    self._logger.info(f"Reached max duration: {max_duration}s")
                    break
                time.sleep(0.5)

            # Stop recording
            with self._camera_lock:
                if self._camera and self._state == RecordingState.RECORDING:
                    self._camera.stop_recording()

            duration = time.time() - start_time
            self._state = RecordingState.PROCESSING

            # Check if recording is long enough
            if duration >= self.config.min_duration:
                # Convert to MP4
                success = self._convert_to_mp4(h264_file, mp4_file)

                if success:
                    # Cleanup H264 file
                    self._safe_delete(h264_file)

                    # Check disk space
                    self._check_disk_space()

                    result = RecordingResult(
                        success=True,
                        file_path=mp4_file,
                        duration=duration
                    )
                else:
                    result = RecordingResult(
                        success=False,
                        file_path=None,
                        duration=duration,
                        error_message="Conversion failed"
                    )
            else:
                self._logger.warning(f"Recording too short: {duration:.1f}s")
                self._safe_delete(h264_file)
                result = RecordingResult(
                    success=False,
                    file_path=None,
                    duration=duration,
                    error_message=f"Too short ({duration:.1f}s < {self.config.min_duration}s)"
                )

            # Trigger callback
            if self._on_recording_complete:
                self._on_recording_complete(result)

        except Exception as e:
            self._logger.error(f"Recording error: {e}")
            self._state = RecordingState.ERROR

            if self._on_recording_complete:
                self._on_recording_complete(RecordingResult(
                    success=False,
                    file_path=None,
                    duration=time.time() - start_time,
                    error_message=str(e)
                ))

        finally:
            self._state = RecordingState.IDLE
            self._manual_recording = False

    def _convert_to_mp4(self, h264_file: str, mp4_file: str) -> bool:
        """Convert H264 to MP4 using ffmpeg"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", h264_file,
                 "-c:v", "libx264", "-crf", "26", "-preset", "fast",
                 "-c:a", "copy", mp4_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60
            )
            if result.returncode == 0:
                self._logger.info(f"Converted to MP4: {mp4_file}")
                return True
            else:
                self._logger.error(f"FFmpeg returned: {result.returncode}")
                return False
        except subprocess.TimeoutExpired:
            self._logger.error("FFmpeg conversion timeout")
            return False
        except Exception as e:
            self._logger.error(f"Conversion error: {e}")
            return False

    def _safe_delete(self, file_path: str) -> None:
        """Safely delete a file"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                self._logger.debug(f"Deleted: {file_path}")
        except Exception as e:
            self._logger.error(f"Delete error: {e}")

    def _check_disk_space(self) -> None:
        """Check disk usage and cleanup if needed"""
        try:
            usage = psutil.disk_usage('/')
            usage_percent = usage.percent

            self._logger.debug(f"Disk usage: {usage_percent:.1f}%")

            if usage_percent > self.config.disk_usage_threshold:
                self._logger.warning(
                    f"Disk usage ({usage_percent:.1f}%) exceeded "
                    f"{self.config.disk_usage_threshold}% threshold"
                )
                self._cleanup_videos()

        except Exception as e:
            self._logger.error(f"Disk check error: {e}")

    def _cleanup_videos(self) -> None:
        """Remove all video files to free disk space"""
        try:
            video_files = glob.glob(f"{self.config.video_dir}/*")
            removed_count = 0
            freed_space_mb = 0

            for video_file in video_files:
                try:
                    file_size = os.path.getsize(video_file) / (1024 * 1024)
                    os.remove(video_file)
                    removed_count += 1
                    freed_space_mb += file_size
                    self._logger.info(f"Removed: {os.path.basename(video_file)} ({file_size:.1f} MB)")
                except Exception as e:
                    self._logger.error(f"Error removing {video_file}: {e}")

            if removed_count > 0:
                new_usage = psutil.disk_usage('/').percent
                self._logger.info(
                    f"Cleanup complete. Removed {removed_count} files, "
                    f"freed {freed_space_mb:.1f} MB. New usage: {new_usage:.1f}%"
                )

                if self._on_disk_cleanup:
                    self._on_disk_cleanup(removed_count, freed_space_mb)

        except Exception as e:
            self._logger.error(f"Cleanup error: {e}")

    @property
    def is_recording(self) -> bool:
        return self._state == RecordingState.RECORDING and not self._stop_event.is_set()

    @property
    def is_manual_recording(self) -> bool:
        """True if current recording was triggered manually (not by motion)."""
        return self._manual_recording and self.is_recording

    @property
    def state(self) -> RecordingState:
        return self._state

    @property
    def recording_duration(self) -> float:
        """Get current recording duration in seconds"""
        if self._state == RecordingState.RECORDING:
            return time.time() - self._recording_start_time
        return 0

    def get_disk_usage(self) -> Tuple[float, float, float]:
        """Get disk usage (total GB, used GB, percent)"""
        try:
            usage = psutil.disk_usage('/')
            return (
                usage.total / (1024 ** 3),
                usage.used / (1024 ** 3),
                usage.percent
            )
        except Exception:
            return (0, 0, 0)
