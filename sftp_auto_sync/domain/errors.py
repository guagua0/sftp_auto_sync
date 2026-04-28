from __future__ import annotations


class AppError(Exception):
    pass


class ValidationError(AppError):
    def __init__(self, messages: str | list[str]):
        if isinstance(messages, str):
            messages = [messages]
        self.messages = list(messages)
        super().__init__('\n'.join(self.messages))


class RetryableError(AppError):
    pass


class NonRetryableError(AppError):
    pass


class ConnectionError(AppError):
    pass


class AuthError(AppError):
    pass


class HostKeyError(AppError):
    pass


class UploadError(AppError):
    pass


class SkippedTaskError(NonRetryableError):
    pass
