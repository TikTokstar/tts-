#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tiktok_source.py — връзка с чата на TikTok Live.

Всичко минава през абстракцията `EventSource`, за да може по-късно да се
сложи TikFinity WebSocket източник, без да се пипа останалата програма.
Останалата част от бота вижда само `ChatMessage` и `SourceState`.

Правила на връзката:
  - Приема "@user", "user" или поднесен профилен адрес.
  - Ако още не си на живо — НЕ гърми, а чака и пробва пак на всеки 30 с.
  - Ако връзката падне по време на streamа — пресвързване с нарастващо
    изчакване (2, 4, 8 ... до 60 с, с малко разсейване).
  - "Потребителят не съществува" е единствената фатална грешка — при нея
    няма смисъл да опитваме пак.

CLI (стъпка 3 — само печата съобщенията на конзолата):
    python tiktok_source.py @potrebitel
    python tiktok_source.py https://www.tiktok.com/@potrebitel --raw
"""

from __future__ import annotations

import abc
import asyncio
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

DEFAULT_RETRY_SECONDS = 30.0
BACKOFF_START = 2.0
BACKOFF_MAX = 60.0


# ---------------------------------------------------------------------------
# Имена
# ---------------------------------------------------------------------------

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,24}$")


def normalize_username(raw: str) -> str:
    """'@user', 'user', 'https://www.tiktok.com/@user/live' -> 'user'.

    Вдига ValueError с четимо съобщение, ако не остане нищо смислено.
    """
    if raw is None:
        raise ValueError("Не си въвел потребителско име.")
    text = str(raw).strip()
    if not text:
        raise ValueError("Не си въвел потребителско име.")

    if "tiktok.com" in text.lower() or text.lower().startswith(("http://", "https://")):
        candidate = text if "://" in text else "https://" + text
        path = urlparse(candidate).path or ""
        for part in path.split("/"):
            if part.startswith("@") and len(part) > 1:
                text = part
                break
        else:
            parts = [p for p in path.split("/") if p]
            text = parts[0] if parts else text

    text = text.split("?")[0].split("#")[0]
    text = text.strip().lstrip("@").strip().rstrip("/")

    if not text:
        raise ValueError("Не разпознах потребителско име в това, което въведе.")
    if not _USERNAME_RE.match(text):
        raise ValueError(
            f"'{text}' не прилича на TikTok потребителско име. "
            "Въведи го като @име или като адрес на профила."
        )
    return text


# ---------------------------------------------------------------------------
# Общи типове
# ---------------------------------------------------------------------------


class SourceState(str, Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    LIVE = "live"
    WAITING = "waiting"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


#: Кратки надписи за индикатора в панела.
STATE_LABELS = {
    SourceState.IDLE: "Готов",
    SourceState.CONNECTING: "Свързване",
    SourceState.LIVE: "На живо",
    SourceState.WAITING: "Не е на живо",
    SourceState.RECONNECTING: "Пресвързване",
    SourceState.DISCONNECTED: "Прекъснато",
    SourceState.ERROR: "Грешка",
}


@dataclass
class ChatMessage:
    username: str
    text: str
    nickname: str = ""
    user_id: str = ""
    is_follower: bool = False
    is_subscriber: bool = False
    is_moderator: bool = False
    is_gifter: bool = False
    timestamp: float = field(default_factory=time.time)
    raw: Any = None

    @property
    def display_name(self) -> str:
        return self.nickname or self.username


class EventSource(abc.ABC):
    """Общият вход. TikTok днес, TikFinity утре — без промени другаде."""

    def __init__(
        self,
        on_message: Optional[Callable[[ChatMessage], None]] = None,
        on_state: Optional[Callable[[SourceState, str], None]] = None,
    ) -> None:
        self.on_message = on_message
        self.on_state = on_state
        self._state = SourceState.IDLE
        self._status_text = STATE_LABELS[SourceState.IDLE]
        self.username: str = ""

    @property
    def state(self) -> SourceState:
        return self._state

    @property
    def status_label(self) -> str:
        return STATE_LABELS.get(self._state, "—")

    @property
    def status_text(self) -> str:
        return self._status_text

    @property
    def is_live(self) -> bool:
        return self._state is SourceState.LIVE

    def _set_state(self, state: SourceState, text: str = "") -> None:
        self._state = state
        self._status_text = text or STATE_LABELS.get(state, "")
        log.info("[%s] %s", STATE_LABELS.get(state, state), self._status_text)
        if self.on_state:
            try:
                self.on_state(state, self._status_text)
            except Exception:
                log.exception("Грешка в обработчика на състоянието")

    def _emit(self, message: ChatMessage) -> None:
        if not self.on_message:
            return
        try:
            self.on_message(message)
        except Exception:
            # Едно лошо съобщение не бива да събаря връзката.
            log.exception("Грешка при обработката на съобщение")

    @abc.abstractmethod
    async def start(self, username: str) -> None: ...

    @abc.abstractmethod
    async def stop(self) -> None: ...


# ---------------------------------------------------------------------------
# Изчакване с нарастване
# ---------------------------------------------------------------------------


class Backoff:
    """2, 4, 8, 16 ... до таван, с разсейване, за да не удряме в такт."""

    def __init__(self, start: float = BACKOFF_START, maximum: float = BACKOFF_MAX) -> None:
        self.start = start
        self.maximum = maximum
        self._current = start
        self.attempts = 0

    def reset(self) -> None:
        self._current = self.start
        self.attempts = 0

    def next_delay(self) -> float:
        delay = min(self._current, self.maximum)
        self._current = min(self._current * 2, self.maximum)
        self.attempts += 1
        return delay * (0.8 + random.random() * 0.4)


# ---------------------------------------------------------------------------
# TikTok
# ---------------------------------------------------------------------------


class TikTokSource(EventSource):
    """Чатът на TikTok Live през пакета TikTokLive."""

    def __init__(
        self,
        on_message: Optional[Callable[[ChatMessage], None]] = None,
        on_state: Optional[Callable[[SourceState, str], None]] = None,
        retry_seconds: float = DEFAULT_RETRY_SECONDS,
        session_id: Optional[str] = None,
        tt_target_idc: Optional[str] = None,
    ) -> None:
        super().__init__(on_message=on_message, on_state=on_state)
        self.retry_seconds = float(retry_seconds)
        self.session_id = session_id or os.getenv("TIKTOK_SESSIONID") or None
        self.tt_target_idc = tt_target_idc or os.getenv("TIKTOK_TARGET_IDC") or None
        self._client = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._backoff = Backoff()
        #: Долна граница на изчакването, когато TikTok блокира анонимна
        #: връзка — по-често от това само влошава нещата.
        self.blocked_min_wait = 15.0
        self.messages_seen = 0
        self.connected_at: Optional[float] = None

    # -- жизнен цикъл ------------------------------------------------------

    async def start(self, username: str) -> None:
        self.username = normalize_username(username)
        if self._running:
            await self.stop()
        self._running = True
        self._backoff.reset()
        self._task = asyncio.create_task(self._run_loop(), name="tiktok-source")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        await self._close_client()
        self.connected_at = None
        self._set_state(SourceState.DISCONNECTED, "Връзката е прекъсната.")

    async def _close_client(self) -> None:
        """Затваря клиента, без да оставя недоизчакани корутини след себе си."""
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            if getattr(client, "connected", False):
                await client.disconnect(close_client=True)
            else:
                # Клиент, който никога не се е свързал: disconnect() влиза в
                # пътища, разчитащи на жив websocket. Затваряме само HTTP-то.
                close = getattr(getattr(client, "web", None), "close", None)
                if close is not None:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result
        except Exception as exc:
            log.debug("Затварянето на клиента гръмна (без значение): %s", exc)

    # -- клиент ------------------------------------------------------------

    def _build_client(self):
        from TikTokLive import TikTokLiveClient
        from TikTokLive.events import CommentEvent, DisconnectEvent, LiveEndEvent

        client = TikTokLiveClient(unique_id=self.username)

        if self.session_id:
            try:
                client.web.set_session(self.session_id, self.tt_target_idc)
                log.info("Ползвам TIKTOK_SESSIONID от .env")
            except Exception as exc:
                log.warning("SESSIONID не можа да се приложи: %s", exc)

        async def on_comment(event) -> None:
            try:
                self._emit(self._to_message(event))
                self.messages_seen += 1
            except Exception:
                log.exception("Съобщението не можа да се преобразува")

        async def on_live_end(event) -> None:
            log.info("Streamът приключи.")

        async def on_disconnect(event) -> None:
            log.info("TikTok затвори връзката.")

        client.add_listener(CommentEvent, on_comment)
        client.add_listener(LiveEndEvent, on_live_end)
        client.add_listener(DisconnectEvent, on_disconnect)
        return client

    @staticmethod
    def _to_message(event) -> ChatMessage:
        user = getattr(event, "user", None)
        username = ""
        nickname = ""
        user_id = ""
        is_follower = False
        is_subscriber = False
        is_moderator = False

        if user is not None:
            for attr in ("unique_id", "display_id", "nickname"):
                value = getattr(user, attr, None)
                if value:
                    username = str(value)
                    break
            nickname = str(getattr(user, "nickname", "") or "")
            user_id = str(getattr(user, "id_str", "") or getattr(user, "id", "") or "")
            follow_info = getattr(user, "follow_info", None)
            if follow_info is not None:
                is_follower = int(getattr(follow_info, "follow_status", 0) or 0) >= 1
            is_subscriber = bool(getattr(user, "is_subscribe", False))
            try:
                roles = getattr(user, "user_role", None)
                is_moderator = int(roles or 0) == 1
            except Exception:
                is_moderator = False

        return ChatMessage(
            username=username or "неизвестен",
            nickname=nickname,
            text=str(getattr(event, "content", "") or ""),
            user_id=user_id,
            is_follower=is_follower,
            is_subscriber=is_subscriber,
            is_moderator=is_moderator,
            raw=event,
        )

    # -- основният цикъл ---------------------------------------------------

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._connect_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Каквото и да стане — състоянието се обновява и пробваме пак.
                log.exception("Неочакван проблем във връзката")
                delay = self._backoff.next_delay()
                self._set_state(
                    SourceState.RECONNECTING,
                    f"Неочакван проблем ({exc}). Нов опит след {delay:.0f} с.",
                )
                await asyncio.sleep(delay)

    async def _connect_once(self) -> None:
        from TikTokLive.client import errors as tt_errors

        self._set_state(
            SourceState.CONNECTING, f"Свързвам се с @{self.username}..."
        )
        await self._close_client()
        self._client = self._build_client()

        try:
            live = await self._client.is_live()
        except tt_errors.UserNotFoundError:
            self._running = False
            self._set_state(
                SourceState.ERROR,
                f"Няма такъв потребител: @{self.username}. Провери името.",
            )
            return
        except Exception as exc:
            live = None
            log.debug("Проверката 'на живо ли е' се провали: %s", exc)

        if live is False:
            self._set_state(
                SourceState.WAITING,
                f"@{self.username} не е на живо. Проверявам пак след "
                f"{self.retry_seconds:.0f} с.",
            )
            await asyncio.sleep(self.retry_seconds)
            return

        try:
            task = await self._client.start(fetch_live_check=False)
            self.connected_at = time.time()
            self._backoff.reset()
            self._set_state(
                SourceState.LIVE, f"Свързан с чата на @{self.username}."
            )
            await task  # държи, докато връзката е жива

        except tt_errors.UserNotFoundError:
            self._running = False
            self._set_state(
                SourceState.ERROR,
                f"Няма такъв потребител: @{self.username}. Провери името.",
            )
            return

        except tt_errors.UserOfflineError:
            self._set_state(
                SourceState.WAITING,
                f"@{self.username} не е на живо. Проверявам пак след "
                f"{self.retry_seconds:.0f} с.",
            )
            await asyncio.sleep(self.retry_seconds)
            return

        except tt_errors.AgeRestrictedError:
            self._running = False
            self._set_state(
                SourceState.ERROR,
                "Streamът е с възрастово ограничение — трябва TIKTOK_SESSIONID "
                "в .env, за да се свържа.",
            )
            return

        except tt_errors.SignatureRateLimitError as exc:
            wait = self._rate_limit_wait(exc)
            self._set_state(
                SourceState.RECONNECTING,
                f"TikTok ограничава заявките (rate limit). Изчаквам {wait:.0f} с.",
            )
            await asyncio.sleep(wait)
            return

        except tt_errors.SignAPIError as exc:
            delay = self._backoff.next_delay()
            self._set_state(
                SourceState.RECONNECTING,
                f"Сървърът за подписване не отговаря ({exc}). "
                f"Нов опит след {delay:.0f} с.",
            )
            await asyncio.sleep(delay)
            return

        except tt_errors.WebcastBlocked200Error:
            delay = max(self._backoff.next_delay(), self.blocked_min_wait)
            self._set_state(
                SourceState.RECONNECTING,
                "TikTok блокира анонимната връзка. Опитай с TIKTOK_SESSIONID "
                f"в .env. Нов опит след {delay:.0f} с.",
            )
            await asyncio.sleep(delay)
            return

        except tt_errors.AlreadyConnectedError:
            await self._close_client()
            await asyncio.sleep(1.0)
            return

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            delay = self._backoff.next_delay()
            self._set_state(
                SourceState.RECONNECTING,
                f"Връзката се провали ({exc}). Нов опит след {delay:.0f} с.",
            )
            await asyncio.sleep(delay)
            return

        # Дотук се стига, когато streamът приключи или TikTok затвори връзката.
        if self._running:
            self.connected_at = None
            self._set_state(
                SourceState.WAITING,
                f"Връзката с @{self.username} се разпадна. Проверявам пак след "
                f"{self.retry_seconds:.0f} с.",
            )
            await asyncio.sleep(self.retry_seconds)

    @staticmethod
    def _rate_limit_wait(exc: Exception) -> float:
        try:
            value = getattr(exc, "retry_after", None)
            if value:
                return max(float(value), 5.0)
        except Exception:
            pass
        return 30.0


# ---------------------------------------------------------------------------
# Източник за тестове — чете от конзолата вместо от TikTok
# ---------------------------------------------------------------------------


class ConsoleSource(EventSource):
    """Пише в конзолата вместо да се свързва — за проверка без stream."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self, username: str = "конзола") -> None:
        self.username = username or "конзола"
        self._running = True
        self._set_state(SourceState.LIVE, "Конзолен режим — пиши съобщения.")
        self._task = asyncio.create_task(self._loop(), name="console-source")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        self._set_state(SourceState.DISCONNECTED, "Конзолният режим е спрян.")

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        while self._running:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
            except Exception:
                break
            if not line:
                await asyncio.sleep(0.2)
                continue
            line = line.strip()
            if not line:
                continue
            username, _, text = line.partition(":")
            if not text:
                username, text = "тест", line
            self._emit(
                ChatMessage(username=username.strip(), text=text.strip(), is_follower=True)
            )

    def feed(self, username: str, text: str, **kwargs) -> None:
        """Ръчно подаване — удобно за тестове."""
        self._emit(ChatMessage(username=username, text=text, **kwargs))


# ---------------------------------------------------------------------------
# CLI — стъпка 3: само печата чата
# ---------------------------------------------------------------------------


async def _cli(username: str, show_raw: bool) -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    count = 0

    def on_message(msg: ChatMessage) -> None:
        nonlocal count
        count += 1
        marks = "".join(
            [
                "F" if msg.is_follower else "-",
                "S" if msg.is_subscriber else "-",
                "M" if msg.is_moderator else "-",
            ]
        )
        stamp = time.strftime("%H:%M:%S", time.localtime(msg.timestamp))
        print(f"[{stamp}] {marks} @{msg.username:<20} {msg.text}")
        if show_raw:
            print(f"           никнейм={msg.nickname!r} id={msg.user_id}")

    def on_state(state: SourceState, text: str) -> None:
        print(f"*** [{STATE_LABELS.get(state, state)}] {text}")

    source = TikTokSource(on_message=on_message, on_state=on_state)
    try:
        await source.start(username)
    except ValueError as exc:
        print(f"Грешка: {exc}")
        return 1

    print("Слушам чата. Ctrl+C за изход.\n")
    try:
        while True:
            await asyncio.sleep(1.0)
            if source.state is SourceState.ERROR and not source._running:
                break
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nСпирам...")
    finally:
        await source.stop()
        print(f"Общо съобщения: {count}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    show_raw = "--raw" in argv
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    try:
        return asyncio.run(_cli(args[0], show_raw))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
