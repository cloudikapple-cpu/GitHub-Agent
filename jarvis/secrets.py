"""Secrets in the OS keychain instead of in a file next to the code.

An API key in ``.env`` is one screenshot, one `git add .` or one shared folder
away from being public. The keychain (Windows Credential Manager, macOS
Keychain, Secret Service on Linux) keeps it out of the repository entirely.

Anywhere a key is expected, write a reference instead::

    api_key: keyring:NVIDIA_API_KEY
    api_key: keyring:jarvis-work/NVIDIA_API_KEY   # explicit service name

:func:`resolve` turns that into the real value at load time. If the keychain is
unavailable or empty, the environment variable of the same name is tried, and
an unresolvable reference becomes an empty string rather than an exception --
``jarvis --doctor`` then reports a missing key, which is the honest diagnosis.
"""

from __future__ import annotations

import logging
import os
from typing import Any

#: Default keychain service (the "application" the secret belongs to).
SERVICE = "jarvis"
#: Marker that turns a config value into a keychain lookup.
PREFIX = "keyring:"

LOGGER = logging.getLogger(__name__)


def _keyring() -> Any | None:
    try:
        import keyring
    except Exception:  # noqa: BLE001 - an optional dependency, and a fragile one
        return None
    return keyring


def available() -> bool:
    """True when a usable keychain backend is installed."""

    module = _keyring()
    if module is None:
        return False
    try:
        backend = module.get_keyring()
    except Exception:  # noqa: BLE001
        return False
    # keyring ships a 'fail' backend that raises on every call.
    return "fail" not in type(backend).__name__.lower()


def backend_name() -> str:
    """Human-readable name of the active keychain, or an empty string."""

    module = _keyring()
    if module is None:
        return ""
    try:
        return type(module.get_keyring()).__name__
    except Exception:  # noqa: BLE001
        return ""


# ----------------------------------------------------------------------
def get_secret(name: str, service: str = SERVICE) -> str:
    """Read a secret. Missing keychain, missing entry and errors all give ""."""

    module = _keyring()
    if module is None or not name:
        return ""
    try:
        return module.get_password(service, name) or ""
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Could not read '%s' from the keychain: %s", name, exc)
        return ""


def set_secret(name: str, value: str, service: str = SERVICE) -> bool:
    module = _keyring()
    if module is None:
        return False
    try:
        module.set_password(service, name, value)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Could not store '%s' in the keychain: %s", name, exc)
        return False
    return True


def delete_secret(name: str, service: str = SERVICE) -> bool:
    module = _keyring()
    if module is None:
        return False
    try:
        module.delete_password(service, name)
    except Exception:  # noqa: BLE001 - deleting what is not there is not an error
        return False
    return True


# ----------------------------------------------------------------------
def is_reference(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith(PREFIX)


def parse_reference(value: str) -> tuple[str, str]:
    """Split ``keyring:service/NAME`` into ``(service, name)``."""

    body = value.strip()[len(PREFIX) :].strip()
    if "/" in body:
        service, _, name = body.partition("/")
        return service.strip() or SERVICE, name.strip()
    return SERVICE, body


def resolve(value: Any) -> Any:
    """Replace a ``keyring:`` reference with the secret behind it.

    Values that are not references are returned unchanged, so this is safe to
    call on every setting.
    """

    if not is_reference(value):
        return value
    service, name = parse_reference(str(value))
    secret = get_secret(name, service)
    if secret:
        return secret
    # A keychain miss is common on CI and in containers: fall back to the
    # environment so the same config works in both places.
    return os.getenv(name, "")
