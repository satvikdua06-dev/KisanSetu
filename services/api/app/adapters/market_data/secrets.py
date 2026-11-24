"""Secrets are referenced by name in source configs and resolved here, never stored in config."""

import os
from typing import Protocol


class SecretReader(Protocol):
    def get(self, name: str) -> str: ...


class MissingSecretError(KeyError):
    pass


class EnvSecretReader:
    """Reads secrets from environment variables. Production swaps this for a secret-manager reader."""

    def get(self, name: str) -> str:
        value = os.environ.get(name)
        if not value:
            raise MissingSecretError(f"secret '{name}' is not set")
        return value


class RecordingSecretReader:
    """Wraps a reader and remembers every value handed out, so errors can be scrubbed before they are shown."""

    def __init__(self, inner: SecretReader):
        self._inner = inner
        self.values: set[str] = set()

    def get(self, name: str) -> str:
        value = self._inner.get(name)
        self.values.add(value)
        return value

    def redact(self, text: str) -> str:
        for value in sorted(self.values, key=len, reverse=True):
            if value:
                text = text.replace(value, "***")
        return text


class DictSecretReader:
    """For tests and dry runs."""

    def __init__(self, values: dict[str, str]):
        self._values = values

    def get(self, name: str) -> str:
        try:
            return self._values[name]
        except KeyError:
            raise MissingSecretError(f"secret '{name}' is not set") from None
