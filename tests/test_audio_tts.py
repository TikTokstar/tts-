# -*- coding: utf-8 -*-
"""
Тестове за tts.py и audio.py, които НЕ искат нито интернет, нито звукова
карта — точно това, което може да се провери автоматично.

Истинското изсвирване се проверява ръчно:
    python tts.py --say "Здравей" --device "Voicemeeter"
"""

import asyncio
import io
import math
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import audio  # noqa: E402
import tts  # noqa: E402


def make_wav(seconds: float = 0.2, rate: int = 24000, freq: float = 440.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(
            b"".join(
                struct.pack("<h", int(12000 * math.sin(i * 2 * math.pi * freq / rate)))
                for i in range(int(rate * seconds))
            )
        )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# audio.py
# ---------------------------------------------------------------------------


def test_decode_audio_roundtrip():
    clip = audio.decode_audio(make_wav(0.25))
    assert clip.samplerate == 24000
    assert clip.channels == 1
    assert 0.2 < clip.duration < 0.3
    assert len(clip.pcm) == int(24000 * 0.25) * 2


def test_decode_rejects_empty():
    with pytest.raises(audio.AudioError):
        audio.decode_audio(b"")


def test_decode_rejects_garbage():
    with pytest.raises(audio.AudioError):
        audio.decode_audio("това не е звук".encode("utf-8") * 20)


def test_make_tone():
    clip = audio.make_tone(seconds=0.3)
    assert abs(clip.duration - 0.3) < 0.01
    assert clip.channels == 1


def test_volume_scaling():
    pcm = struct.pack("<4h", 1000, -1000, 2000, -2000)
    assert audio._scale_volume(pcm, 1.0) == pcm
    quiet = struct.unpack("<4h", audio._scale_volume(pcm, 0.5))
    assert quiet == (500, -500, 1000, -1000)
    loud = struct.unpack("<4h", audio._scale_volume(pcm, 2.0))
    assert loud == (2000, -2000, 4000, -4000)


def test_volume_does_not_wrap_around():
    """Пресилването трябва да реже, а не да превърта в отрицателно."""
    pcm = struct.pack("<2h", 30000, -30000)
    out = struct.unpack("<2h", audio._scale_volume(pcm, 4.0))
    assert out[0] == 32767
    assert out[1] == -32768


def test_resolve_device_accepts_none_and_digits():
    assert audio.resolve_device(None) is None
    assert audio.resolve_device("") is None
    assert audio.resolve_device("default") is None
    assert audio.resolve_device(7) == 7
    assert audio.resolve_device("7") == 7


def test_resolve_unknown_device_falls_back():
    """Изчезнало устройство не бива да гърми — минаваме на подразбиране."""
    assert audio.resolve_device("Няма такова устройство 12345") is None


def test_queue_drops_oldest_when_full():
    player = audio.AudioPlayer(queue_max=3)  # без start() — нищо не се изсвирва
    for i in range(6):
        clip = audio.make_tone(seconds=0.01)
        clip.meta = {"i": i}
        player.enqueue(clip)
    assert player.queue_size == 3
    assert player.dropped == 3
    remaining = [player._queue.get_nowait().meta["i"] for _ in range(3)]
    assert remaining == [3, 4, 5]  # най-старите са изхвърлени


def test_clear_empties_queue():
    player = audio.AudioPlayer(queue_max=10)
    for _ in range(4):
        player.enqueue(audio.make_tone(seconds=0.01))
    assert player.clear() == 4
    assert player.queue_size == 0


def test_mute_rejects_new_items():
    player = audio.AudioPlayer()
    player.set_mute(True)
    assert player.enqueue(audio.make_tone(seconds=0.01)) is False
    assert player.queue_size == 0
    player.set_mute(False)
    assert player.enqueue(audio.make_tone(seconds=0.01)) is True


def test_volume_is_clamped():
    player = audio.AudioPlayer()
    player.set_volume(-5)
    assert player.volume == 0.0
    player.set_volume(99)
    assert player.volume == 2.0


def test_player_survives_missing_device():
    """Без звукова карта плейърът записва грешка, но не забива."""
    player = audio.AudioPlayer(device="няма такова")
    player.start()
    player.enqueue(audio.make_tone(seconds=0.05))
    deadline = 3.0
    step = 0.05
    while deadline > 0 and (player.queue_size or player.current):
        import time

        time.sleep(step)
        deadline -= step
    player.stop()
    assert player.queue_size == 0  # обработено, независимо дали е успяло


# ---------------------------------------------------------------------------
# tts.py — пресети
# ---------------------------------------------------------------------------


def test_voices_json_loads():
    roster = tts.VoiceRoster.load()
    assert len(roster) >= 8, "заданието иска поне 8 пресета"
    ids = [p.id for p in roster.presets]
    assert len(ids) == len(set(ids)), "id-тата на пресетите трябва да са уникални"


def test_presets_use_real_bg_voices():
    roster = tts.VoiceRoster.load()
    for preset in roster.presets:
        assert preset.voice.startswith("bg-BG-"), preset.id


def test_preset_value_normalization():
    assert tts._fix_signed("20%", "%", "+0%") == "+20%"
    assert tts._fix_signed("-15", "%", "+0%") == "-15%"
    assert tts._fix_signed("+25%", "%", "+0%") == "+25%"
    assert tts._fix_signed("40Hz", "Hz", "+0Hz") == "+40Hz"
    assert tts._fix_signed("глупости", "%", "+0%") == "+0%"
    assert tts._fix_signed("", "%", "+0%") == "+0%"


def test_sticky_voice_per_user():
    roster = tts.VoiceRoster.load()
    first = roster.pick_for_user("ivan")
    for _ in range(50):
        assert roster.pick_for_user("ivan").id == first.id
    # регистърът и @ не бива да променят гласа
    assert roster.pick_for_user("IVAN").id == first.id
    assert roster.pick_for_user("@ivan").id == first.id
    assert roster.pick_for_user("  Ivan  ").id == first.id


def test_sticky_voices_spread_across_presets():
    roster = tts.VoiceRoster.load()
    names = {roster.pick_for_user(f"user{i}").id for i in range(200)}
    assert len(names) >= min(8, len(roster)), "разпределението е прекалено струпано"


def test_resolve_by_number_id_and_name():
    roster = tts.VoiceRoster.load()
    assert roster.resolve("1").id == roster.usable[0].id
    assert roster.resolve("hamster").id == "hamster"
    assert roster.resolve("Калина").id == "kalina"
    assert roster.resolve("няма такъв") is None
    assert roster.resolve("999") is None
    assert roster.resolve(None) is None


def test_missing_voices_file_falls_back(tmp_path):
    roster = tts.VoiceRoster.load(tmp_path / "няма.json")
    assert len(roster) >= 2
    assert roster.default().voice.startswith("bg-BG-")


def test_broken_voices_file_falls_back(tmp_path):
    bad = tmp_path / "voices.json"
    bad.write_text("{ това не е валиден json", encoding="utf-8")
    roster = tts.VoiceRoster.load(bad)
    assert len(roster) >= 2


def test_verify_without_network_keeps_presets_usable(monkeypatch):
    """Без интернет пресетите не бива да се обявяват за невалидни."""
    roster = tts.VoiceRoster.load()

    async def boom():
        raise OSError("няма мрежа")

    import edge_tts

    monkeypatch.setattr(edge_tts, "list_voices", boom)
    report = asyncio.run(roster.verify())
    assert report["ok"] is False
    assert report["error"]
    assert len(roster.usable) == len(roster)


def test_verify_redirects_preset_with_dead_voice(monkeypatch):
    """Ако Microsoft махне глас, пресетът се пренасочва, а не гърми."""
    roster = tts.VoiceRoster([
        tts.VoicePreset("a", "Тест", "bg-BG-НямаТакъвNeural"),
    ])

    async def fake_list():
        return [
            {"ShortName": "bg-BG-BorislavNeural", "Locale": "bg-BG", "Gender": "Male"},
            {"ShortName": "en-US-EmmaNeural", "Locale": "en-US", "Gender": "Female"},
        ]

    import edge_tts

    monkeypatch.setattr(edge_tts, "list_voices", fake_list)
    report = asyncio.run(roster.verify())
    assert report["ok"] is True
    assert report["found"] == ["bg-BG-BorislavNeural"]
    assert report["invalid"] and report["invalid"][0]["preset"] == "a"
    assert roster.presets[0].voice == "bg-BG-BorislavNeural"
    assert roster.presets[0].available is True


# ---------------------------------------------------------------------------
# tts.py — кеш
# ---------------------------------------------------------------------------


def test_cache_key_depends_on_text_and_preset(tmp_path):
    roster = tts.VoiceRoster.load()
    engine = tts.TTSEngine(roster=roster, cache_dir=tmp_path)
    a = roster.by_id("borislav")
    b = roster.by_id("hamster")
    assert engine.cache_key("здравей", a) == engine.cache_key("здравей", a)
    assert engine.cache_key("здравей", a) != engine.cache_key("здрасти", a)
    assert engine.cache_key("здравей", a) != engine.cache_key("здравей", b)


def test_cache_hit_avoids_second_synthesis(tmp_path, monkeypatch):
    roster = tts.VoiceRoster.load()
    engine = tts.TTSEngine(roster=roster, cache_dir=tmp_path)
    calls = []

    async def fake_remote(text, preset):
        calls.append(text)
        return b"ID3fake-mp3-payload"

    monkeypatch.setattr(engine, "_synthesize_remote", fake_remote)

    first = asyncio.run(engine.synthesize("здравей", roster.default()))
    second = asyncio.run(engine.synthesize("здравей", roster.default()))
    assert first.cached is False
    assert second.cached is True
    assert second.audio == first.audio
    assert len(calls) == 1, "второто извикване трябваше да дойде от кеша"
    assert engine.hits == 1 and engine.misses == 1


def test_empty_text_is_rejected(tmp_path):
    engine = tts.TTSEngine(cache_dir=tmp_path)
    with pytest.raises(tts.TTSError):
        asyncio.run(engine.synthesize("   "))


def test_synthesis_error_message_is_bulgarian(tmp_path, monkeypatch):
    engine = tts.TTSEngine(cache_dir=tmp_path, retries=0)

    async def boom(text, preset):
        raise ConnectionError("websocket closed")

    monkeypatch.setattr(engine, "_synthesize_remote", boom)
    with pytest.raises(ConnectionError):
        asyncio.run(engine.synthesize("здравей"))

    # а през истинския път — четимо българско съобщение
    msg = tts._friendly_error(ConnectionError("websocket closed"), engine.roster.default())
    assert "Microsoft" in msg or "връзка" in msg


def test_cache_prune_respects_limit(tmp_path):
    engine = tts.TTSEngine(cache_dir=tmp_path, cache_max_mb=0)
    engine.cache_max_bytes = 300
    for i in range(10):
        (tmp_path / f"{i:040d}.mp3").write_bytes(b"x" * 100)
    engine.prune_cache()
    total = sum(p.stat().st_size for p in tmp_path.glob("*.mp3"))
    assert total <= 300


def test_clear_cache(tmp_path):
    engine = tts.TTSEngine(cache_dir=tmp_path)
    for i in range(5):
        (tmp_path / f"{i}.mp3").write_bytes(b"x")
    assert engine.clear_cache() == 5
    assert engine.cache_stats()["files"] == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
