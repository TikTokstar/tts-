#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Мост между TikTokLive и играта - резервният източник за чата.

Основният е TikFinity: върви си сам и не иска нищо от нас. Този мост е за
случая, в който TikFinity не работи или не искаш да зависиш от него.

    pip install -r bridge/requirements.txt
    python3 bridge/tiktok_bridge.py @потребителското_име

После в конфигурацията на играта:  source: "tiktoklive"

Мостът чете коментарите през библиотеката TikTokLive и ги препредава по
локален WebSocket на порт 21214 в един-единствен формат:

    {"event": "chat", "data": {
        "user": "Име", "userId": "123", "message": "текст",
        "id": "msg_id", "timestamp": 1699999999999
    }}

Внимание: TikTokLive подписва заявките си през външна услуга (Euler Stream)
с лимити на безплатния слой, и се чупи всеки път, когато TikTok смени нещо
в протокола си. Затова е резервният, а не основният вариант.
"""

import argparse
import asyncio
import json
import sys
import time


# Тежките зависимости се внасят чак когато мостът тръгне, а не при внасяне
# на модула - така extract_comment може да се провери от тестовете, без
# TikTokLive да е инсталиран.
def _load_deps():
    try:
        from websockets.asyncio.server import serve
    except ImportError:
        sys.exit("Липсва websockets. Пусни: pip install -r bridge/requirements.txt")

    try:
        from TikTokLive import TikTokLiveClient
        from TikTokLive.events import CommentEvent, ConnectEvent, DisconnectEvent
    except ImportError:
        sys.exit("Липсва TikTokLive. Пусни: pip install -r bridge/requirements.txt")

    return serve, TikTokLiveClient, CommentEvent, ConnectEvent, DisconnectEvent


class Bridge:
    """Държи отворените браузъри и им праща каквото дойде от TikTok."""

    def __init__(self, verbose=False):
        self.clients = set()
        self.verbose = verbose
        self.sent = 0

    async def handle_client(self, websocket):
        self.clients.add(websocket)
        print("[мост] браузър се закачи (общо %d)" % len(self.clients))
        try:
            # Не чакаме нищо от играта - само държим връзката отворена.
            await websocket.wait_closed()
        finally:
            self.clients.discard(websocket)
            print("[мост] браузър се откачи (общо %d)" % len(self.clients))

    async def broadcast(self, payload):
        if not self.clients:
            return
        message = json.dumps(payload, ensure_ascii=False)
        dead = []
        for client in list(self.clients):
            try:
                await client.send(message)
            except Exception:
                dead.append(client)
        for client in dead:
            self.clients.discard(client)


def extract_comment(event):
    """
    Вади каквото ни трябва от събитието.

    Всичко минава през getattr с резервен вариант: протоколът на TikTok се
    мести, а мостът не бива да пада заради преименувано поле.
    """
    user = getattr(event, "user", None)
    nickname = getattr(user, "nickname", "") or ""
    handle = getattr(user, "display_id", "") or ""
    user_id = getattr(user, "id", "") or handle or nickname

    common = getattr(event, "common", None)
    msg_id = str(getattr(common, "msg_id", "") or "")

    return {
        "user": nickname or handle or str(user_id),
        "userId": str(user_id),
        "message": getattr(event, "comment", "") or "",
        "id": msg_id,
        "timestamp": int(time.time() * 1000),
    }


async def run(username, host, port, verbose):
    serve, TikTokLiveClient, CommentEvent, ConnectEvent, DisconnectEvent = _load_deps()

    bridge = Bridge(verbose=verbose)
    client = TikTokLiveClient(unique_id=username)

    @client.on(ConnectEvent)
    async def on_connect(event):
        print("[мост] закачен за стрийма на %s" % username)

    @client.on(DisconnectEvent)
    async def on_disconnect(event):
        print("[мост] стриймът прекъсна")

    @client.on(CommentEvent)
    async def on_comment(event):
        data = extract_comment(event)
        if not data["message"]:
            return
        bridge.sent += 1
        if verbose:
            print("[чат] %s: %s" % (data["user"], data["message"]))
        await bridge.broadcast({"event": "chat", "data": data})

    async with serve(bridge.handle_client, host, port):
        print("[мост] WebSocket слуша на ws://%s:%d/" % (host, port))
        print("[мост] чакам стрийма на %s ..." % username)

        # Стриймът може да не е започнал още, а TikTok къса връзки. И в
        # двата случая просто пробваме пак - стриймът върви с часове.
        delay = 5
        while True:
            try:
                await client.connect()
                print("[мост] връзката се затвори, пробвам пак след %ds" % delay)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print("[мост] %s: %s" % (type(exc).__name__, exc))
                print("[мост] нов опит след %ds" % delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


def clean_username(parts):
    """Сглобява името от каквото е дошло по командния ред.

    Ако в името се промъкне интервал (много лесно става при копиране),
    обвивката го разцепва на два аргумента. Името в TikTok не може да
    съдържа интервали, затова просто ги махаме, вместо да се отказваме с
    неразбираемо съобщение.
    """
    name = "".join("".join(parts).split())
    return name.lstrip("@")


def main():
    parser = argparse.ArgumentParser(description="TikTokLive мост към играта Думички.")
    parser.add_argument("username", nargs="+",
                        help="потребителското име в TikTok, напр. @someone")
    parser.add_argument("--host", default="127.0.0.1", help="по подразбиране 127.0.0.1")
    parser.add_argument("--port", type=int, default=21214, help="по подразбиране 21214")
    parser.add_argument("--verbose", action="store_true", help="печата всеки коментар")
    args = parser.parse_args()

    name = clean_username(args.username)
    if not name:
        sys.exit("Празно потребителско име. Пусни: python bridge/tiktok_bridge.py @името_ти")

    username = "@" + name

    try:
        asyncio.run(run(username, args.host, args.port, args.verbose))
    except KeyboardInterrupt:
        print("\n[мост] спрян")


if __name__ == "__main__":
    main()
