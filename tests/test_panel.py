# -*- coding: utf-8 -*-
"""
Тестове за контролния панел.

Панелът е тънък слой над TTSBot — тук проверяваме, че всяка ръчка стига
до бота и че промените важат веднага, без рестарт.
"""

import asyncio
import io
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import main as main_mod  # noqa: E402
from config import Config  # noqa: E402
from tts import SynthesisResult  # noqa: E402

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


def silent_wav(seconds: float = 0.02, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", 0) for _ in range(int(rate * seconds))))
    return buf.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    from panel.app import build_app

    cfg = Config(path=tmp_path / "config.json")
    cfg.set("hotkeys.enabled", False, save=False)
    cfg.set("panel.open_browser", False, save=False)
    cfg.set("moderation.blocklist_file", "няма.txt", save=False)

    monkeypatch.setattr(main_mod, "VoiceStore", lambda *a, **k: _MemStore())
    bot = main_mod.TTSBot(config=cfg)
    bot.engine.enable_cache = False

    async def fake_synth(text, preset=None):
        return SynthesisResult(
            audio=silent_wav(), preset=preset or bot.roster.default(), text=text
        )

    bot.engine.synthesize = fake_synth
    bot.player.enqueue = lambda clip: True

    app = build_app(bot)
    with TestClient(app) as test_client:
        test_client.bot = bot
        yield test_client


class _MemStore:
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


# ---------------------------------------------------------------------------
# Страница и начални данни
# ---------------------------------------------------------------------------


def test_page_loads_and_is_in_bulgarian(client):
    res = client.get("/")
    assert res.status_code == 200
    body = res.text
    for word in ("Свържи", "Прекъсни", "Заглуши", "Модерация", "Гласове"):
        assert word in body, f"липсва надпис: {word}"


def test_bootstrap_has_everything_the_page_needs(client):
    data = client.get("/api/bootstrap").json()
    assert set(data) >= {"status", "history", "voices", "devices", "config"}
    assert len(data["voices"]) >= 8
    assert data["voices"][0]["number"] == 1
    assert "moderation" in data["config"]


def test_status_endpoint(client):
    status = client.get("/api/status").json()
    assert status["label"] == "Готов"
    assert status["muted"] is False


# ---------------------------------------------------------------------------
# Връзка
# ---------------------------------------------------------------------------


def test_connect_normalizes_a_pasted_url(client):
    res = client.post(
        "/api/connect", json={"username": "https://www.tiktok.com/@proba/live"}
    ).json()
    assert res["ok"] is True
    assert "@proba" in res["message"]
    assert client.bot.config.get("tiktok.username") == "proba"


def test_connect_rejects_junk_with_bulgarian_message(client):
    res = client.post("/api/connect", json={"username": "не е име"}).json()
    assert res["ok"] is False
    assert "потребителско име" in res["message"]


def test_connect_without_username(client):
    res = client.post("/api/connect", json={}).json()
    assert res["ok"] is False


def test_disconnect(client):
    assert client.post("/api/disconnect", json={}).json()["ok"] is True


# ---------------------------------------------------------------------------
# Звук и гласове
# ---------------------------------------------------------------------------


def test_volume_reaches_the_player(client):
    res = client.post("/api/volume", json={"volume": 0.4}).json()
    assert res["volume"] == 0.4
    assert client.bot.player.volume == 0.4


def test_volume_rejects_junk(client):
    assert client.post("/api/volume", json={"volume": "силно"}).json()["ok"] is False


def test_speed_is_clamped_and_stored(client):
    assert client.post("/api/speed", json={"offset": 25}).json()["offset"] == 25
    assert client.bot.config.get("voice.rate_offset") == 25
    assert client.post("/api/speed", json={"offset": 9999}).json()["offset"] == 100


def test_speed_changes_the_actual_rate(client):
    """Плъзгачът трябва да стигне до заявката към Microsoft."""
    client.post("/api/speed", json={"offset": 20})
    preset = client.bot.roster.by_id("borislav")  # +0%
    assert preset.with_rate_offset(20).rate == "+20%"
    spiker = client.bot.roster.by_id("spiker")  # +18%
    assert spiker.with_rate_offset(20).rate == "+38%"
    # самият пресет не се променя — иначе стойността щеше да се трупа
    assert spiker.rate == "+18%"


def test_voice_test_button(client):
    res = client.post("/api/voice/test", json={"preset": "hamster"}).json()
    assert res["ok"] is True
    assert "Хамстер" in res["message"]


def test_voice_test_with_unknown_preset(client):
    res = client.post("/api/voice/test", json={"preset": "няма-такъв"}).json()
    assert res["ok"] is False


def test_voice_override(client):
    res = client.post("/api/voice/override", json={"preset": "gigant"}).json()
    assert res["ok"] is True
    assert client.bot.config.get("voice.host_override") == "gigant"
    assert client.bot.pick_preset("който и да е").id == "gigant"

    client.post("/api/voice/override", json={"preset": ""})
    assert client.bot.config.get("voice.host_override") is None


def test_forget_voices(client):
    client.bot.store.set("ivan", "hamster")
    assert client.post("/api/voice/forget", json={}).json()["ok"] is True
    assert client.bot.store.get("ivan") is None


def test_device_list_endpoint(client):
    assert isinstance(client.get("/api/devices").json(), list)


# ---------------------------------------------------------------------------
# Управление
# ---------------------------------------------------------------------------


def test_control_buttons(client):
    assert client.post("/api/control/skip", json={}).json()["ok"] is True
    assert client.post("/api/control/clear", json={}).json()["ok"] is True

    res = client.post("/api/control/mute", json={}).json()
    assert res["muted"] is True
    assert client.bot.player.muted is True

    res = client.post("/api/control/mute", json={"muted": False}).json()
    assert res["muted"] is False


# ---------------------------------------------------------------------------
# Настройки без рестарт
# ---------------------------------------------------------------------------


def test_config_change_applies_immediately(client):
    """Заданието го иска изрично: промяна в панела важи веднага."""
    res = client.post(
        "/api/config",
        json={"moderation.max_length": 42, "moderation.only_followers": True},
    ).json()
    assert res["ok"] is True
    assert client.bot.config.get("moderation.max_length") == 42

    from tiktok_source import ChatMessage

    decision = client.bot.moderator.check(
        ChatMessage(username="x", text="здр", is_follower=False)
    )
    assert decision.allowed is False, "новата настройка трябва да важи веднага"


def test_config_volume_reaches_player(client):
    client.post("/api/config", json={"audio.volume": 0.3})
    assert client.bot.player.volume == 0.3


def test_config_ignores_bad_keys(client):
    res = client.post("/api/config", json={"безточка": 1}).json()
    assert res["applied"] == {}


def test_config_rejects_empty(client):
    assert client.post("/api/config", json={}).json()["ok"] is False


def test_config_is_persisted(client, tmp_path):
    client.post("/api/config", json={"moderation.max_length": 77})
    assert Config.load(tmp_path / "config.json").get("moderation.max_length") == 77


# ---------------------------------------------------------------------------
# Живият изглед
# ---------------------------------------------------------------------------


def test_history_shows_original_and_transliteration(client):
    from tiktok_source import ChatMessage

    asyncio.run(client.bot._handle(ChatMessage(username="ivan", text="6te doida")))
    records = client.get("/api/history").json()
    assert records[0]["original"] == "6te doida"
    assert records[0]["spoken"] == "ще дойда"
    assert records[0]["voice"]
    assert records[0]["time"]


def test_websocket_sends_hello_and_live_messages(client):
    from tiktok_source import ChatMessage

    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["kind"] == "hello"
        assert "status" in hello

        asyncio.run(client.bot._handle(ChatMessage(username="ivan", text="kak si be")))
        event = ws.receive_json()
        assert event["kind"] == "message"
        assert event["original"] == "kak si be"
        assert event["spoken"] == "как си бе"


def test_cache_clear_endpoint(client):
    assert client.post("/api/cache/clear", json={}).json()["ok"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
