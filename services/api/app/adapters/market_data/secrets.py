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


class DictSecretReader:
    """For tests and dry runs."""

    def __init__(self, values: dict[str, str]):
        self._values = values

    def get(self, name: str) -> str:
        try:
            return self._values[name]
        except KeyError:
            raise MissingSecretError(f"secret '{name}' is not set") from None
