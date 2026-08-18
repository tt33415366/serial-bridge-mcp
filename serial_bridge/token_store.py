"""Load, generate, and persist the Hub Access Token."""
from __future__ import annotations

import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from serial_bridge.config import DEFAULT_CONFIG_PATH

DEFAULT_TOKEN_FILENAME = "serial_bridge.token"

_store: TokenStore | None = None


@dataclass
class TokenStore:
    path: Path
    file_token: str

    @property
    def token(self) -> str:
        env_token = os.environ.get("SERIAL_BRIDGE_TOKEN")
        if env_token and env_token.strip():
            return env_token.strip()
        return self.file_token

    def valid_bearer(self, authorization: str | None) -> bool:
        token = self.token
        if not token or authorization is None:
            return False
        return secrets.compare_digest(authorization, f"Bearer {token}")


def resolve_token_path(config_path: Path, environ: Mapping[str, str]) -> Path:
    override = environ.get("SERIAL_BRIDGE_TOKEN_FILE")
    if override:
        return Path(override)
    return config_path.parent / DEFAULT_TOKEN_FILENAME


def _read_token_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    return token or None


def _write_token_file(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(token)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
    except BaseException:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def load_or_create_token_store(
    *,
    config_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> TokenStore:
    env = os.environ if environ is None else environ
    resolved_config_path = config_path or Path(
        env.get("SERIAL_BRIDGE_CONFIG", DEFAULT_CONFIG_PATH)
    )
    token_path = resolve_token_path(resolved_config_path, env)
    env_token = env.get("SERIAL_BRIDGE_TOKEN")
    env_token = env_token.strip() if env_token and env_token.strip() else None

    file_token = _read_token_file(token_path)
    if env_token is not None and file_token is None:
        _write_token_file(token_path, env_token)
        file_token = env_token
    elif file_token is None:
        file_token = secrets.token_urlsafe(32)
        _write_token_file(token_path, file_token)

    return TokenStore(path=token_path, file_token=file_token)


def init_token_store(
    *,
    config_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> TokenStore:
    global _store
    _store = load_or_create_token_store(config_path=config_path, environ=environ)
    return _store


def get_token_store() -> TokenStore:
    if _store is None:
        raise RuntimeError("Access Token store is not initialized")
    return _store


def reset_token_store() -> None:
    global _store
    _store = None


def runtime_access_token() -> str:
    env_token = os.environ.get("SERIAL_BRIDGE_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()
    return get_token_store().file_token


def valid_bearer_token(authorization: str | None) -> bool:
    if authorization is None:
        return False
    try:
        token = runtime_access_token()
    except RuntimeError:
        return False
    if not token:
        return False
    return secrets.compare_digest(authorization, f"Bearer {token}")


def env_overrides_token() -> bool:
    env_token = os.environ.get("SERIAL_BRIDGE_TOKEN")
    return bool(env_token and env_token.strip())


def rotate_access_token() -> tuple[str, bool]:
    """Rewrite the secrets file with a new token and return (token, env_overrides)."""
    store = get_token_store()
    new_token = secrets.token_urlsafe(32)
    _write_token_file(store.path, new_token)
    store.file_token = new_token
    return new_token, env_overrides_token()
