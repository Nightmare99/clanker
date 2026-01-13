"""Logging configuration for Clanker with rolling file support."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal

# Default logging configuration
DEFAULT_LOG_DIR = Path.home() / ".clanker" / "logs"
DEFAULT_LOG_FILE = "clanker.log"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
DEFAULT_BACKUP_COUNT = 3  # Keep 3 backup files
DEFAULT_LOG_LEVEL = "INFO"

# Logger name for the application
LOGGER_NAME = "clanker"

# Format strings
DETAILED_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
SIMPLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"


class ClankerLogger:
    """Centralized logging manager for Clanker."""

    _instance: "ClankerLogger | None" = None
    _initialized: bool = False

    def __new__(cls) -> "ClankerLogger":
        """Singleton pattern to ensure single logger instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the logger (only runs once due to singleton)."""
        if ClankerLogger._initialized:
            return
        ClankerLogger._initialized = True

        self._logger = logging.getLogger(LOGGER_NAME)
        self._logger.setLevel(logging.DEBUG)  # Capture all, filter at handler level
        self._file_handler: RotatingFileHandler | None = None
        self._console_handler: logging.StreamHandler | None = None

    def setup(
        self,
        log_dir: Path | None = None,
        log_file: str = DEFAULT_LOG_FILE,
        level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = DEFAULT_LOG_LEVEL,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
        console_output: bool = False,
        detailed_format: bool = True,
    ) -> None:
        """Configure the logging system.

        Args:
            log_dir: Directory for log files. Defaults to ~/.clanker/logs.
            log_file: Name of the log file.
            level: Minimum log level to capture.
            max_bytes: Maximum size per log file before rotation.
            backup_count: Number of backup files to keep.
            console_output: Whether to also output logs to console.
            detailed_format: Use detailed format with function/line info.
        """
        # Clear existing handlers
        self._logger.handlers.clear()

        # Setup log directory
        log_dir = log_dir or DEFAULT_LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / log_file

        # Choose format
        fmt = DETAILED_FORMAT if detailed_format else SIMPLE_FORMAT
        formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

        # Setup rotating file handler
        self._file_handler = RotatingFileHandler(
            filename=log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        self._file_handler.setLevel(getattr(logging, level))
        self._file_handler.setFormatter(formatter)
        self._logger.addHandler(self._file_handler)

        # Optional console handler (for debugging)
        if console_output:
            self._console_handler = logging.StreamHandler(sys.stderr)
            self._console_handler.setLevel(getattr(logging, level))
            self._console_handler.setFormatter(formatter)

            # Filter out noisy MCP / LangChain connection logs from TUI
            class _NoMCPFilter(logging.Filter):
                def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
                    """Hide MCP connection/setup noise but keep tool execution logs."""
                    name = record.name
                    msg = record.getMessage()

                    # Only suppress low-level MCP connection / transport chatter
                    if name.startswith("langchain_mcp_adapters") or ".mcp" in name:
                        return not any(
                            phrase in msg.lower()
                            for phrase in (
                                "connect",
                                "connecting",
                                "connected",
                                "handshake",
                                "initializ",
                                "opening",
                                "closing",
                                "transport",
                            )
                        )

                    return True

            self._console_handler.addFilter(_NoMCPFilter())
            self._logger.addHandler(self._console_handler)

        self._logger.info(
            "Logging initialized: level=%s, file=%s, max_bytes=%d, backup_count=%d",
            level,
            log_path,
            max_bytes,
            backup_count,
        )

    def get_logger(self, name: str | None = None) -> logging.Logger:
        """Get a logger instance.

        Args:
            name: Optional sub-logger name. If provided, creates a child logger.

        Returns:
            Logger instance.
        """
        if name:
            return self._logger.getChild(name)
        return self._logger

    @property
    def log_path(self) -> Path | None:
        """Get the current log file path."""
        if self._file_handler:
            return Path(self._file_handler.baseFilename)
        return None

    def set_level(self, level: str) -> None:
        """Change the log level at runtime.

        Args:
            level: New log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        """
        log_level = getattr(logging, level.upper(), logging.INFO)
        if self._file_handler:
            self._file_handler.setLevel(log_level)
        if self._console_handler:
            self._console_handler.setLevel(log_level)
        self._logger.info("Log level changed to %s", level)


# Module-level functions for convenience
_manager = ClankerLogger()


def setup_logging(
    log_dir: Path | None = None,
    log_file: str = DEFAULT_LOG_FILE,
    level: str = DEFAULT_LOG_LEVEL,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    console_output: bool = False,
    detailed_format: bool = True,
) -> None:
    """Setup the logging system. Call this once at application startup.

    Args:
        log_dir: Directory for log files. Defaults to ~/.clanker/logs.
        log_file: Name of the log file.
        level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        max_bytes: Maximum size per log file before rotation (default 5MB).
        backup_count: Number of backup files to keep (default 3).
        console_output: Whether to also output logs to console.
        detailed_format: Use detailed format with function/line info.
    """
    _manager.setup(
        log_dir=log_dir,
        log_file=log_file,
        level=level,
        max_bytes=max_bytes,
        backup_count=backup_count,
        console_output=console_output,
        detailed_format=detailed_format,
    )


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Optional module/component name for the logger.

    Returns:
        Logger instance for the specified name.

    Example:
        logger = get_logger("agent")
        logger.info("Agent started")
        logger.debug("Processing message: %s", message)
    """
    return _manager.get_logger(name)


def get_log_path() -> Path | None:
    """Get the current log file path."""
    return _manager.log_path
