#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — сглобява всичко: чат -> модерация -> транслитерация -> глас ->
опашка -> синтез (с кеш) -> изсвирване -> дневник.

Конвейерът е на два етапа нарочно: докато едно съобщение се изсвирва,
следващото вече се синтезира. Така мрежовото време на Microsoft се крие
зад възпроизвеждането и се стига до целта под ~1.5 s.

Нищо тук няма право да събори цикъла — всяко съобщение е в try/except,
логва се и се продължава.

CLI:
    python main.py                       # чете username от config.json
    python main.py @potrebitel           # свързва се веднага
    python main.py --console             # без TikTok, пиши в конзолата
    python main.py --no-panel            # само конзола, без уеб панел
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import audio as audio_mod
import translit
from config import Config, VoiceStore
from moderation import Decision, Moderator, Reason
from tiktok_source import (
    ChatMessage,
    ConsoleSource,
    EventSource,
    SourceState,
    STATE_LABELS,
    TikTokSource,
    normalize_username,
)
from tts import TTSEngine, TTSError, VoicePreset, VoiceRoster

log = logging.getLogger("tts")

BASE_DIR = Path(__file__).resolve().parent


def _safe_attr(obj: Any, name: str, default: str = "") -> str:
    """Чете поле, каквото и да става.

    `getattr(obj, name, default)` хваща само AttributeError — ако полето е
    property, което гърми (счупен proto от TikTok), изключението минава
    нататък. Тук се ползва и в аварийния път, така че НЕ бива да вдига.
    """
    try:
        value = getattr(obj, name, default)
    except Exception:
        return default
    return default if value is None else str(value)


@dataclass
class MessageRecord:
    """Един ред от живия изглед в панела."""

    timestamp: float
    username: str
    nickname: str
    original: str
    spoken: str
    voice: str
    status: str  # "прочетено" | "спряно" | "грешка"
    reason: str = ""
    detail: str = ""
    cached: bool = False
    latency_ms: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["time"] = time.strftime("%H:%M:%S", time.localtime(self.timestamp))
        return data


class TTSBot:
    """Целият бот. Панелът вика само методите оттук."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config if config is not None else Config.load()
        self.store = VoiceStore()
        self.roster = VoiceRoster.load()
        self.moderator = Moderator(self.config)

        self.engine = TTSEngine(
            roster=self.roster,
            cache_max_mb=int(self.config.get("tts.cache_max_mb", 200)),
            enable_cache=bool(self.config.get("tts.cache_enabled", True)),
            timeout=float(self.config.get("tts.timeout", 12.0)),
            retries=int(self.config.get("tts.retries", 1)),
        )
        self.player = audio_mod.AudioPlayer(
            device=self.config.get("audio.device") or None,
            volume=float(self.config.get("audio.volume", 1.0)),
            queue_max=int(self.config.get("audio.queue_max", 15)),
            on_event=self._on_audio_event,
        )

        self.source: Optional[EventSource] = None
        self._inbox: "asyncio.Queue[ChatMessage]" = asyncio.Queue()
        self._worker: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._hotkeys = None

        size = int(self.config.get("panel.history_size", 20))
        self.history: Deque[MessageRecord] = deque(maxlen=max(size, 5))
        self.listeners: List[Any] = []  # панелът си закача тук

        self.voice_report: dict = {}
        self.started_at = time.time()
        self.spoken_count = 0
        self.error_count = 0
        self.last_error: str = ""

    # -----------------------------------------------------------------
    # Живот
    # -----------------------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.player.start()

        # Сверяваме гласовете с Microsoft — не ги вярваме на сляпо.
        self.voice_report = await self.roster.verify()
        if self.voice_report.get("error"):
            log.warning(
                "Гласовете не са сверени (%s). Продължавам с voices.json.",
                self.voice_report["error"],
            )
        else:
            found = ", ".join(self.voice_report.get("found") or []) or "няма"
            log.info("Български гласове у Microsoft: %s", found)
            for bad in self.voice_report.get("invalid") or []:
                log.warning(
                    "Пресет '%s' сочеше липсващ глас '%s' — пренасочен",
                    bad["preset"],
                    bad["voice"],
                )

        self._worker = asyncio.create_task(self._pipeline(), name="tts-pipeline")
        self._start_hotkeys()

        if self.config.get("tiktok.auto_connect") and self.config.get(
            "tiktok.username"
        ):
            await self.connect(str(self.config.get("tiktok.username")))

    async def shutdown(self) -> None:
        await self.disconnect()
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except (asyncio.CancelledError, Exception):
                pass
            self._worker = None
        self._stop_hotkeys()
        self.player.stop()

    # -----------------------------------------------------------------
    # Връзка
    # -----------------------------------------------------------------

    async def connect(self, username: str, console: bool = False) -> dict:
        """Свързва се. Връща речник за панела (успех + съобщение)."""
        await self.disconnect()
        try:
            if console:
                self.source = ConsoleSource(
                    on_message=self._on_chat_message, on_state=self._on_state
                )
                await self.source.start("конзола")
                return {"ok": True, "message": "Конзолен режим."}

            clean = normalize_username(username)
        except ValueError as exc:
            self._notify("state", {"state": "error", "label": "Грешка", "text": str(exc)})
            return {"ok": False, "message": str(exc)}

        self.config.set("tiktok.username", clean)
        self.source = TikTokSource(
            on_message=self._on_chat_message,
            on_state=self._on_state,
            retry_seconds=float(self.config.get("tiktok.retry_seconds", 30)),
        )
        await self.source.start(clean)
        return {"ok": True, "message": f"Свързвам се с @{clean}..."}

    async def disconnect(self) -> None:
        if self.source is not None:
            try:
                await self.source.stop()
            except Exception:
                log.exception("Прекъсването на връзката гръмна")
            self.source = None

    # -----------------------------------------------------------------
    # Вход от чата
    # -----------------------------------------------------------------

    def _on_chat_message(self, message: ChatMessage) -> None:
        """Вика се от цикъла на TikTokLive — трябва да е светкавично."""
        try:
            cap = int(self.config.get("audio.queue_max", 15))
            while self._inbox.qsize() >= cap:
                try:
                    dropped = self._inbox.get_nowait()
                    self._inbox.task_done()
                    self._record(
                        dropped, "", "", "спряно", reason="пълна опашка"
                    )
                except asyncio.QueueEmpty:
                    break
            self._inbox.put_nowait(message)
        except Exception:
            log.exception("Съобщението не влезе в опашката")

    def _on_state(self, state: SourceState, text: str) -> None:
        self._notify(
            "state",
            {
                "state": state.value,
                "label": STATE_LABELS.get(state, ""),
                "text": text,
            },
        )

    def _on_audio_event(self, name: str, payload: dict) -> None:
        self._notify("audio", {"event": name, **payload})

    # -----------------------------------------------------------------
    # Конвейерът
    # -----------------------------------------------------------------

    async def _pipeline(self) -> None:
        while True:
            try:
                message = await self._inbox.get()
            except asyncio.CancelledError:
                raise
            try:
                await self._handle(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Тук е последната мрежа. Едно съобщение не бива да
                # спира четенето на следващите — затова и самото записване
                # в дневника е обвито.
                self.error_count += 1
                self.last_error = str(exc)
                log.exception("Съобщението се провали")
                try:
                    self._record(message, "", "", "грешка", detail=str(exc))
                except Exception:
                    log.exception("Дори записът в дневника се провали")
            finally:
                self._inbox.task_done()

    async def _handle(self, message: ChatMessage) -> None:
        started = time.perf_counter()

        # 1. Команди за глас (!glas) — не се четат като обикновен текст.
        if await self._maybe_handle_command(message):
            return

        # 2. Модерация
        decision: Decision = self.moderator.check(message)
        if not decision.allowed:
            self._record(
                message, "", "", "спряно", reason=decision.reason, detail=decision.detail
            )
            return

        # 3. Нормализация + транслитерация
        opts = translit.TranslitOptions.from_config(self.config.as_dict())
        result = translit.analyze(decision.text, opts)
        spoken = result.text.strip()
        if not spoken:
            self._record(
                message, decision.text, "", "спряно", reason=Reason.NOTHING_TO_SAY
            )
            return

        # 4. Избор на глас (плюс общата скорост от панела)
        preset = self.pick_preset(message.username).with_rate_offset(
            self.config.get("voice.rate_offset", 0)
        )

        # 5. Име на зрителя отпред (по избор)
        if self.config.get("moderation.read_username", False):
            template = str(
                self.config.get("moderation.username_template", "{name} казва")
            )
            name = translit.transliterate(message.display_name, opts) or message.username
            spoken = f"{template.format(name=name)}: {spoken}"

        # 6. Синтез (с кеш) и изсвирване
        try:
            synth = await self.engine.synthesize(spoken, preset)
        except TTSError as exc:
            self.error_count += 1
            self.last_error = str(exc)
            self._record(
                message, decision.text, spoken, "грешка",
                voice=preset.name, detail=str(exc),
            )
            return

        try:
            clip = audio_mod.decode_audio(synth.audio)
        except audio_mod.AudioError as exc:
            self.error_count += 1
            self.last_error = str(exc)
            self._record(
                message, decision.text, spoken, "грешка",
                voice=preset.name, detail=str(exc),
            )
            return

        clip.meta = {"username": message.username, "text": spoken, "voice": preset.name}
        self.player.enqueue(clip)
        self.spoken_count += 1

        self._record(
            message,
            decision.text,
            spoken,
            "прочетено",
            voice=preset.name,
            cached=synth.cached,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    # -----------------------------------------------------------------
    # Гласове
    # -----------------------------------------------------------------

    def pick_preset(self, username: str) -> VoicePreset:
        """Ред на предимство: избор на зрителя -> лепкав хеш -> подразбиране."""
        override = self.config.get("voice.host_override")
        if override:
            preset = self.roster.resolve(str(override))
            if preset:
                return preset

        chosen = self.store.get(username)
        if chosen:
            preset = self.roster.by_id(chosen)
            if preset:
                return preset

        if self.config.get("voice.sticky_per_viewer", True):
            return self.roster.pick_for_user(username)

        preset = self.roster.resolve(str(self.config.get("voice.default_preset") or ""))
        return preset or self.roster.default()

    async def _maybe_handle_command(self, message: ChatMessage) -> bool:
        """`!glas` и `!glas 3`. Връща True, ако съобщението е команда."""
        if not self.config.get("voice.allow_chat_command", True):
            return False
        command = str(self.config.get("voice.command", "!glas") or "!glas").lower()
        text = (message.text or "").strip()
        if not text.lower().startswith(command):
            return False

        argument = text[len(command) :].strip()
        count = len(self.roster.usable)

        if not argument:
            reply = (
                f"{message.display_name}, имаш {count} гласа. "
                f"Напиши {command} и номер от 1 до {count}."
            )
            preset = self.pick_preset(message.username)
        else:
            preset = self.roster.resolve(argument)
            if preset is None:
                reply = (
                    f"{message.display_name}, няма глас '{argument}'. "
                    f"Избери номер от 1 до {count}."
                )
                preset = self.pick_preset(message.username)
            else:
                self.store.set(message.username, preset.id)
                reply = f"{message.display_name}, гласът ти вече е {preset.name}."

        self._record(
            message, text, reply, "команда", voice=preset.name, reason=command
        )
        try:
            synth = await self.engine.synthesize(
                reply, preset.with_rate_offset(self.config.get("voice.rate_offset", 0))
            )
            clip = audio_mod.decode_audio(synth.audio)
            clip.meta = {"username": message.username, "text": reply, "voice": preset.name}
            self.player.enqueue(clip)
        except (TTSError, audio_mod.AudioError) as exc:
            log.warning("Отговорът на командата не се изговори: %s", exc)
        return True

    # -----------------------------------------------------------------
    # Управление (панел + горещи клавиши)
    # -----------------------------------------------------------------

    def skip(self) -> None:
        self.player.skip()
        self._notify("control", {"action": "skip"})

    def clear_queue(self) -> int:
        removed = self.player.clear()
        self._notify("control", {"action": "clear", "removed": removed})
        return removed

    def toggle_mute(self) -> bool:
        muted = self.player.toggle_mute()
        self._notify("control", {"action": "mute", "muted": muted})
        return muted

    def set_mute(self, muted: bool) -> bool:
        self.player.set_mute(muted)
        self._notify("control", {"action": "mute", "muted": self.player.muted})
        return self.player.muted

    def set_volume(self, volume: float) -> float:
        self.player.set_volume(volume)
        self.config.set("audio.volume", self.player.volume)
        return self.player.volume

    def set_device(self, name: Optional[str]) -> str:
        self.player.set_device(name or None)
        self.config.set("audio.device", name or "")
        return audio_mod.device_name(self.player.device_index)

    async def test_voice(self, preset_ref: Optional[str], text: str = "") -> dict:
        preset = self.roster.resolve(preset_ref) if preset_ref else self.roster.default()
        if preset is None:
            return {"ok": False, "message": f"Няма глас '{preset_ref}'."}
        preset = preset.with_rate_offset(self.config.get("voice.rate_offset", 0))
        sample = text.strip() or f"Здравей! Това е гласът {preset.name}."
        try:
            synth = await self.engine.synthesize(sample, preset)
            clip = audio_mod.decode_audio(synth.audio)
        except (TTSError, audio_mod.AudioError) as exc:
            return {"ok": False, "message": str(exc)}
        clip.meta = {"username": "проба", "text": sample, "voice": preset.name}
        self.player.enqueue(clip)
        return {"ok": True, "message": f"Изсвирвам {preset.name}.", "text": sample}

    # -----------------------------------------------------------------
    # Горещи клавиши
    # -----------------------------------------------------------------

    def _start_hotkeys(self) -> None:
        if not self.config.get("hotkeys.enabled", True):
            return
        combos = {
            str(self.config.get("hotkeys.skip", "<ctrl>+<alt>+s")): self._hotkey_skip,
            str(self.config.get("hotkeys.mute", "<ctrl>+<alt>+m")): self._hotkey_mute,
        }
        try:
            from pynput import keyboard

            self._hotkeys = keyboard.GlobalHotKeys(combos)
            self._hotkeys.daemon = True
            self._hotkeys.start()
            log.info("Горещи клавиши: %s", ", ".join(combos))
        except Exception as exc:
            # Няма достъп до клавиатурата (или сме без работен плот) —
            # бутоните в панела продължават да работят.
            self._hotkeys = None
            log.warning("Горещите клавиши не тръгнаха (%s). Ползвай панела.", exc)

    def _stop_hotkeys(self) -> None:
        if self._hotkeys is not None:
            try:
                self._hotkeys.stop()
            except Exception:
                pass
            self._hotkeys = None

    def _hotkey_skip(self) -> None:
        try:
            self.skip()
        except Exception:
            log.exception("Горещият клавиш за пропускане гръмна")

    def _hotkey_mute(self) -> None:
        try:
            muted = self.toggle_mute()
            log.info("Звукът е %s", "изключен" if muted else "включен")
        except Exception:
            log.exception("Горещият клавиш за заглушаване гръмна")

    # -----------------------------------------------------------------
    # Състояние и дневник
    # -----------------------------------------------------------------

    def _record(
        self,
        message: ChatMessage,
        original: str,
        spoken: str,
        status: str,
        voice: str = "",
        reason: str = "",
        detail: str = "",
        cached: bool = False,
        latency_ms: int = 0,
    ) -> None:
        record = MessageRecord(
            timestamp=time.time(),
            username=_safe_attr(message, "username"),
            nickname=_safe_attr(message, "nickname"),
            original=original or _safe_attr(message, "text"),
            spoken=spoken,
            voice=voice,
            status=status,
            reason=reason,
            detail=detail,
            cached=cached,
            latency_ms=latency_ms,
        )
        self.history.append(record)
        self._notify("message", record.to_dict())

        if status == "прочетено":
            mark = "＊" if cached else " "
            log.info(
                "%s @%s: %s -> %s [%s, %d ms]",
                mark, record.username, record.original, record.spoken,
                record.voice, record.latency_ms,
            )
        elif status == "спряно":
            log.debug("- @%s: %s (%s)", record.username, record.original, reason)
        elif status == "грешка":
            log.error("! @%s: %s (%s)", record.username, record.original, detail)

    def _notify(self, kind: str, payload: dict) -> None:
        for listener in list(self.listeners):
            try:
                listener(kind, payload)
            except Exception:
                log.exception("Слушател на събития гръмна")

    def status(self) -> dict:
        source = self.source
        state = source.state if source else SourceState.IDLE
        return {
            "state": state.value,
            "label": STATE_LABELS.get(state, ""),
            "text": source.status_text if source else "Не е свързан.",
            "username": self.config.get("tiktok.username", ""),
            "muted": self.player.muted,
            "volume": round(self.player.volume, 2),
            "device": audio_mod.device_name(self.player.device_index),
            "queue": self.player.queue_size,
            "inbox": self._inbox.qsize(),
            "spoken": self.spoken_count,
            "errors": self.error_count,
            "last_error": self.last_error,
            "dropped_audio": self.player.dropped,
            "uptime": int(time.time() - self.started_at),
            "cache": self.engine.cache_stats(),
            "moderation": {
                "seen": self.moderator.stats.seen,
                "allowed": self.moderator.stats.allowed,
                "dropped": self.moderator.stats.dropped,
                "by_reason": dict(self.moderator.stats.by_reason),
                "blocklist_rules": len(self.moderator.blocklist),
                "blocklist_errors": list(self.moderator.blocklist.errors),
            },
            "voices": {
                "verified": self.roster.verified,
                "found": self.voice_report.get("found") or [],
                "error": self.voice_report.get("error"),
            },
        }

    def history_dicts(self) -> List[dict]:
        return [r.to_dict() for r in reversed(self.history)]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("TikTokLive").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


async def run(args: argparse.Namespace) -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    bot = TTSBot()
    await bot.start()

    panel_task = None
    if not args.no_panel:
        try:
            from panel.app import serve_panel

            panel_task = asyncio.create_task(serve_panel(bot))
        except Exception as exc:
            log.warning("Панелът не тръгна (%s) — продължавам без него.", exc)

    username = args.username or bot.config.get("tiktok.username", "")
    if args.console:
        await bot.connect("", console=True)
        print("Конзолен режим: пиши 'потребител: съобщение' и Enter.")
    elif username and (args.username or bot.config.get("tiktok.auto_connect")):
        result = await bot.connect(username)
        if not result["ok"]:
            print(f"Грешка: {result['message']}")
    else:
        print("Отвори панела и въведи своя @потребител, за да се свържеш.")

    try:
        while True:
            await asyncio.sleep(1.0)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nСпирам...")
    finally:
        if panel_task:
            panel_task.cancel()
        await bot.shutdown()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Български TTS бот за TikTok Live",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("username", nargs="?", help="@потребител или адрес на профила")
    parser.add_argument("--console", action="store_true", help="без TikTok, чете от конзолата")
    parser.add_argument("--no-panel", action="store_true", help="без уеб панел")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробен дневник")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
