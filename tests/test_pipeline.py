# -*- coding: utf-8 -*-
"""
Тестове за main.py — целият конвейер от чат съобщение до опашката за звук.

Синтезът е подставен (иначе тестовете щяха да искат интернет), но всичко
останало е истинско: модерация, транслитерация, избор на глас, команди,
дневник и — най-важното — че нищо не събаря цикъла.
"""

import asyncio
import sys
import wave
import io
import math
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import main as main_mod  # noqa: E402
from config import Config  # noqa: E402
from tiktok_source import ChatMessage  # noqa: E402
from tts import SynthesisResult, TTSError  # noqa: E402


def fake_wav(seconds: float = 0.05, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(
            b"".join(
                struct.pack("<h", int(8000 * math.sin(i * 2 * math.pi * 440 / rate)))
                for i in range(int(rate * seconds))
            )
        )
    return buf.getvalue()


@pytest.fixture
def bot(tmp_path, monkeypatch):
    """Бот с истинска логика, но подставен синтез и без истински звук."""
    cfg = Config(path=tmp_path / "config.json")
    cfg.set("moderation.blocklist_file", "няма.txt", save=False)
    cfg.set("moderation.user_cooldown", 0, save=False)
    cfg.set("moderation.duplicate_window", 0, save=False)
    cfg.set("hotkeys.enabled", False, save=False)

    monkeypatch.setattr(main_mod, "VoiceStore", lambda *a, **k: _MemStore())
    bot = main_mod.TTSBot(config=cfg)
    bot.engine.cache_dir = tmp_path / "cache"
    bot.engine.enable_cache = False

    synthesized = []

    async def fake_synth(text, preset=None):
        preset = preset or bot.roster.default()
        synthesized.append((text, preset.id))
        return SynthesisResult(audio=fake_wav(), preset=preset, text=text)

    bot.engine.synthesize = fake_synth
    bot.synthesized = synthesized

    played = []
    bot.player.enqueue = lambda clip: played.append(clip) or True
    bot.played = played
    return bot


class _MemStore:
    """VoiceStore в паметта — да не пишем по диска в тестовете."""

    def __init__(self):
        self._d = {}

    @staticmethod
    def _key(u):
        return str(u or "").strip().lstrip("@").lower()

    def get(self, u):
        return self._d.get(self._key(u))

    def set(self, u, v):
        self._d[self._key(u)] = v

    def clear(self, u=None):
        self._d.clear() if u is None else self._d.pop(self._key(u), None)

    def __len__(self):
        return len(self._d)

    def as_dict(self):
        return dict(self._d)


def handle(bot, message):
    asyncio.run(bot._handle(message))


def msg(text, username="ivan", **kwargs):
    return ChatMessage(username=username, text=text, **kwargs)


# ---------------------------------------------------------------------------
# Основният път
# ---------------------------------------------------------------------------


def test_shlyokavitsa_reaches_the_speaker(bot):
    """Целият смисъл: 'kak si be' от чата -> 'как си бе' в колоните."""
    handle(bot, msg("kak si be"))
    assert len(bot.played) == 1
    spoken_text, _ = bot.synthesized[0]
    assert spoken_text == "как си бе"

    record = bot.history[-1]
    assert record.status == "прочетено"
    assert record.original == "kak si be"
    assert record.spoken == "как си бе"
    assert record.voice


def test_cyrillic_passes_through(bot):
    handle(bot, msg("здравей как си"))
    assert bot.synthesized[0][0] == "здравей как си"


def test_leet_is_transliterated(bot):
    handle(bot, msg("6te doida"))
    assert bot.synthesized[0][0] == "ще дойда"


def test_english_is_not_letter_mapped(bot):
    handle(bot, msg("gg wp"))
    assert bot.synthesized[0][0] == "джиджи дабълю пи"


def test_blocked_message_is_not_spoken(bot):
    bot.config.set("moderation.only_followers", True, save=False)
    handle(bot, msg("здр", is_follower=False))
    assert bot.played == []
    assert bot.history[-1].status == "спряно"
    assert bot.history[-1].reason == "не е последовател"


def test_emoji_only_is_not_spoken(bot):
    handle(bot, msg("😂😂😂"))
    assert bot.played == []
    assert bot.history[-1].status == "спряно"


def test_message_that_transliterates_to_nothing(bot):
    """Съобщение, което оцелява модерацията, но няма какво да се каже."""
    bot.config.set("moderation.drop_emoji_only", False, save=False)
    handle(bot, msg("🔥🔥"))
    assert bot.played == []
    assert bot.history[-1].reason == "нищо за изговаряне"


def test_truncated_message_is_marked(bot):
    bot.config.set("moderation.max_length", 20, save=False)
    handle(bot, msg("днес беше страхотен ден и искам да ви разкажа всичко за него"))
    assert len(bot.played) == 1
    record = bot.history[-1]
    assert record.original.endswith("...")
    assert len(record.original) == 20


# ---------------------------------------------------------------------------
# Избор на глас
# ---------------------------------------------------------------------------


def test_same_viewer_always_gets_same_voice(bot):
    for _ in range(5):
        handle(bot, msg("здр", username="ivan"))
    voices = {v for _, v in bot.synthesized}
    assert len(voices) == 1


def test_different_viewers_get_different_voices(bot):
    for i in range(30):
        handle(bot, msg("здр", username=f"user{i}"))
    voices = {v for _, v in bot.synthesized}
    assert len(voices) > 1


def test_host_override_wins(bot):
    bot.config.set("voice.host_override", "hamster", save=False)
    handle(bot, msg("здр", username="ivan"))
    assert bot.synthesized[0][1] == "hamster"


def test_viewer_choice_beats_sticky_hash(bot):
    bot.store.set("ivan", "gigant")
    handle(bot, msg("здр", username="ivan"))
    assert bot.synthesized[0][1] == "gigant"


def test_host_override_beats_viewer_choice(bot):
    bot.store.set("ivan", "gigant")
    bot.config.set("voice.host_override", "kalina", save=False)
    handle(bot, msg("здр", username="ivan"))
    assert bot.synthesized[0][1] == "kalina"


# ---------------------------------------------------------------------------
# Команди в чата
# ---------------------------------------------------------------------------


def test_glas_command_sets_voice(bot):
    handle(bot, msg("!glas 3", username="ivan"))
    third = bot.roster.usable[2]
    assert bot.store.get("ivan") == third.id
    assert bot.history[-1].status == "команда"
    # потвърждението се изговаря с НОВИЯ глас
    assert bot.synthesized[-1][1] == third.id


def test_glas_command_is_not_read_as_text(bot):
    handle(bot, msg("!glas 3"))
    spoken, _ = bot.synthesized[-1]
    assert "!glas" not in spoken
    assert "гласът ти вече е" in spoken.lower()


def test_glas_without_argument_explains(bot):
    handle(bot, msg("!glas"))
    spoken, _ = bot.synthesized[-1]
    assert str(len(bot.roster.usable)) in spoken
    assert bot.store.get("ivan") is None, "без номер нищо не се сменя"


def test_glas_with_bad_argument(bot):
    handle(bot, msg("!glas 999"))
    assert "няма глас" in bot.synthesized[-1][0].lower()
    assert bot.store.get("ivan") is None


def test_glas_by_name(bot):
    handle(bot, msg("!glas Хамстер"))
    assert bot.store.get("ivan") == "hamster"


def test_glas_choice_persists_to_next_message(bot):
    handle(bot, msg("!glas 4", username="ivan"))
    bot.synthesized.clear()
    handle(bot, msg("здравей", username="ivan"))
    assert bot.synthesized[0][1] == bot.roster.usable[3].id


def test_glas_command_can_be_disabled(bot):
    bot.config.set("voice.allow_chat_command", False, save=False)
    handle(bot, msg("!glas 3"))
    # чете се като обикновен текст, не като команда
    assert bot.history[-1].status != "команда"


# ---------------------------------------------------------------------------
# Име на зрителя
# ---------------------------------------------------------------------------


def test_username_prefix_when_enabled(bot):
    bot.config.set("moderation.read_username", True, save=False)
    handle(bot, msg("kak si", username="ivan", nickname="Иван"))
    spoken, _ = bot.synthesized[0]
    assert spoken.startswith("Иван казва:")
    assert "как си" in spoken


def test_username_prefix_off_by_default(bot):
    handle(bot, msg("kak si", username="ivan", nickname="Иван"))
    assert bot.synthesized[0][0] == "как си"


def test_latin_nickname_is_transliterated_in_prefix(bot):
    bot.config.set("moderation.read_username", True, save=False)
    handle(bot, msg("здр", username="ivan", nickname="Ivancho"))
    assert bot.synthesized[0][0].startswith("иванчо казва:")


# ---------------------------------------------------------------------------
# Устойчивост — нищо не бива да събаря конвейера
# ---------------------------------------------------------------------------


def test_synthesis_failure_is_logged_not_fatal(bot):
    async def boom(text, preset=None):
        raise TTSError("Няма връзка със сървъра на Microsoft.")

    bot.engine.synthesize = boom
    handle(bot, msg("здравей"))
    assert bot.played == []
    assert bot.history[-1].status == "грешка"
    assert "Microsoft" in bot.history[-1].detail
    assert bot.error_count == 1


def test_decode_failure_is_logged_not_fatal(bot):
    async def bad_audio(text, preset=None):
        return SynthesisResult(
            audio="това не е звук".encode("utf-8"),
            preset=bot.roster.default(),
            text=text,
        )

    bot.engine.synthesize = bad_audio
    handle(bot, msg("здравей"))
    assert bot.played == []
    assert bot.history[-1].status == "грешка"


def test_pipeline_survives_a_bad_message_and_keeps_going(bot):
    """Едно счупено съобщение не бива да спре четенето на следващите."""

    async def go():
        bot._loop = asyncio.get_running_loop()
        worker = asyncio.create_task(bot._pipeline())

        class Exploding:
            username = "лош"
            nickname = ""
            is_follower = True
            is_moderator = False
            is_gifter = False

            @property
            def text(self):
                raise RuntimeError("бум")

        bot._inbox.put_nowait(Exploding())
        bot._inbox.put_nowait(msg("kak si be", username="добър"))
        await asyncio.wait_for(bot._inbox.join(), timeout=5.0)
        worker.cancel()

    asyncio.run(go())
    assert len(bot.played) == 1, "второто съобщение трябваше да мине"
    assert bot.synthesized[-1][0] == "как си бе"


def test_inbox_drops_oldest_when_full(bot):
    bot.config.set("audio.queue_max", 3, save=False)
    for i in range(8):
        bot._on_chat_message(msg(f"съобщение {i}", username=f"u{i}"))
    assert bot._inbox.qsize() == 3
    dropped = [r for r in bot.history if r.reason == "пълна опашка"]
    assert len(dropped) == 5


def test_listener_errors_do_not_break_pipeline(bot):
    bot.listeners.append(lambda kind, payload: 1 / 0)
    handle(bot, msg("kak si be"))
    assert len(bot.played) == 1


# ---------------------------------------------------------------------------
# Състояние за панела
# ---------------------------------------------------------------------------


def test_status_shape(bot):
    status = bot.status()
    for key in ("state", "label", "text", "muted", "volume", "device", "queue"):
        assert key in status
    assert status["label"] == "Готов"


def test_history_is_capped_and_newest_first(bot):
    bot.history = type(bot.history)(maxlen=5)
    for i in range(10):
        handle(bot, msg(f"съобщение {i}", username=f"u{i}"))
    records = bot.history_dicts()
    assert len(records) == 5
    assert records[0]["original"] == "съобщение 9", "най-новото е първо"


def test_history_shows_original_and_transliterated(bot):
    """Панелът показва оригинал -> транслитерация -> глас, за дебъгване на живо."""
    handle(bot, msg("6te doida"))
    record = bot.history_dicts()[0]
    assert record["original"] == "6te doida"
    assert record["spoken"] == "ще дойда"
    assert record["voice"]
    assert record["time"]


def test_control_methods(bot):
    assert bot.set_volume(0.5) == 0.5
    assert bot.toggle_mute() is True
    assert bot.toggle_mute() is False
    bot.skip()
    assert isinstance(bot.clear_queue(), int)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
