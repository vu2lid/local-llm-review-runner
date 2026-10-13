"""Errors that the CLI prints to stderr and turns into exit codes."""


class ReviewError(Exception):
    """Base error. Subclasses set the process exit code."""

    exit_code = 1


class UsageError(ReviewError):
    exit_code = 2


class ProtocolError(ReviewError):
    """Input or model output failed closed."""

    exit_code = 1


class RuntimeFailed(ReviewError):
    exit_code = 1


class RuntimeTimeout(ReviewError):
    exit_code = 1


class BitNetUnavailable(ReviewError):
    """The installed executable was missing or its help text was not verified."""

    exit_code = 2
