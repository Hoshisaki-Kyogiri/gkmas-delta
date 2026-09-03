"""User-facing errors.

Anything raised as a UmeError is printed as a plain Chinese sentence plus a
suggested next step, never as a traceback. Everything else still tracebacks so
real bugs stay visible.
"""


class UmeError(Exception):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


class NetworkError(UmeError):
    pass


class ManifestError(UmeError):
    pass


class DiskSpaceError(UmeError):
    pass


class BackendMissingError(UmeError):
    pass


class ConfigError(UmeError):
    pass
