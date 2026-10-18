"""Exit-code constants and the exception hierarchy (plan §4.1, frozen)."""

from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_CONVERT = 4
EXIT_VERIFY = 5
EXIT_OUTPUT = 6


class Df2UlogError(Exception):
    """Base class for all df2ulog errors; args[0] is a human-readable message."""


class InputFormatError(Df2UlogError): ...


class DataFlashReadError(Df2UlogError):
    context: str | None = None

    def __init__(self, message: str, context: str | None = None) -> None:
        super().__init__(message)
        self.context = context


class UnsupportedFormatCharError(Df2UlogError):
    char: str = ""
    message_name: str | None = None

    def __init__(
        self,
        message: str,
        char: str = "",
        message_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.char = char
        self.message_name = message_name


class TimeOrderError(Df2UlogError):
    ulog_name: str = ""
    multi_id: int = 0
    previous_us: int = 0
    current_us: int = 0

    def __init__(
        self,
        message: str,
        *,
        ulog_name: str = "",
        multi_id: int = 0,
        previous_us: int = 0,
        current_us: int = 0,
    ) -> None:
        super().__init__(message)
        self.ulog_name = ulog_name
        self.multi_id = multi_id
        self.previous_us = previous_us
        self.current_us = current_us


class OutputExistsError(Df2UlogError): ...


class UlogWriteError(Df2UlogError): ...


class VerificationError(Df2UlogError): ...
