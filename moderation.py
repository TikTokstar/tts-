#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
moderation.py — филтрите, които пазят живия stream.

Това е нещото, което трябва да работи безотказно: всичко минало оттук
отива директно в колоните пред публика. Затова всяка проверка връща
причина на български, а не просто True/False — за да се вижда в панела
защо едно съобщение не е прочетено.

Ред на проверките (най-евтините първи):
    празно -> тригер префикс -> само последователи/дарители -> команда
    -> черен списък -> само емоджи/само линк -> повторение -> изчакване
    на потребител -> общ лимит -> дължина

blocklist.txt се презарежда сам, щом файлът се промени — без рестарт.

CLI:
    python moderation.py "текст за проверка"
"""

from __future__ import annotations

import logging
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


class Reason:
    """Причини за отхвърляне — на български, готови за панела."""

    EMPTY = "празно съобщение"
    NO_PREFIX = "няма тригер префикс"
    NOT_FOLLOWER = "не е последовател"
    NOT_GIFTER = "не е дарител"
    BLOCKED = "черен списък"
    EMOJI_ONLY = "само емоджи"
    LINK_ONLY = "само линк"
    DUPLICATE = "повторение"
    COOLDOWN = "изчакване на потребителя"
    RATE_LIMIT = "общ лимит на съобщения"
    NOTHING_TO_SAY = "нищо за изговаряне"


@dataclass
class Decision:
    allowed: bool
    text: str = ""
    reason: str = ""
    detail: str = ""
    truncated: bool = False

    def __bool__(self) -> bool:
        return self.allowed


# ---------------------------------------------------------------------------
# Черен списък
# ---------------------------------------------------------------------------


class Blocklist:
    """Думи и регулярни изрази от blocklist.txt, презареждани в движение.

    Формат на файла:
        # ред, започващ с диез, е коментар
        дума              -> съвпада като цяла дума, без значение от регистъра
        re:^спам.*        -> регулярен израз
        /^спам.*/         -> същото, друг запис
    """

    def __init__(self, path: Path, reload_interval: float = 1.0) -> None:
        self.path = Path(path)
        self.reload_interval = reload_interval
        self.words: List[str] = []
        self.patterns: List[Tuple[str, re.Pattern]] = []
        self.errors: List[str] = []
        self._mtime: Optional[float] = None
        self._last_check = 0.0
        self.reload(force=True)

    def maybe_reload(self) -> bool:
        """Презарежда, ако файлът е пипан. Извиква се на всяко съобщение."""
        now = time.monotonic()
        if now - self._last_check < self.reload_interval:
            return False
        self._last_check = now
        try:
            mtime = self.path.stat().st_mtime if self.path.exists() else None
        except OSError:
            return False
        if mtime != self._mtime:
            self.reload(force=True)
            return True
        return False

    def reload(self, force: bool = False) -> None:
        self.words = []
        self.patterns = []
        self.errors = []
        try:
            self._mtime = self.path.stat().st_mtime if self.path.exists() else None
        except OSError:
            self._mtime = None

        if not self.path.exists():
            log.info("Няма %s — черният списък е празен", self.path.name)
            return

        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as exc:
            log.error("Черният списък не се чете: %s", exc)
            return

        for lineno, line in enumerate(lines, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            raw = line
            if line.startswith("re:"):
                raw = line[3:].strip()
            elif len(line) > 1 and line.startswith("/") and line.endswith("/"):
                raw = line[1:-1]
            else:
                self.words.append(line.lower())
                continue
            try:
                self.patterns.append((raw, re.compile(raw, re.IGNORECASE | re.UNICODE)))
            except re.error as exc:
                msg = f"{self.path.name}, ред {lineno}: невалиден регулярен израз ({exc})"
                self.errors.append(msg)
                log.warning(msg)

        log.info(
            "Черен списък: %d думи, %d израза%s",
            len(self.words),
            len(self.patterns),
            f", {len(self.errors)} с грешка" if self.errors else "",
        )

    def match(self, text: str) -> Optional[str]:
        """Връща какво е съвпаднало, или None."""
        if not text:
            return None
        self.maybe_reload()
        low = text.lower()
        for word in self.words:
            # цяла дума, за да не спъваме "пич" заради "спичам"
            if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", low, re.UNICODE):
                return word
        for raw, pattern in self.patterns:
            try:
                if pattern.search(text):
                    return raw
            except Exception:
                continue
        return None

    def __len__(self) -> int:
        return len(self.words) + len(self.patterns)


# ---------------------------------------------------------------------------
# Модератор
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+|\b\S+\.(?:com|net|org|bg|io|me|tv|gg|ly|co|ru)\b")
_WORD_RE = re.compile(r"[0-9A-Za-zЀ-ӿ]", re.UNICODE)


@dataclass
class ModerationStats:
    seen: int = 0
    allowed: int = 0
    dropped: int = 0
    by_reason: Dict[str, int] = field(default_factory=dict)

    def record(self, decision: Decision) -> None:
        self.seen += 1
        if decision.allowed:
            self.allowed += 1
        else:
            self.dropped += 1
            self.by_reason[decision.reason] = self.by_reason.get(decision.reason, 0) + 1


class Moderator:
    """Всички филтри на едно място. Настройките се четат на всяко съобщение,
    за да важат промените от панела веднага, без рестарт."""

    def __init__(self, config, blocklist: Optional[Blocklist] = None) -> None:
        self.config = config
        path = BASE_DIR / str(
            config.get("moderation.blocklist_file", "blocklist.txt")
        )
        # Изрично сравнение с None: Blocklist има __len__, значи празен
        # черен списък е "falsy" и `blocklist or ...` би го изхвърлил.
        self.blocklist = blocklist if blocklist is not None else Blocklist(path)
        self._last_by_user: Dict[str, float] = {}
        self._recent: Deque[Tuple[float, str, str]] = deque(maxlen=200)
        self._minute: Deque[float] = deque(maxlen=1000)
        self.stats = ModerationStats()

    # -- помощни -----------------------------------------------------------

    def _cfg(self, key: str, default=None):
        return self.config.get(f"moderation.{key}", default)

    @staticmethod
    def _has_letters(text: str) -> bool:
        return bool(_WORD_RE.search(text or ""))

    @staticmethod
    def _strip_urls(text: str) -> str:
        return _URL_RE.sub(" ", text or "")

    def reset_user(self, username: str) -> None:
        self._last_by_user.pop(str(username).lower(), None)

    def reset(self) -> None:
        self._last_by_user.clear()
        self._recent.clear()
        self._minute.clear()

    # -- основната проверка ------------------------------------------------

    def check(self, message) -> Decision:
        """message е ChatMessage. Връща Decision с текст за изговаряне."""
        try:
            decision = self._check(message)
        except Exception as exc:
            # Модерацията никога не бива да събаря конвейера. При съмнение
            # съобщението се пропуска — по-добре тихо, отколкото неконтролирано.
            log.exception("Проверката гръмна — пропускам съобщението")
            decision = Decision(False, reason="грешка при проверка", detail=str(exc))
        self.stats.record(decision)
        return decision

    def _check(self, message) -> Decision:
        now = time.monotonic()
        username = str(getattr(message, "username", "") or "").lower()
        text = str(getattr(message, "text", "") or "").strip()

        if not text:
            return Decision(False, reason=Reason.EMPTY)

        # --- тригер префикс (по подразбиране изключен) ---
        if self._cfg("trigger_prefix_enabled", False):
            prefix = str(self._cfg("trigger_prefix", "!tts") or "").strip()
            if prefix:
                if not text.lower().startswith(prefix.lower()):
                    return Decision(False, reason=Reason.NO_PREFIX)
                text = text[len(prefix) :].strip()
                if not text:
                    return Decision(False, reason=Reason.EMPTY)

        # --- само последователи / само дарители (по подразбиране изключени) ---
        if self._cfg("only_followers", False) and not getattr(
            message, "is_follower", False
        ):
            if not getattr(message, "is_moderator", False):
                return Decision(False, reason=Reason.NOT_FOLLOWER)

        if self._cfg("only_gifters", False) and not getattr(message, "is_gifter", False):
            if not getattr(message, "is_moderator", False):
                return Decision(False, reason=Reason.NOT_GIFTER)

        # --- черен списък ---
        hit = self.blocklist.match(text)
        if hit:
            return Decision(False, reason=Reason.BLOCKED, detail=hit)

        # --- само линк / само емоджи ---
        without_urls = self._strip_urls(text)
        if self._cfg("drop_link_only", True) and text != without_urls:
            if not self._has_letters(without_urls):
                return Decision(False, reason=Reason.LINK_ONLY)

        if self._cfg("drop_emoji_only", True) and not self._has_letters(text):
            return Decision(False, reason=Reason.EMOJI_ONLY)

        # --- повторение в прозорец ---
        window = float(self._cfg("duplicate_window", 30.0) or 0)
        if window > 0:
            key = text.lower()
            for stamp, prev_user, prev_text in reversed(self._recent):
                if now - stamp > window:
                    break
                if prev_text == key and prev_user == username:
                    return Decision(False, reason=Reason.DUPLICATE)

        # --- изчакване на потребителя ---
        cooldown = float(self._cfg("user_cooldown", 8.0) or 0)
        if cooldown > 0 and username:
            last = self._last_by_user.get(username)
            if last is not None and now - last < cooldown:
                remaining = cooldown - (now - last)
                return Decision(
                    False,
                    reason=Reason.COOLDOWN,
                    detail=f"остават {remaining:.1f} с",
                )

        # --- общ лимит за минута ---
        limit = int(self._cfg("rate_limit_per_min", 20) or 0)
        if limit > 0:
            while self._minute and now - self._minute[0] > 60.0:
                self._minute.popleft()
            if len(self._minute) >= limit:
                return Decision(
                    False,
                    reason=Reason.RATE_LIMIT,
                    detail=f"{limit} съобщения за минута",
                )

        # --- дължина ---
        truncated = False
        max_length = int(self._cfg("max_length", 200) or 0)
        if max_length > 0 and len(text) > max_length:
            suffix = str(self._cfg("truncate_suffix", "...") or "")
            keep = max(max_length - len(suffix), 1)
            text = text[:keep].rstrip() + suffix
            truncated = True

        # Броим чак сега — отхвърлените не бива да изяждат лимита.
        if username:
            self._last_by_user[username] = now
        self._minute.append(now)
        self._recent.append((now, username, str(getattr(message, "text", "")).lower()))

        return Decision(True, text=text, truncated=truncated)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from config import Config
    from tiktok_source import ChatMessage

    cfg = Config.load()
    mod = Moderator(cfg)
    print(f"Черен списък: {len(mod.blocklist)} правила от {mod.blocklist.path.name}")
    for err in mod.blocklist.errors:
        print(f"  ! {err}")

    if not argv:
        print("\nПиши съобщения (Ctrl+C за изход):")
        try:
            while True:
                line = input("> ")
                if not line.strip():
                    continue
                d = mod.check(ChatMessage(username="тест", text=line, is_follower=True))
                if d.allowed:
                    print(f"  ПУСНАТО: {d.text!r}{' (отрязано)' if d.truncated else ''}")
                else:
                    extra = f" — {d.detail}" if d.detail else ""
                    print(f"  СПРЯНО:  {d.reason}{extra}")
        except (KeyboardInterrupt, EOFError):
            print()
        return 0

    text = " ".join(argv)
    d = mod.check(ChatMessage(username="тест", text=text, is_follower=True))
    if d.allowed:
        print(f"ПУСНАТО: {d.text!r}")
        return 0
    print(f"СПРЯНО: {d.reason}" + (f" — {d.detail}" if d.detail else ""))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
