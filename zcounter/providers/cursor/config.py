from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ENV_CONFIG = "ZCOUNTER_CURSOR_CONFIG"


class CursorConfigError(Exception):
    pass


@dataclass(frozen=True)
class CursorConfig:
    enabled: bool
    cookie_header: str | None
    path: Path
    warnings: tuple[str, ...] = ()


def resolve_config_path() -> tuple[Path, bool]:
    override = os.environ.get(ENV_CONFIG)
    if override:
        return Path(override).expanduser(), True

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "zcounter" / "cursor.toml", False
    return Path.home() / ".config" / "zcounter" / "cursor.toml", False


def load_cursor_config() -> CursorConfig | None:
    path, explicit = resolve_config_path()
    if not path.exists():
        if explicit:
            raise CursorConfigError(f"cursor config path was not found: {path}")
        return None
    if not path.is_file():
        raise CursorConfigError(f"cursor config path is not a file: {path}")

    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise CursorConfigError(f"cursor config is not valid TOML: {path}") from exc
    except OSError as exc:
        raise CursorConfigError(f"cursor config could not be read: {path}") from exc

    cursor = data.get("cursor")
    if not isinstance(cursor, dict):
        return CursorConfig(enabled=False, cookie_header=None, path=path, warnings=_permission_warnings(path))

    enabled = _bool_value(cursor.get("enabled"), default=False)
    cookie_header = _clean_cookie_header(cursor.get("cookie_header"))
    return CursorConfig(
        enabled=enabled,
        cookie_header=cookie_header,
        path=path,
        warnings=_permission_warnings(path),
    )


def _bool_value(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return default


def _clean_cookie_header(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if cleaned.lower().startswith("cookie:"):
        cleaned = cleaned.split(":", 1)[1].strip()
    return cleaned or None


def _permission_warnings(path: Path) -> tuple[str, ...]:
    try:
        mode = path.stat().st_mode
    except OSError:
        return ()
    if os.name == "nt":
        return ()
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        return (f"cursor config file is readable by group/other: {path}",)
    return ()
