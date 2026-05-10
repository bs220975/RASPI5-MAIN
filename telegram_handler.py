"""
Telegram Bot Handler Module

Provides thread-safe Telegram messaging with:
- Message queue for async sending
- Automatic retry with exponential backoff
- Rate limiting to avoid API limits
- Support for text, video, image, and document messages

Usage:
    from telegram_handler import TelegramHandler
    from config import config

    handler = TelegramHandler(config.telegram)
    handler.start()
    handler.send_text("Hello, World!")
    handler.send_video("/path/to/video.mp4", caption="Motion detected")
"""
import io
import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from queue import PriorityQueue, Empty
from typing import Optional, Callable, Union, BinaryIO

import telepot
from telepot.exception import TelegramError

from config import TelegramConfig

__all__ = [
    'MessageType',
    'TelegramHandler',
    'TelegramError',
]

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Types of messages that can be sent via Telegram."""
    TEXT = auto()
    VIDEO = auto()
    IMAGE = auto()
    DOCUMENT = auto()


@dataclass
class QueuedMessage:
    """
    Represents a message queued for sending.

    Attributes:
        message_type: Type of message (text, video, etc.)
        content: Message content (text string or file path)
        caption: Optional caption for media messages
        retry_count: Number of send attempts made
    """
    message_type: MessageType
    content: Union[str, bytes, BinaryIO]
    caption: Optional[str] = None
    retry_count: int = 0
    parse_mode: Optional[str] = None

    # Priority: lower = higher priority (TEXT=0 sends before VIDEO=1)
    @property
    def priority(self) -> int:
        return 0 if self.message_type == MessageType.TEXT else 1

    def __lt__(self, other: 'QueuedMessage') -> bool:
        return self.priority < other.priority


class TelegramHandler:
    """
    Thread-safe Telegram bot handler with message queue.

    Features:
    - Asynchronous message sending via queue
    - Automatic retry with exponential backoff
    - Rate limiting (configurable delay between messages)
    - Support for multiple message types
    - Graceful shutdown

    Example:
        handler = TelegramHandler(config)
        handler.start()

        # Async (queued) sending
        handler.send_text("Hello!")
        handler.send_video("/path/to/video.mp4")

        # Sync sending with retries
        success = handler.send_text_sync("Important message")

        # Cleanup
        handler.stop()
    """

    def __init__(self, config: TelegramConfig):
        """
        Initialize the Telegram handler.

        Args:
            config: TelegramConfig with bot_token and chat_id
        """
        self._config = config
        self._bot: Optional[telepot.Bot] = None
        self._chat_id = config.chat_id
        self._message_queue: PriorityQueue[QueuedMessage] = PriorityQueue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._send_lock = threading.Lock()
        self._initialized = False

    def start(self) -> bool:
        """
        Start the Telegram handler and worker thread.

        Returns:
            True if started successfully, False otherwise
        """
        if self._running:
            logger.warning("Telegram handler already running")
            return True

        try:
            self._bot = telepot.Bot(self._config.bot_token)
            # Verify bot is working
            self._bot.getMe()
            self._initialized = True
            logger.info("Telegram bot initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
            return False

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="TelegramWorker",
            daemon=True
        )
        self._worker_thread.start()
        logger.info("Telegram handler started")
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the Telegram handler gracefully.

        Args:
            timeout: Maximum seconds to wait for worker thread
        """
        if not self._running:
            return

        self._running = False

        # Wait for remaining messages to be sent
        try:
            self._message_queue.join()
        except Exception:
            pass


        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)

        logger.info("Telegram handler stopped")

    def _worker_loop(self) -> None:
        """Worker thread that processes the message queue."""
        while self._running:
            try:
                # Non-blocking get with timeout
                try:
                    message = self._message_queue.get(timeout=0.5)
                except Empty:
                    continue

                success = self._send_message(message)

                if not success and message.retry_count < self._config.retry_attempts:
                    # Requeue for retry with exponential backoff
                    message.retry_count += 1
                    delay = self._config.retry_delay * (2 ** (message.retry_count - 1))
                    logger.info(f"Retrying in {delay}s (attempt {message.retry_count})")
                    time.sleep(delay)
                    self._message_queue.put(message)
                elif not success:
                    logger.error(f"Failed to send message after {message.retry_count} attempts")

                self._message_queue.task_done()

                # Rate limiting
                time.sleep(self._config.rate_limit_delay)

            except Exception as e:
                logger.error(f"Worker loop error: {e}")

    def _send_message(self, message: QueuedMessage) -> bool:
        """
        Send a single message to Telegram.

        Args:
            message: QueuedMessage to send

        Returns:
            True if sent successfully, False otherwise
        """
        if not self._bot or not self._initialized:
            logger.error("Bot not initialized")
            return False

        try:
            with self._send_lock:
                if message.message_type == MessageType.TEXT:
                    kwargs = {}
                    if message.parse_mode:
                        kwargs['parse_mode'] = message.parse_mode
                    self._bot.sendMessage(self._chat_id, str(message.content), **kwargs)

                elif message.message_type == MessageType.VIDEO:
                    self._send_file(
                        message.content,
                        self._bot.sendVideo,
                        'video',
                        message.caption
                    )

                elif message.message_type == MessageType.IMAGE:
                    self._send_file(
                        message.content,
                        self._bot.sendPhoto,
                        'photo',
                        message.caption
                    )

                elif message.message_type == MessageType.DOCUMENT:
                    self._send_file(
                        message.content,
                        self._bot.sendDocument,
                        'document',
                        message.caption
                    )

            logger.debug(f"Sent {message.message_type.name} message")
            return True

        except TelegramError as e:
            logger.error(f"Telegram API error: {e}")
            return False
        except FileNotFoundError:
            logger.error(f"File not found: {message.content}")
            message.retry_count = self._config.retry_attempts  # permanent failure, skip retries
            return False
        except Exception as e:
            logger.error(f"Error sending {message.message_type.name}: {e}")
            return False

    def _send_file(
        self,
        content: Union[str, bytes, BinaryIO],
        send_func: Callable,
        param_name: str,
        caption: Optional[str]
    ) -> None:
        """
        Send a file (video, image, document) to Telegram.

        Args:
            content: File path, bytes, or file-like object
            send_func: Bot method to call (sendVideo, sendPhoto, etc.)
            param_name: Parameter name for the file (video, photo, document)
            caption: Optional caption
        """
        kwargs = {'caption': caption} if caption else {}

        if isinstance(content, str):
            # File path
            with open(content, 'rb') as f:
                send_func(self._chat_id, **{param_name: f}, **kwargs)
        elif isinstance(content, bytes):
            # Raw bytes
            send_func(self._chat_id, **{param_name: io.BytesIO(content)}, **kwargs)
        else:
            # File-like object (BytesIO, etc.)
            send_func(self._chat_id, **{param_name: content}, **kwargs)

    # === Public API: Async (Queued) Methods ===

    def send_text(self, text: str, parse_mode: Optional[str] = None) -> None:
        """
        Queue a text message for sending.

        Args:
            text: Message text
            parse_mode: Optional Telegram parse mode ('HTML' or 'Markdown')
        """
        if not text:
            return
        message = QueuedMessage(MessageType.TEXT, text, parse_mode=parse_mode)
        self._message_queue.put(message)

    def send_video(
        self,
        video_path: str,
        caption: Optional[str] = None
    ) -> None:
        """
        Queue a video for sending.

        Args:
            video_path: Path to video file
            caption: Optional caption
        """
        message = QueuedMessage(MessageType.VIDEO, video_path, caption)
        self._message_queue.put(message)

    def send_image(
        self,
        image_path: str,
        caption: Optional[str] = None
    ) -> None:
        """
        Queue an image for sending.

        Args:
            image_path: Path to image file
            caption: Optional caption
        """
        message = QueuedMessage(MessageType.IMAGE, image_path, caption)
        self._message_queue.put(message)

    def send_document(
        self,
        doc_path: str,
        caption: Optional[str] = None
    ) -> None:
        """
        Queue a document for sending.

        Args:
            doc_path: Path to document file
            caption: Optional caption
        """
        message = QueuedMessage(MessageType.DOCUMENT, doc_path, caption)
        self._message_queue.put(message)

    # === Public API: Sync Methods ===

    def send_text_sync(self, text: str) -> bool:
        """
        Send a text message synchronously with retries.

        Args:
            text: Message text

        Returns:
            True if sent successfully
        """
        if not self._bot or not self._initialized:
            logger.error("Bot not initialized")
            return False

        for attempt in range(self._config.retry_attempts):
            try:
                with self._send_lock:
                    self._bot.sendMessage(self._chat_id, text)
                return True
            except Exception as e:
                if attempt < self._config.retry_attempts - 1:
                    delay = self._config.retry_delay * (2 ** attempt)
                    logger.warning(f"Retry {attempt + 1}: {e}, waiting {delay}s")
                    time.sleep(delay)
                else:
                    logger.error(f"Failed after {self._config.retry_attempts} attempts: {e}")

        return False

    def send_image_buffer(
        self,
        buffer: Union[bytes, BinaryIO],
        caption: str = ''
    ) -> bool:
        """
        Send an image from a bytes buffer synchronously.

        Args:
            buffer: Image data as bytes or BytesIO
            caption: Optional caption

        Returns:
            True if sent successfully
        """
        if not self._bot or not self._initialized:
            return False

        try:
            with self._send_lock:
                if isinstance(buffer, bytes):
                    buffer = io.BytesIO(buffer)
                self._bot.sendPhoto(self._chat_id, photo=buffer, caption=caption)
            return True
        except Exception as e:
            logger.error(f"Error sending image buffer: {e}")
            return False

    def send_video_sync(
        self,
        video_path: str,
        caption: Optional[str] = None
    ) -> bool:
        """
        Send a video synchronously.

        Args:
            video_path: Path to video file
            caption: Optional caption

        Returns:
            True if sent successfully
        """
        if not self._bot or not self._initialized:
            return False

        try:
            with self._send_lock:
                with open(video_path, 'rb') as video:
                    self._bot.sendVideo(self._chat_id, video=video, caption=caption)
            return True
        except Exception as e:
            logger.error(f"Error sending video: {e}")
            return False

    # === Bot Command Menu ===

    def set_my_commands(self, commands: list) -> bool:
        """
        Register commands with Telegram so they appear as a clickable menu.

        Args:
            commands: List of dicts with 'command' and 'description' keys
                      e.g. [{'command': 'start', 'description': 'Start the bot'}]

        Returns:
            True if registered successfully
        """
        if not self._bot or not self._initialized:
            return False
        try:
            import requests
            url = f"https://api.telegram.org/bot{self._config.bot_token}/setMyCommands"
            response = requests.post(url, json={'commands': commands}, timeout=10)
            result = response.json()
            if result.get('ok'):
                logger.info(f"Registered {len(commands)} bot commands with Telegram menu")
                return True
            else:
                logger.warning(f"setMyCommands failed: {result}")
                return False
        except Exception as e:
            logger.error(f"setMyCommands error: {e}")
            return False

    # === Bot Message Loop ===

    def start_message_loop(self, handler_callback: Callable) -> threading.Thread:
        """
        Start the Telegram bot message loop in a separate thread.

        Args:
            handler_callback: Function to handle incoming messages

        Returns:
            The thread running the message loop
        """
        if not self._bot:
            raise RuntimeError("Bot not initialized. Call start() first.")

        def run_loop():
            try:
                self._bot.message_loop(handler_callback)
                # Keep thread alive
                while self._running:
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Message loop error: {e}")

        thread = threading.Thread(
            target=run_loop,
            name="TelegramBotLoop",
            daemon=True
        )
        thread.start()
        logger.info("Telegram bot message loop started")
        return thread

    # === Properties ===

    @property
    def is_running(self) -> bool:
        """Check if handler is running."""
        return self._running

    @property
    def is_initialized(self) -> bool:
        """Check if bot is initialized."""
        return self._initialized

    @property
    def queue_size(self) -> int:
        """Get number of messages in queue."""
        return self._message_queue.qsize()

    @property
    def chat_id(self) -> str:
        """Get the configured chat ID."""
        return self._chat_id

    @property
    def bot(self) -> Optional[telepot.Bot]:
        """Get the underlying bot instance."""
        return self._bot
