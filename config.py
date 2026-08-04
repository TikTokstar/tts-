#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py — настройките (config.json) и запомнените гласове по зрител.

Всичко има разумна стойност по подразбиране, така че липсващ или счупен
config.json не спира бота — просто се пише наново.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_STORE_PATH = BASE_DIR / "voices_state.json"


DEFAULTS: Dict[str, Any] = {
    "tiktok": {
        "username": "",
        "auto_connect": False,
        "retry_seconds": 30,
    },
    "voice": {
        "default_preset": "borislav",
        "sticky_per_viewer": True,
        "allow_chat_command": True,
        "command": "!glas",
        "host_override": None,
        "rate_offset": 0,
    },
    "audio": {
        "device": "",
        "volume": 1.0,
        "queue_max": 15,
    },
    "tts": {
        "cache_enabled": True,
        "cache_max_mb": 200,
        "timeout": 12.0,
        "retries": 1,
    },
    "translit": {
        "emoji_mode": "drop",
        "url_word": "линк",
        "mention_mode": "read",
        "collapse_repeats": True,
    },
    "moderation": {
        "max_length": 200,
        "truncate_suffix": "...",
        "user_cooldown": 8.0,
        "rate_limit_per_min": 20,
        "duplicate_window": 30.0,
        "drop_emoji_only": True,
        "drop_link_only": True,
        "blocklist_file": "blocklist.txt",
        "only_followers": False,
        "only_gifters": False,
        "trigger_prefix_enabled": False,
        "trigger_prefix": "!tts",
        "read_username": False,
        "username_template": "{name} казва",
    },
    "hotkeys": {
        "enabled": True,
        "skip": "<ctrl>+<alt>+s",
        "mute": "<ctrl>+<alt>+m",
    },
    "panel": {
        "host": "127.0.0.1",
        "port": 8777,
        "history_size": 20,
        "open_browser": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Слива прочетеното върху подразбиранията, без да губи нови ключове."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _atomic_write(path: Path, text: str) -> None:
    """Записва през временен файл — прекъснат запис не убива настройките."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Config:
    """Настройките, с достъп по път: cfg.get('moderation.max_length')."""

    def __init__(self, path: Path = DEFAULT_CONFIG_PATH, data: Optional[dict] = None):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.data: Dict[str, Any] = _deep_merge(DEFAULTS, data or {})

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> "Config":
        path = Path(path)
        raw: dict = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("config.json трябва да е обект")
            except Exception as exc:
                log.error(
                    "config.json не се чете (%s) — продължавам с подразбиранията", exc
                )
                raw = {}
        cfg = cls(path=path, data=raw)
        if not path.exists():
            cfg.save()
        return cfg

    def save(self) -> None:
        with self._lock:
            try:
                _atomic_write(
                    self.path,
                    json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
                )
            except Exception as exc:
                log.error("config.json не може да се запише: %s", exc)

    def get(self, dotted: str, default: Any = None) -> Any:
        with self._lock:
            node: Any = self.data
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return node

    def set(self, dotted: str, value: Any, save: bool = True) -> None:
        with self._lock:
            parts = dotted.split(".")
            node = self.data
            for part in parts[:-1]:
                if part not in node or not isinstance(node[part], dict):
                    node[part] = {}
                node = node[part]
            node[parts[-1]] = value
        if save:
            self.save()

    def update(self, values: Dict[str, Any], save: bool = True) -> None:
        for dotted, value in values.items():
            self.set(dotted, value, save=False)
        if save:
            self.save()

    def section(self, name: str) -> dict:
        value = self.get(name, {})
        return dict(value) if isinstance(value, dict) else {}

    def as_dict(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.data)


class VoiceStore:
    """Кой зрител кой глас е избрал. Малък JSON, писан атомарно."""

    def __init__(self, path: Path = DEFAULT_STORE_PATH):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data: Dict[str, str] = {}
        self.load()

    @staticmethod
    def _key(username: str) -> str:
        return str(username or "").strip().lstrip("@").lower()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = {
                    self._key(k): str(v) for k, v in raw.items() if isinstance(v, str)
                }
        except Exception as exc:
            log.warning("Запомнените гласове не се четат (%s) — започвам наново", exc)
            self._data = {}

    def save(self) -> None:
        with self._lock:
            try:
                _atomic_write(
                    self.path,
                    json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
                )
            except Exception as exc:
                log.error("Запомнените гласове не се записват: %s", exc)

    def get(self, username: str) -> Optional[str]:
        with self._lock:
            return self._data.get(self._key(username))

    def set(self, username: str, preset_id: str) -> None:
        with self._lock:
            self._data[self._key(username)] = str(preset_id)
        self.save()

    def clear(self, username: Optional[str] = None) -> None:
        with self._lock:
            if username is None:
                self._data.clear()
            else:
                self._data.pop(self._key(username), None)
        self.save()

    def __len__(self) -> int:
        return len(self._data)

    def as_dict(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._data)
