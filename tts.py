#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts.py — синтез на реч през edge-tts (безплатните неврални гласове на
Microsoft), гласови пресети и дисков кеш.

Български има само два неврални гласа, затова "гласовете" в панела са
ПРЕСЕТИ: базов глас + скорост + височина + сила, описани във voices.json.

Имената на гласовете НЕ са зашити в кода — при старт се сверяват срещу
`edge_tts.list_voices()`. Ако Microsoft преименува или махне глас, пресетът
се маркира като невалиден и се пренасочва към работещ, вместо да гърми.

CLI:
    python tts.py --list-voices           # какво реално дава Microsoft
    python tts.py --presets               # какво има във voices.json
    python tts.py --say "Здравей!"        # синтез + изсвирване
    python tts.py --say "Здравей!" --preset hamster --device "Voicemeeter"
    python tts.py --say "Здравей!" --out proba.mp3
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_VOICES_FILE = BASE_DIR / "voices.json"
DEFAULT_CACHE_DIR = BASE_DIR / "audio_cache"

#: Гласовете, които очакваме за български. Служат само като резерва —
#: истинският списък се тегли при старт.
FALLBACK_BG_VOICES = ("bg-BG-BorislavNeural", "bg-BG-KalinaNeural")

_SIGNED_PCT = re.compile(r"^[+-]\d{1,3}%$")
_SIGNED_HZ = re.compile(r"^[+-]\d{1,3}Hz$")


class TTSError(RuntimeError):
    """Грешка при синтеза, със съобщение на български."""


# ---------------------------------------------------------------------------
# Пресети
# ---------------------------------------------------------------------------


@dataclass
class VoicePreset:
    id: str
    name: str
    voice: str
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    description: str = ""
    #: Щур глас: стига се с !glas или от панела, но НЕ участва в
    #: случайното раздаване на зрители — иначе половината чат щеше да
    #: звучи като катерички, без никой да го е искал.
    fun: bool = False
    #: Пълва се при сверяване с живия списък на Microsoft.
    available: bool = True

    @classmethod
    def from_dict(cls, raw: dict, index: int) -> "VoicePreset":
        preset = cls(
            id=str(raw.get("id") or f"preset{index}"),
            name=str(raw.get("name") or raw.get("id") or f"Глас {index}"),
            voice=str(raw.get("voice") or FALLBACK_BG_VOICES[0]),
            rate=str(raw.get("rate", "+0%")),
            pitch=str(raw.get("pitch", "+0Hz")),
            volume=str(raw.get("volume", "+0%")),
            description=str(raw.get("description", "")),
            fun=bool(raw.get("fun", False)),
        )
        preset.normalize()
        return preset

    def normalize(self) -> None:
        """edge-tts е капризен за формата — оправяме каквото можем."""
        self.rate = _fix_signed(self.rate, "%", "+0%")
        self.volume = _fix_signed(self.volume, "%", "+0%")
        self.pitch = _fix_signed(self.pitch, "Hz", "+0Hz")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "voice": self.voice,
            "rate": self.rate,
            "pitch": self.pitch,
            "volume": self.volume,
            "description": self.description,
            "fun": self.fun,
            "available": self.available,
        }

    def with_rate_offset(self, offset_percent: int) -> "VoicePreset":
        """Пресетът плюс общата скорост от панела.

        Връща КОПИЕ — плъзгачът не бива да променя самия пресет, иначе
        стойността щеше да се трупа при всяко съобщение.
        """
        offset = int(offset_percent or 0)
        if offset == 0:
            return self
        try:
            base = int(self.rate.rstrip("%"))
        except (ValueError, AttributeError):
            base = 0
        total = max(-90, min(base + offset, 200))
        clone = VoicePreset(
            id=self.id,
            name=self.name,
            voice=self.voice,
            rate=f"{'+' if total >= 0 else ''}{total}%",
            pitch=self.pitch,
            volume=self.volume,
            description=self.description,
            fun=self.fun,
            available=self.available,
        )
        return clone


def _fix_signed(value: str, unit: str, default: str) -> str:
    """'20%' -> '+20%', '-15' -> '-15%', глупости -> подразбиране."""
    value = str(value).strip().replace(" ", "")
    if not value:
        return default
    pattern = _SIGNED_PCT if unit == "%" else _SIGNED_HZ
    if pattern.match(value):
        return value
    m = re.match(r"^([+-]?)(\d{1,3})(?:%|Hz|hz)?$", value)
    if not m:
        log.warning("Неразбираема стойност %r — ползвам %s", value, default)
        return default
    sign = m.group(1) or "+"
    return f"{sign}{m.group(2)}{unit}"


class VoiceRoster:
    """Пресетите от voices.json + сверяване с живия списък на Microsoft."""

    def __init__(self, presets: Sequence[VoicePreset]) -> None:
        self.presets: List[VoicePreset] = list(presets)
        self.available_voices: List[dict] = []
        self.verified = False
        self.verify_error: Optional[str] = None

    # -- зареждане ---------------------------------------------------------

    @classmethod
    def load(cls, path: Path = DEFAULT_VOICES_FILE) -> "VoiceRoster":
        if not path.exists():
            log.warning("Липсва %s — ползвам два вградени пресета", path)
            return cls(cls._builtin_presets())
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.error("voices.json не се чете (%s) — ползвам вградените", exc)
            return cls(cls._builtin_presets())

        items = raw.get("presets") if isinstance(raw, dict) else raw
        presets: List[VoicePreset] = []
        seen: set = set()
        for i, item in enumerate(items or []):
            if not isinstance(item, dict):
                continue
            preset = VoicePreset.from_dict(item, i)
            if preset.id in seen:
                log.warning("Повтарящо се id на пресет %r — пропускам", preset.id)
                continue
            seen.add(preset.id)
            presets.append(preset)
        if not presets:
            log.warning("voices.json е празен — ползвам вградените пресети")
            presets = cls._builtin_presets()
        return cls(presets)

    @staticmethod
    def _builtin_presets() -> List[VoicePreset]:
        return [
            VoicePreset("borislav", "Борислав", FALLBACK_BG_VOICES[0]),
            VoicePreset("kalina", "Калина", FALLBACK_BG_VOICES[1]),
        ]

    # -- достъп ------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.presets)

    @property
    def usable(self) -> List[VoicePreset]:
        out = [p for p in self.presets if p.available]
        return out or self.presets

    def sticky_pool(self, include_fun: bool = False) -> List[VoicePreset]:
        """Пресетите, между които се раздават зрителите.

        Щурите се пропускат по подразбиране — зрител, който не е поискал
        нищо, трябва да получи глас, който се слуша спокойно цял стрийм.
        """
        usable = self.usable
        if include_fun:
            return usable
        normal = [p for p in usable if not p.fun]
        return normal or usable

    def by_id(self, preset_id: Optional[str]) -> Optional[VoicePreset]:
        if not preset_id:
            return None
        for preset in self.presets:
            if preset.id == preset_id:
                return preset
        return None

    def by_number(self, number: int) -> Optional[VoicePreset]:
        """1-базиран номер — така го пишат зрителите в чата (`!glas 3`)."""
        usable = self.usable
        if 1 <= number <= len(usable):
            return usable[number - 1]
        return None

    def resolve(self, ref: Optional[str]) -> Optional[VoicePreset]:
        """Приема id, номер или име."""
        if ref is None:
            return None
        ref = str(ref).strip()
        if not ref:
            return None
        if ref.isdigit():
            return self.by_number(int(ref))
        found = self.by_id(ref)
        if found:
            return found
        low = ref.lower()
        for preset in self.presets:
            if preset.name.lower() == low:
                return preset
        return None

    def pick_for_user(
        self, username: str, include_fun: bool = False
    ) -> VoicePreset:
        """Стабилен хеш -> пресет. Един и същ зрител звучи винаги еднакво."""
        pool = self.sticky_pool(include_fun)
        if not pool:
            raise TTSError("Няма нито един използваем гласов пресет.")
        key = username.strip().lstrip("@").lower()
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        return pool[int.from_bytes(digest[:8], "big") % len(pool)]

    def default(self) -> VoicePreset:
        usable = self.usable
        if not usable:
            raise TTSError("Няма нито един използваем гласов пресет.")
        return usable[0]

    def describe(self) -> List[dict]:
        out = []
        for i, preset in enumerate(self.usable, start=1):
            data = preset.to_dict()
            data["number"] = i
            out.append(data)
        return out

    # -- сверяване с Microsoft --------------------------------------------

    async def verify(self, locale_prefix: str = "bg") -> dict:
        """Тегли живия списък с гласове и маркира пресетите."""
        report: dict = {"ok": False, "found": [], "invalid": [], "error": None}
        try:
            import edge_tts

            voices = await edge_tts.list_voices()
        except Exception as exc:
            self.verify_error = str(exc)
            report["error"] = str(exc)
            log.warning(
                "Списъкът с гласове не можа да се провери (%s). "
                "Продължавам с имената от voices.json.",
                exc,
            )
            # Без интернет не обявяваме пресетите за невалидни — може просто
            # мрежата да е бавна в момента.
            for preset in self.presets:
                preset.available = True
            return report

        self.available_voices = voices
        names = {v.get("ShortName", "") for v in voices}
        bg_names = sorted(
            v.get("ShortName", "")
            for v in voices
            if str(v.get("Locale", "")).lower().startswith(locale_prefix)
        )
        report["found"] = bg_names

        fallback = bg_names[0] if bg_names else (sorted(names)[0] if names else None)
        for preset in self.presets:
            if preset.voice in names:
                preset.available = True
                continue
            report["invalid"].append({"preset": preset.id, "voice": preset.voice})
            log.warning(
                "Гласът %r (пресет %r) вече не съществува у Microsoft.",
                preset.voice,
                preset.id,
            )
            if fallback:
                preset.voice = fallback
                preset.available = True
            else:
                preset.available = False

        self.verified = True
        report["ok"] = True
        return report


# ---------------------------------------------------------------------------
# Синтез
# ---------------------------------------------------------------------------


@dataclass
class SynthesisResult:
    audio: bytes
    preset: VoicePreset
    text: str
    cached: bool = False
    elapsed: float = 0.0


class TTSEngine:
    """Синтез с дисков кеш и повторен опит при мрежов проблем."""

    def __init__(
        self,
        roster: Optional[VoiceRoster] = None,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        cache_max_mb: int = 200,
        enable_cache: bool = True,
        timeout: float = 12.0,
        retries: int = 1,
    ) -> None:
        # Изрично с None: VoiceRoster има __len__, значи празен списък с
        # пресети е "falsy" и `roster or ...` би го подменил мълчаливо.
        self.roster = roster if roster is not None else VoiceRoster.load()
        self.cache_dir = Path(cache_dir)
        self.cache_max_bytes = max(0, int(cache_max_mb)) * 1024 * 1024
        self.enable_cache = enable_cache
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.hits = 0
        self.misses = 0
        if self.enable_cache:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                log.warning("Кеш папката не може да се създаде (%s)", exc)
                self.enable_cache = False

    # -- кеш ---------------------------------------------------------------

    def cache_key(self, text: str, preset: VoicePreset) -> str:
        payload = "\x1f".join(
            [text, preset.voice, preset.rate, preset.pitch, preset.volume]
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.mp3"

    def prune_cache(self) -> int:
        """Изхвърля най-старите файлове, ако кешът е прекалено голям."""
        if not self.enable_cache or self.cache_max_bytes <= 0:
            return 0
        try:
            files = sorted(
                (p for p in self.cache_dir.glob("*.mp3") if p.is_file()),
                key=lambda p: p.stat().st_mtime,
            )
        except Exception:
            return 0
        total = sum(p.stat().st_size for p in files)
        removed = 0
        for path in files:
            if total <= self.cache_max_bytes:
                break
            try:
                size = path.stat().st_size
                path.unlink()
                total -= size
                removed += 1
            except Exception:
                continue
        return removed

    def clear_cache(self) -> int:
        removed = 0
        if not self.cache_dir.exists():
            return 0
        for path in self.cache_dir.glob("*.mp3"):
            try:
                path.unlink()
                removed += 1
            except Exception:
                continue
        return removed

    def cache_stats(self) -> dict:
        files = list(self.cache_dir.glob("*.mp3")) if self.cache_dir.exists() else []
        size = sum(p.stat().st_size for p in files if p.is_file())
        return {
            "files": len(files),
            "mb": round(size / 1024 / 1024, 2),
            "hits": self.hits,
            "misses": self.misses,
        }

    # -- синтез ------------------------------------------------------------

    async def synthesize(
        self, text: str, preset: Optional[VoicePreset] = None
    ) -> SynthesisResult:
        """Текст -> mp3 байтове. Вдига TTSError с четимо съобщение."""
        text = (text or "").strip()
        if not text:
            raise TTSError("Няма текст за изговаряне.")
        preset = preset or self.roster.default()
        started = time.perf_counter()

        key = self.cache_key(text, preset)
        path = self._cache_path(key)
        if self.enable_cache and path.exists():
            try:
                audio = path.read_bytes()
                if audio:
                    self.hits += 1
                    path.touch()  # за подрязването по време на достъп
                    return SynthesisResult(
                        audio=audio,
                        preset=preset,
                        text=text,
                        cached=True,
                        elapsed=time.perf_counter() - started,
                    )
            except Exception as exc:
                log.debug("Кешираният файл не се чете (%s)", exc)

        self.misses += 1
        audio = await self._synthesize_remote(text, preset)

        if self.enable_cache:
            try:
                tmp = path.with_suffix(".part")
                tmp.write_bytes(audio)
                tmp.replace(path)
                self.prune_cache()
            except Exception as exc:
                log.debug("Кешът не може да се запише (%s)", exc)

        return SynthesisResult(
            audio=audio,
            preset=preset,
            text=text,
            cached=False,
            elapsed=time.perf_counter() - started,
        )

    async def _synthesize_remote(self, text: str, preset: VoicePreset) -> bytes:
        import edge_tts
        from edge_tts import exceptions as tts_exc

        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                communicate = edge_tts.Communicate(
                    text,
                    voice=preset.voice,
                    rate=preset.rate,
                    pitch=preset.pitch,
                    volume=preset.volume,
                )
                chunks: List[bytes] = []

                async def pump() -> None:
                    async for chunk in communicate.stream():
                        if chunk.get("type") == "audio" and chunk.get("data"):
                            chunks.append(chunk["data"])

                await asyncio.wait_for(pump(), timeout=self.timeout)
                audio = b"".join(chunks)
                if not audio:
                    raise tts_exc.NoAudioReceived("празен отговор")
                return audio

            except asyncio.TimeoutError as exc:
                last_error = exc
                log.warning("Синтезът надхвърли %.0f s (опит %d)", self.timeout, attempt + 1)
            except tts_exc.NoAudioReceived as exc:
                last_error = exc
                log.warning("Microsoft не върна звук (опит %d)", attempt + 1)
            except Exception as exc:
                last_error = exc
                log.warning("Синтезът се провали (опит %d): %s", attempt + 1, exc)
            if attempt < self.retries:
                await asyncio.sleep(0.4 * (attempt + 1))

        raise TTSError(_friendly_error(last_error, preset)) from last_error


def _friendly_error(exc: Optional[Exception], preset: VoicePreset) -> str:
    text = str(exc or "").lower()
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in text:
        return "Синтезът се забави твърде много. Провери интернет връзката."
    if "no audio" in text or "noaudioreceived" in text:
        return (
            f"Microsoft не върна звук за глас '{preset.voice}'. "
            "Възможно е текстът да е само пунктуация или гласът да е недостъпен."
        )
    if any(k in text for k in ("websocket", "connection", "getaddrinfo", "ssl", "proxy")):
        return "Няма връзка със сървъра на Microsoft. Провери интернет/защитна стена."
    if "403" in text or "401" in text:
        return "Microsoft отказа заявката (403). Опитай пак след малко."
    return f"Синтезът се провали: {exc}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def _cli_list_voices(prefix: str = "bg") -> int:
    try:
        import edge_tts

        voices = await edge_tts.list_voices()
    except Exception as exc:
        print(f"Списъкът с гласове не можа да се изтегли: {exc}")
        return 1
    matching = [v for v in voices if str(v.get("Locale", "")).lower().startswith(prefix)]
    print(f"Общо гласове у Microsoft: {len(voices)}")
    print(f"Гласове за '{prefix}': {len(matching)}")
    for v in matching:
        print(f"  {v.get('ShortName'):<28} {v.get('Gender'):<8} {v.get('Locale')}")
    return 0 if matching else 1


async def _cli_say(
    text: str,
    preset_ref: Optional[str],
    device: Optional[str],
    out_file: Optional[str],
) -> int:
    import audio as audio_mod

    roster = VoiceRoster.load()
    report = await roster.verify()
    if report["error"]:
        print(f"(Проверката на гласовете не мина: {report['error']})")
    else:
        print(f"Налични български гласове: {', '.join(report['found']) or 'няма'}")
        for bad in report["invalid"]:
            print(f"  ! пресет {bad['preset']} сочеше към липсващ глас {bad['voice']}")

    preset = roster.resolve(preset_ref) if preset_ref else roster.default()
    if preset is None:
        print(f"Няма такъв пресет: {preset_ref}")
        return 1

    engine = TTSEngine(roster=roster)
    started = time.perf_counter()
    try:
        result = await engine.synthesize(text, preset)
    except TTSError as exc:
        print(f"Грешка: {exc}")
        return 1
    synth_ms = (time.perf_counter() - started) * 1000
    print(
        f"Пресет: {preset.name} ({preset.voice}, rate={preset.rate}, "
        f"pitch={preset.pitch}, volume={preset.volume})"
    )
    print(
        f"Синтез: {len(result.audio)} байта за {synth_ms:.0f} ms"
        f"{' (от кеша)' if result.cached else ''}"
    )

    if out_file:
        Path(out_file).write_bytes(result.audio)
        print(f"Записах: {out_file}")
        return 0

    try:
        clip = audio_mod.decode_audio(result.audio)
    except audio_mod.AudioError as exc:
        print(f"Грешка при декодиране: {exc}")
        return 1
    print(f"Декодиран: {clip.duration:.2f} s, {clip.samplerate} Hz, {clip.channels} кан.")

    player = audio_mod.AudioPlayer(device=device)
    player.start()
    print(f"Изсвирвам на: {audio_mod.device_name(player.device_index)}")
    player.enqueue(clip)
    deadline = time.time() + clip.duration + 3.0
    while time.time() < deadline and (player.queue_size or player.current):
        await asyncio.sleep(0.05)
    player.stop()
    if player.last_error:
        print(f"Грешка при изсвирване: {player.last_error}")
        return 1
    print("Готово.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    def opt(name: str) -> Optional[str]:
        if name in argv:
            i = argv.index(name)
            if i + 1 < len(argv):
                return argv[i + 1]
        return None

    if "--list-voices" in argv:
        return asyncio.run(_cli_list_voices(opt("--locale") or "bg"))

    if "--presets" in argv:
        roster = VoiceRoster.load()
        print(f"{'№':>3}  {'id':<12} {'име':<12} {'глас':<24} {'rate':>6} {'pitch':>7}")
        print("-" * 76)
        for item in roster.describe():
            print(
                f"{item['number']:>3}  {item['id']:<12} {item['name']:<12} "
                f"{item['voice']:<24} {item['rate']:>6} {item['pitch']:>7}"
            )
        return 0

    text = opt("--say")
    if text:
        return asyncio.run(
            _cli_say(text, opt("--preset"), opt("--device"), opt("--out"))
        )

    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
