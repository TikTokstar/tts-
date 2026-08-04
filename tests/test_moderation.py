# -*- coding: utf-8 -*-
"""
Тестове за moderation.py и config.py.

Това е кодът, който пази живия stream — всяко правило от заданието има
свой тест, включително че по подразбиране НИЩО не е включено излишно.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from config import Config, VoiceStore  # noqa: E402
from moderation import Blocklist, Moderator, Reason  # noqa: E402
from tiktok_source import ChatMessage  # noqa: E402


@pytest.fixture
def cfg(tmp_path):
    config = Config(path=tmp_path / "config.json")
    config.set("moderation.blocklist_file", "няма-такъв.txt", save=False)
    return config


@pytest.fixture
def mod(cfg, tmp_path):
    blocklist = Blocklist(tmp_path / "blocklist.txt")
    return Moderator(cfg, blocklist=blocklist)


def msg(text, username="ivan", **kwargs):
    return ChatMessage(username=username, text=text, **kwargs)


# ---------------------------------------------------------------------------
# Подразбирания: всичко излишно е ИЗКЛЮЧЕНО
# ---------------------------------------------------------------------------


def test_every_message_is_read_by_default(mod):
    """Смисълът на бота — по подразбиране всяко съобщение се чете."""
    assert mod.check(msg("kak si be")).allowed
    assert mod.check(msg("здравей", username="pesho")).allowed
    assert mod.check(msg("нещо друго", username="gosho")).allowed


def test_optional_filters_are_off_by_default(cfg):
    assert cfg.get("moderation.only_followers") is False
    assert cfg.get("moderation.only_gifters") is False
    assert cfg.get("moderation.trigger_prefix_enabled") is False


def test_non_follower_passes_by_default(mod):
    assert mod.check(msg("здр", is_follower=False)).allowed


# ---------------------------------------------------------------------------
# Дължина
# ---------------------------------------------------------------------------


def test_long_message_is_truncated(mod, cfg):
    cfg.set("moderation.max_length", 20, save=False)
    decision = mod.check(msg("а" * 100))
    assert decision.allowed
    assert decision.truncated
    assert len(decision.text) == 20
    assert decision.text.endswith("...")


def test_short_message_is_not_truncated(mod):
    decision = mod.check(msg("кратко"))
    assert decision.allowed
    assert decision.truncated is False
    assert decision.text == "кратко"


def test_max_length_zero_disables_truncation(mod, cfg):
    cfg.set("moderation.max_length", 0, save=False)
    decision = mod.check(msg("б" * 500))
    assert decision.allowed
    assert len(decision.text) == 500


# ---------------------------------------------------------------------------
# Изчакване и лимити
# ---------------------------------------------------------------------------


def test_user_cooldown_blocks_second_message(mod, cfg):
    cfg.set("moderation.user_cooldown", 8.0, save=False)
    assert mod.check(msg("първо")).allowed
    second = mod.check(msg("второ"))
    assert not second.allowed
    assert second.reason == Reason.COOLDOWN
    assert "остават" in second.detail


def test_cooldown_is_per_user(mod, cfg):
    cfg.set("moderation.user_cooldown", 8.0, save=False)
    assert mod.check(msg("здр", username="ivan")).allowed
    assert mod.check(msg("здр2", username="pesho")).allowed, "друг зрител не бива да чака"


def test_cooldown_expires(mod, cfg):
    cfg.set("moderation.user_cooldown", 0.05, save=False)
    assert mod.check(msg("първо")).allowed
    time.sleep(0.08)
    assert mod.check(msg("второ")).allowed


def test_global_rate_limit(mod, cfg):
    cfg.set("moderation.rate_limit_per_min", 3, save=False)
    cfg.set("moderation.user_cooldown", 0, save=False)
    cfg.set("moderation.duplicate_window", 0, save=False)
    allowed = [mod.check(msg(f"съобщение {i}", username=f"u{i}")).allowed for i in range(6)]
    assert allowed[:3] == [True, True, True]
    assert allowed[3:] == [False, False, False]
    last = mod.check(msg("още едно", username="друг"))
    assert last.reason == Reason.RATE_LIMIT


def test_rejected_messages_do_not_eat_the_rate_limit(mod, cfg):
    """Спрените съобщения не бива да изяждат лимита на пуснатите."""
    cfg.set("moderation.rate_limit_per_min", 2, save=False)
    cfg.set("moderation.user_cooldown", 0, save=False)
    cfg.set("moderation.duplicate_window", 0, save=False)
    for i in range(10):
        mod.check(msg("😀😀", username=f"spam{i}"))  # само емоджи -> спряно
    assert mod.check(msg("истинско съобщение", username="ivan")).allowed


# ---------------------------------------------------------------------------
# Повторения
# ---------------------------------------------------------------------------


def test_duplicate_within_window_is_dropped(mod, cfg):
    cfg.set("moderation.duplicate_window", 30.0, save=False)
    cfg.set("moderation.user_cooldown", 0, save=False)
    assert mod.check(msg("едно и също")).allowed
    second = mod.check(msg("едно и също"))
    assert not second.allowed
    assert second.reason == Reason.DUPLICATE


def test_duplicate_from_another_user_is_allowed(mod, cfg):
    cfg.set("moderation.duplicate_window", 30.0, save=False)
    cfg.set("moderation.user_cooldown", 0, save=False)
    assert mod.check(msg("здравей", username="ivan")).allowed
    assert mod.check(msg("здравей", username="pesho")).allowed


def test_duplicate_window_expires(mod, cfg):
    cfg.set("moderation.duplicate_window", 0.05, save=False)
    cfg.set("moderation.user_cooldown", 0, save=False)
    assert mod.check(msg("пак същото")).allowed
    time.sleep(0.08)
    assert mod.check(msg("пак същото")).allowed


# ---------------------------------------------------------------------------
# Само емоджи / само линк
# ---------------------------------------------------------------------------


EMOJI_ONLY = ["😂😂😂", "🔥", "❤️❤️", "   😀  ", "!!!", "???"]


@pytest.mark.parametrize("text", EMOJI_ONLY)
def test_emoji_only_is_dropped(mod, text):
    decision = mod.check(msg(text))
    assert not decision.allowed
    assert decision.reason == Reason.EMOJI_ONLY


LINK_ONLY = [
    "https://example.com",
    "www.example.com",
    "  https://youtu.be/abc123  ",
]


@pytest.mark.parametrize("text", LINK_ONLY)
def test_link_only_is_dropped(mod, text):
    decision = mod.check(msg(text))
    assert not decision.allowed
    assert decision.reason == Reason.LINK_ONLY


def test_link_with_text_is_allowed(mod):
    decision = mod.check(msg("виж това https://example.com яко е"))
    assert decision.allowed


def test_empty_message_is_dropped(mod):
    assert mod.check(msg("")).reason == Reason.EMPTY
    assert mod.check(msg("     ")).reason == Reason.EMPTY


# ---------------------------------------------------------------------------
# Черен списък
# ---------------------------------------------------------------------------


def test_blocklist_word_match(tmp_path, cfg):
    path = tmp_path / "blocklist.txt"
    path.write_text("забранена\n# коментар\nдруга\n", encoding="utf-8")
    mod = Moderator(cfg, blocklist=Blocklist(path))
    decision = mod.check(msg("това е забранена дума"))
    assert not decision.allowed
    assert decision.reason == Reason.BLOCKED
    assert decision.detail == "забранена"


def test_blocklist_matches_whole_words_only(tmp_path, cfg):
    """'пич' не бива да спира 'спичам' — иначе спираме нормални съобщения."""
    path = tmp_path / "blocklist.txt"
    path.write_text("пич\n", encoding="utf-8")
    mod = Moderator(cfg, blocklist=Blocklist(path))
    assert not mod.check(msg("ей пич")).allowed
    assert mod.check(msg("спичам нещо", username="друг")).allowed


def test_blocklist_is_case_insensitive(tmp_path, cfg):
    path = tmp_path / "blocklist.txt"
    path.write_text("спам\n", encoding="utf-8")
    mod = Moderator(cfg, blocklist=Blocklist(path))
    assert not mod.check(msg("СПАМ тук")).allowed


def test_blocklist_regex(tmp_path, cfg):
    path = tmp_path / "blocklist.txt"
    path.write_text("re:(?i)\\bsub4sub\\b\n/^реклама/\n", encoding="utf-8")
    mod = Moderator(cfg, blocklist=Blocklist(path))
    assert not mod.check(msg("SUB4SUB моля")).allowed
    assert not mod.check(msg("реклама тук", username="друг")).allowed
    assert mod.check(msg("нормално съобщение", username="трети")).allowed


def test_broken_regex_is_reported_not_fatal(tmp_path, cfg):
    path = tmp_path / "blocklist.txt"
    path.write_text("re:[невалиден\nдобра\n", encoding="utf-8")
    blocklist = Blocklist(path)
    assert blocklist.errors, "счупеният израз трябва да се докладва"
    assert "ред 1" in blocklist.errors[0]
    mod = Moderator(cfg, blocklist=blocklist)
    assert not mod.check(msg("добра дума")).allowed, "останалите правила работят"


def test_blocklist_reloads_without_restart(tmp_path, cfg):
    """Заданието го иска изрично: промяна във файла важи веднага."""
    path = tmp_path / "blocklist.txt"
    path.write_text("# празен\n", encoding="utf-8")
    blocklist = Blocklist(path, reload_interval=0.0)
    mod = Moderator(cfg, blocklist=blocklist)
    assert mod.check(msg("новадума")).allowed

    time.sleep(0.01)
    path.write_text("новадума\n", encoding="utf-8")
    decision = mod.check(msg("новадума", username="друг"))
    assert not decision.allowed
    assert decision.reason == Reason.BLOCKED


def test_missing_blocklist_file_is_fine(tmp_path, cfg):
    blocklist = Blocklist(tmp_path / "няма.txt")
    assert len(blocklist) == 0
    mod = Moderator(cfg, blocklist=blocklist)
    assert mod.check(msg("каквото и да е")).allowed


# ---------------------------------------------------------------------------
# Незадължителни филтри
# ---------------------------------------------------------------------------


def test_only_followers_when_enabled(mod, cfg):
    cfg.set("moderation.only_followers", True, save=False)
    assert not mod.check(msg("здр", username="a", is_follower=False)).allowed
    assert mod.check(msg("здр", username="b", is_follower=True)).allowed


def test_moderators_bypass_follower_filter(mod, cfg):
    cfg.set("moderation.only_followers", True, save=False)
    decision = mod.check(msg("здр", username="mod", is_follower=False, is_moderator=True))
    assert decision.allowed


def test_only_gifters_when_enabled(mod, cfg):
    cfg.set("moderation.only_gifters", True, save=False)
    assert not mod.check(msg("здр", username="a", is_gifter=False)).allowed
    assert mod.check(msg("здр", username="b", is_gifter=True)).allowed


def test_trigger_prefix_when_enabled(mod, cfg):
    cfg.set("moderation.trigger_prefix_enabled", True, save=False)
    cfg.set("moderation.trigger_prefix", "!tts", save=False)
    assert not mod.check(msg("обикновено съобщение")).allowed
    decision = mod.check(msg("!tts прочети това", username="друг"))
    assert decision.allowed
    assert decision.text == "прочети това", "префиксът не бива да се изговаря"


def test_trigger_prefix_alone_is_empty(mod, cfg):
    cfg.set("moderation.trigger_prefix_enabled", True, save=False)
    assert not mod.check(msg("!tts")).allowed


def test_settings_apply_without_restart(mod, cfg):
    """Панелът сменя настройка — важи от следващото съобщение."""
    assert mod.check(msg("здр", username="a", is_follower=False)).allowed
    cfg.set("moderation.only_followers", True, save=False)
    assert not mod.check(msg("здр", username="b", is_follower=False)).allowed
    cfg.set("moderation.only_followers", False, save=False)
    assert mod.check(msg("здр", username="c", is_follower=False)).allowed


# ---------------------------------------------------------------------------
# Устойчивост
# ---------------------------------------------------------------------------


def test_moderator_never_raises(mod):
    class Broken:
        @property
        def text(self):
            raise RuntimeError("счупено съобщение")

        username = "х"

    decision = mod.check(Broken())
    assert decision.allowed is False  # при съмнение — тихо


def test_stats_are_recorded(mod, cfg):
    cfg.set("moderation.user_cooldown", 0, save=False)
    cfg.set("moderation.duplicate_window", 0, save=False)
    mod.check(msg("нормално"))
    mod.check(msg("😀"))
    mod.check(msg("🔥"))
    assert mod.stats.seen == 3
    assert mod.stats.allowed == 1
    assert mod.stats.dropped == 2
    assert mod.stats.by_reason[Reason.EMOJI_ONLY] == 2


# ---------------------------------------------------------------------------
# config.py
# ---------------------------------------------------------------------------


def test_config_defaults_present(tmp_path):
    cfg = Config.load(tmp_path / "config.json")
    assert cfg.get("moderation.max_length") == 200
    assert cfg.get("moderation.user_cooldown") == 8.0
    assert cfg.get("audio.queue_max") == 15
    assert cfg.get("panel.port") == 8777
    assert (tmp_path / "config.json").exists(), "липсващият config се записва наново"


def test_config_dotted_access(tmp_path):
    cfg = Config(path=tmp_path / "c.json")
    cfg.set("нещо.дълбоко.навътре", 42)
    assert cfg.get("нещо.дълбоко.навътре") == 42
    assert cfg.get("няма.такъв.път", "по подразбиране") == "по подразбиране"


def test_config_survives_broken_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ това не е json", encoding="utf-8")
    cfg = Config.load(path)
    assert cfg.get("moderation.max_length") == 200


def test_config_keeps_unknown_keys_and_adds_new_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"tiktok": {"username": "ivan"}}', encoding="utf-8")
    cfg = Config.load(path)
    assert cfg.get("tiktok.username") == "ivan", "запазва писаното от потребителя"
    assert cfg.get("moderation.max_length") == 200, "допълва новите подразбирания"


def test_config_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config.load(path)
    cfg.set("tiktok.username", "потребител")
    assert Config.load(path).get("tiktok.username") == "потребител"


def test_voice_store_roundtrip(tmp_path):
    store = VoiceStore(tmp_path / "state.json")
    store.set("Ivan", "hamster")
    assert store.get("ivan") == "hamster"
    assert store.get("@IVAN") == "hamster", "регистър и @ не бива да имат значение"
    assert VoiceStore(tmp_path / "state.json").get("ivan") == "hamster"


def test_voice_store_clear(tmp_path):
    store = VoiceStore(tmp_path / "state.json")
    store.set("ivan", "hamster")
    store.set("pesho", "kalina")
    store.clear("ivan")
    assert store.get("ivan") is None
    assert store.get("pesho") == "kalina"
    store.clear()
    assert len(store) == 0


def test_voice_store_survives_broken_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("не е json", encoding="utf-8")
    store = VoiceStore(path)
    assert len(store) == 0
    store.set("ivan", "kalina")
    assert store.get("ivan") == "kalina"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
