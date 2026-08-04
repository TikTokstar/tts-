# -*- coding: utf-8 -*-
"""
Тестове за tiktok_source.py — без истинска връзка с TikTok.

Проверяваме точно това, което иска заданието: нормализация на името,
изчакване вместо грешка, когато не си на живо, пресвързване с нарастващо
изчакване, и четими български съобщения за всяка грешка.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import tiktok_source as ts  # noqa: E402
from tiktok_source import ChatMessage, SourceState, normalize_username  # noqa: E402


# ---------------------------------------------------------------------------
# Нормализация на потребителското име
# ---------------------------------------------------------------------------

GOOD_NAMES = [
    ("potrebitel", "potrebitel"),
    ("@potrebitel", "potrebitel"),
    ("  @potrebitel  ", "potrebitel"),
    ("https://www.tiktok.com/@potrebitel", "potrebitel"),
    ("https://tiktok.com/@potrebitel", "potrebitel"),
    ("http://www.tiktok.com/@potrebitel/live", "potrebitel"),
    ("www.tiktok.com/@potrebitel", "potrebitel"),
    ("tiktok.com/@potrebitel", "potrebitel"),
    ("https://www.tiktok.com/@potrebitel?lang=bg", "potrebitel"),
    ("https://www.tiktok.com/@potrebitel/live?is_from=copy", "potrebitel"),
    ("@potrebitel/", "potrebitel"),
    ("user.name_123", "user.name_123"),
    ("@user.name_123", "user.name_123"),
]


@pytest.mark.parametrize("raw,expected", GOOD_NAMES)
def test_normalize_username(raw, expected):
    assert normalize_username(raw) == expected


BAD_NAMES = ["", "   ", None, "@", "https://www.tiktok.com/", "име с интервали", "@@@"]


@pytest.mark.parametrize("raw", BAD_NAMES)
def test_normalize_username_rejects_junk(raw):
    with pytest.raises(ValueError) as err:
        normalize_username(raw)
    # съобщението трябва да е на български
    assert any(c in "абвгдежзийклмнопрстуфхцчшщъьюя" for c in str(err.value).lower())


# ---------------------------------------------------------------------------
# Изчакване с нарастване
# ---------------------------------------------------------------------------


def test_backoff_grows_and_caps():
    b = ts.Backoff(start=2.0, maximum=16.0)
    delays = [b.next_delay() for _ in range(8)]
    # расте
    assert delays[0] < delays[1] < delays[2]
    # но не над тавана (плюс разсейването)
    assert all(d <= 16.0 * 1.2 for d in delays)
    assert b.attempts == 8


def test_backoff_resets():
    b = ts.Backoff(start=2.0)
    for _ in range(5):
        b.next_delay()
    b.reset()
    assert b.attempts == 0
    assert b.next_delay() < 3.0


# ---------------------------------------------------------------------------
# Състояния
# ---------------------------------------------------------------------------


def test_every_state_has_bulgarian_label():
    for state in SourceState:
        label = ts.STATE_LABELS[state]
        assert label
        assert any(c in "абвгдежзийклмнопрстуфхцчшщъьюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЬЮЯ" for c in label)


def test_spec_states_are_present():
    labels = set(ts.STATE_LABELS.values())
    for required in ("Свързване", "На живо", "Не е на живо", "Прекъснато"):
        assert required in labels


def test_state_callback_errors_do_not_propagate():
    def boom(state, text):
        raise RuntimeError("панелът гръмна")

    source = ts.ConsoleSource(on_state=boom)
    source._set_state(SourceState.LIVE, "тест")  # не бива да вдига
    assert source.state is SourceState.LIVE


def test_message_callback_errors_do_not_propagate():
    def boom(msg):
        raise RuntimeError("обработката гръмна")

    source = ts.ConsoleSource(on_message=boom)
    source.feed("ivan", "здр")  # не бива да вдига


# ---------------------------------------------------------------------------
# Преобразуване на събитие -> ChatMessage
# ---------------------------------------------------------------------------


def test_event_to_message():
    event = SimpleNamespace(
        content="kak si be",
        user=SimpleNamespace(
            unique_id="ivan",
            display_id="ivan",
            nickname="Иван",
            id_str="12345",
            follow_info=SimpleNamespace(follow_status=1),
            is_subscribe=True,
            user_role=0,
        ),
    )
    msg = ts.TikTokSource._to_message(event)
    assert msg.username == "ivan"
    assert msg.nickname == "Иван"
    assert msg.text == "kak si be"
    assert msg.user_id == "12345"
    assert msg.is_follower is True
    assert msg.is_subscriber is True
    assert msg.display_name == "Иван"


def test_event_to_message_survives_missing_fields():
    """TikTok праща и полусчупени събития — не бива да гърмим."""
    msg = ts.TikTokSource._to_message(SimpleNamespace(content="здр", user=None))
    assert msg.username == "неизвестен"
    assert msg.text == "здр"
    assert msg.is_follower is False

    msg2 = ts.TikTokSource._to_message(SimpleNamespace())
    assert msg2.text == ""


def test_non_follower_detected():
    event = SimpleNamespace(
        content="здр",
        user=SimpleNamespace(
            unique_id="pesho",
            nickname="Пешо",
            follow_info=SimpleNamespace(follow_status=0),
        ),
    )
    assert ts.TikTokSource._to_message(event).is_follower is False


# ---------------------------------------------------------------------------
# Цикълът на свързване (с подставен клиент)
# ---------------------------------------------------------------------------


class FakeClient:
    """Заместител на TikTokLiveClient, който можем да караме да се проваля."""

    def __init__(self, live=True, start_error=None, live_error=None):
        self._live = live
        self._start_error = start_error
        self._live_error = live_error
        self.listeners = {}
        self.disconnected = False
        self.web = SimpleNamespace(set_session=lambda *a: None)

    def add_listener(self, event, handler):
        self.listeners[event] = handler

    async def is_live(self):
        if self._live_error:
            raise self._live_error
        return self._live

    async def start(self, **kwargs):
        if self._start_error:
            raise self._start_error
        return asyncio.get_running_loop().create_future()  # виси, докато е "жив"

    async def disconnect(self, close_client=False):
        self.disconnected = True


def run_one_pass(source, fake, timeout=1.0):
    """Пуска _connect_once веднъж с подставен клиент."""
    source._build_client = lambda: fake

    async def go():
        try:
            await asyncio.wait_for(source._connect_once(), timeout=timeout)
        except asyncio.TimeoutError:
            pass  # LIVE виси нарочно

    asyncio.run(go())


def test_offline_user_waits_instead_of_erroring():
    """Пускам бота преди streamа — трябва да чака, не да гърми."""
    states = []
    source = ts.TikTokSource(
        on_state=lambda s, t: states.append((s, t)), retry_seconds=0.05
    )
    source.username = "potrebitel"
    run_one_pass(source, FakeClient(live=False))
    assert SourceState.WAITING in [s for s, _ in states]
    text = [t for s, t in states if s is SourceState.WAITING][0]
    assert "не е на живо" in text.lower()


def test_live_user_reaches_live_state():
    states = []
    source = ts.TikTokSource(on_state=lambda s, t: states.append((s, t)))
    source.username = "potrebitel"
    run_one_pass(source, FakeClient(live=True), timeout=0.4)
    assert SourceState.LIVE in [s for s, _ in states]


def test_user_not_found_is_fatal():
    from TikTokLive.client import errors as tt_errors

    states = []
    source = ts.TikTokSource(on_state=lambda s, t: states.append((s, t)))
    source.username = "nqma_takuv"
    source._running = True
    run_one_pass(
        source, FakeClient(live_error=tt_errors.UserNotFoundError("не съществува"))
    )
    assert source.state is SourceState.ERROR
    assert source._running is False, "няма смисъл да опитваме пак"
    assert "Няма такъв потребител" in source.status_text


def test_offline_error_during_start_waits():
    from TikTokLive.client import errors as tt_errors

    source = ts.TikTokSource(retry_seconds=0.05)
    source.username = "potrebitel"
    run_one_pass(
        source, FakeClient(start_error=tt_errors.UserOfflineError("офлайн"))
    )
    assert source.state is SourceState.WAITING


def test_blocked_connection_suggests_sessionid():
    from TikTokLive.client import errors as tt_errors

    source = ts.TikTokSource()
    source.username = "potrebitel"
    source._backoff = ts.Backoff(start=0.01, maximum=0.01)
    source.blocked_min_wait = 0.01
    run_one_pass(
        source,
        FakeClient(start_error=tt_errors.WebcastBlocked200Error("блокирано")),
    )
    assert source.state is SourceState.RECONNECTING
    assert "TIKTOK_SESSIONID" in source.status_text


def test_unknown_error_still_reconnects():
    """Непозната грешка не бива да събаря бота."""
    source = ts.TikTokSource()
    source.username = "potrebitel"
    source._backoff = ts.Backoff(start=0.01, maximum=0.01)
    run_one_pass(source, FakeClient(start_error=RuntimeError("нещо странно")))
    assert source.state is SourceState.RECONNECTING
    assert "нещо странно" in source.status_text


def test_age_restricted_mentions_sessionid():
    from TikTokLive.client import errors as tt_errors

    source = ts.TikTokSource()
    source.username = "potrebitel"
    source._running = True
    run_one_pass(
        source, FakeClient(start_error=tt_errors.AgeRestrictedError("18+"))
    )
    assert source.state is SourceState.ERROR
    assert "TIKTOK_SESSIONID" in source.status_text


def test_rate_limit_wait_uses_retry_after():
    exc = SimpleNamespace(retry_after=42)
    assert ts.TikTokSource._rate_limit_wait(exc) == 42.0
    # без подсказка от TikTok — разумно подразбиране
    assert ts.TikTokSource._rate_limit_wait(RuntimeError("х")) == 30.0


# ---------------------------------------------------------------------------
# EventSource като абстракция
# ---------------------------------------------------------------------------


def test_event_source_is_abstract():
    with pytest.raises(TypeError):
        ts.EventSource()


def test_console_source_can_be_swapped_in():
    """Панелът работи с EventSource, не с TikTokSource — това е смисълът."""
    seen = []
    source = ts.ConsoleSource(on_message=seen.append)
    assert isinstance(source, ts.EventSource)
    source.feed("ivan", "kak si")
    assert seen[0].username == "ivan"
    assert seen[0].text == "kak si"


def test_start_normalizes_username():
    source = ts.TikTokSource()

    async def go():
        source._run_loop = lambda: asyncio.sleep(0)  # без истински цикъл
        await source.start("https://www.tiktok.com/@potrebitel/live")
        await source.stop()

    asyncio.run(go())
    assert source.username == "potrebitel"


def test_start_rejects_bad_username():
    source = ts.TikTokSource()
    with pytest.raises(ValueError):
        asyncio.run(source.start("не е име"))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
