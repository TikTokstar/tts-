#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel/app.py — контролният панел на http://localhost:8777

Само тънък слой над TTSBot: всяка ръчка вика метод на бота, нищо не се
дублира тук. Живите обновявания вървят по WebSocket.

Важно за нишките: част от събитията (звуковите) идват от нишката на
плейъра, не от цикъла на asyncio. Затова слушателят подава през
`call_soon_threadsafe` — иначе WebSocket-ите щяха да се пишат от грешна
нишка и да се чупят по трудни за хващане начини.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import audio as audio_mod

log = logging.getLogger("panel")

PANEL_DIR = Path(__file__).resolve().parent
STATIC_DIR = PANEL_DIR / "static"


class EventHub:
    """Разпраща събитията на бота към всички отворени панели."""

    def __init__(self) -> None:
        self.sockets: Set[WebSocket] = set()
        self.queue: "asyncio.Queue[dict]" = asyncio.Queue(maxsize=500)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._task: Optional[asyncio.Task] = None

    def attach(self, bot) -> None:
        self.loop = asyncio.get_running_loop()
        bot.listeners.append(self._on_event)
        self._task = asyncio.create_task(self._broadcaster(), name="panel-broadcast")

    def detach(self, bot) -> None:
        try:
            bot.listeners.remove(self._on_event)
        except ValueError:
            pass
        if self._task:
            self._task.cancel()
            self._task = None

    def _on_event(self, kind: str, payload: dict) -> None:
        """Вика се от РАЗЛИЧНИ нишки — оттук нататък всичко е в цикъла."""
        if self.loop is None:
            return
        event = {"kind": kind, **payload}
        try:
            self.loop.call_soon_threadsafe(self._enqueue, event)
        except RuntimeError:
            pass  # цикълът се затваря — няма кой да слуша

    def _enqueue(self, event: dict) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            # Панелът е само за гледане — по-добре да изпуснем събитие,
            # отколкото да бавим бота.
            pass

    async def _broadcaster(self) -> None:
        while True:
            event = await self.queue.get()
            for socket in list(self.sockets):
                try:
                    await socket.send_json(event)
                except Exception:
                    self.sockets.discard(socket)


def build_app(bot) -> FastAPI:
    hub = EventHub()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        hub.attach(bot)
        try:
            yield
        finally:
            hub.detach(bot)

    app = FastAPI(
        title="Български TTS за TikTok Live",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # -- страницата --------------------------------------------------------

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # -- състояние ---------------------------------------------------------

    @app.get("/api/status")
    async def status() -> dict:
        return bot.status()

    @app.get("/api/history")
    async def history() -> List[dict]:
        return bot.history_dicts()

    @app.get("/api/bootstrap")
    async def bootstrap() -> dict:
        """Всичко, което страницата иска при зареждане, с една заявка."""
        return {
            "status": bot.status(),
            "history": bot.history_dicts(),
            "voices": bot.roster.describe(),
            "devices": [
                {
                    "index": d.index,
                    "name": d.name,
                    "label": d.label,
                    "default": d.is_default,
                }
                for d in audio_mod.list_output_devices()
            ],
            "config": bot.config.as_dict(),
        }

    # -- връзка ------------------------------------------------------------

    @app.post("/api/connect")
    async def connect(payload: Dict[str, Any]) -> dict:
        username = str(payload.get("username", "") or "").strip()
        if not username:
            return {"ok": False, "message": "Въведи своя @потребител."}
        return await bot.connect(username)

    @app.post("/api/disconnect")
    async def disconnect() -> dict:
        await bot.disconnect()
        return {"ok": True, "message": "Връзката е прекъсната."}

    # -- звук --------------------------------------------------------------

    @app.get("/api/devices")
    async def devices() -> List[dict]:
        return [
            {"index": d.index, "name": d.name, "label": d.label, "default": d.is_default}
            for d in audio_mod.list_output_devices()
        ]

    @app.post("/api/device")
    async def set_device(payload: Dict[str, Any]) -> dict:
        name = payload.get("name") or ""
        actual = bot.set_device(name)
        return {"ok": True, "message": f"Изход: {actual}", "device": actual}

    @app.post("/api/volume")
    async def set_volume(payload: Dict[str, Any]) -> dict:
        try:
            volume = float(payload.get("volume", 1.0))
        except (TypeError, ValueError):
            return {"ok": False, "message": "Невалидна сила на звука."}
        return {"ok": True, "volume": bot.set_volume(volume)}

    @app.post("/api/speed")
    async def set_speed(payload: Dict[str, Any]) -> dict:
        try:
            offset = int(payload.get("offset", 0))
        except (TypeError, ValueError):
            return {"ok": False, "message": "Невалидна скорост."}
        offset = max(-50, min(offset, 100))
        bot.config.set("voice.rate_offset", offset)
        return {"ok": True, "offset": offset}

    # -- гласове -----------------------------------------------------------

    @app.get("/api/voices")
    async def voices() -> List[dict]:
        return bot.roster.describe()

    @app.post("/api/voice/test")
    async def test_voice(payload: Dict[str, Any]) -> dict:
        return await bot.test_voice(
            payload.get("preset"), str(payload.get("text", "") or "")
        )

    @app.post("/api/voice/override")
    async def voice_override(payload: Dict[str, Any]) -> dict:
        preset = payload.get("preset") or None
        if preset:
            found = bot.roster.resolve(str(preset))
            if not found:
                return {"ok": False, "message": f"Няма глас '{preset}'."}
            bot.config.set("voice.host_override", found.id)
            return {"ok": True, "message": f"Всички ще звучат като {found.name}."}
        bot.config.set("voice.host_override", None)
        return {"ok": True, "message": "Всеки зрител си има свой глас."}

    @app.post("/api/voice/forget")
    async def forget_voices(payload: Dict[str, Any]) -> dict:
        username = payload.get("username")
        bot.store.clear(username)
        if username:
            return {"ok": True, "message": f"Изчистих гласа на @{username}."}
        return {"ok": True, "message": "Изчистих запомнените гласове."}

    # -- управление --------------------------------------------------------

    @app.post("/api/control/skip")
    async def skip() -> dict:
        bot.skip()
        return {"ok": True, "message": "Пропуснато."}

    @app.post("/api/control/clear")
    async def clear() -> dict:
        removed = bot.clear_queue()
        return {"ok": True, "message": f"Изчистих {removed} от опашката."}

    @app.post("/api/control/mute")
    async def mute(payload: Dict[str, Any]) -> dict:
        if "muted" in payload:
            muted = bot.set_mute(bool(payload["muted"]))
        else:
            muted = bot.toggle_mute()
        return {
            "ok": True,
            "muted": muted,
            "message": "Звукът е изключен." if muted else "Звукът е включен.",
        }

    # -- настройки ---------------------------------------------------------

    @app.get("/api/config")
    async def get_config() -> dict:
        return bot.config.as_dict()

    @app.post("/api/config")
    async def set_config(payload: Dict[str, Any]) -> dict:
        """Приема {"moderation.max_length": 150, ...} — важи веднага."""
        if not isinstance(payload, dict) or not payload:
            return {"ok": False, "message": "Няма какво да променя."}
        applied = {}
        for dotted, value in payload.items():
            if not isinstance(dotted, str) or "." not in dotted:
                continue
            bot.config.set(dotted, value, save=False)
            applied[dotted] = value
        bot.config.save()

        # Няколко настройки трябва да стигнат и до живите обекти.
        if "audio.volume" in applied:
            bot.player.set_volume(float(applied["audio.volume"]))
        if "audio.device" in applied:
            bot.player.set_device(applied["audio.device"] or None)
        return {"ok": True, "applied": applied, "config": bot.config.as_dict()}

    @app.post("/api/cache/clear")
    async def clear_cache() -> dict:
        removed = bot.engine.clear_cache()
        return {"ok": True, "message": f"Изтрих {removed} файла от кеша."}

    # -- живи обновявания --------------------------------------------------

    @app.websocket("/ws")
    async def websocket_endpoint(socket: WebSocket) -> None:
        await socket.accept()
        hub.sockets.add(socket)
        try:
            await socket.send_json({"kind": "hello", "status": bot.status()})
            while True:
                await socket.receive_text()  # държи връзката отворена
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            hub.sockets.discard(socket)

    return app


async def serve_panel(bot) -> None:
    """Пуска uvicorn вътре в текущия цикъл, за да живее заедно с бота."""
    import uvicorn

    host = str(bot.config.get("panel.host", "127.0.0.1"))
    port = int(bot.config.get("panel.port", 8777))
    app = build_app(bot)

    config = uvicorn.Config(
        app, host=host, port=port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)

    shown = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}"
    print(f"\n  Контролен панел: {shown}\n")

    if bot.config.get("panel.open_browser", True):
        try:
            import webbrowser

            webbrowser.open(shown)
        except Exception:
            pass

    try:
        await server.serve()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.error("Панелът спря: %s", exc)
