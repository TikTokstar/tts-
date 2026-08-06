#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Фалшив TikFinity - за проверка на overlay-а без жив стрийм.

Вдига WebSocket на порт 21213 и праща кадри със същата обвивка като
истинския TikFinity. Играта не различава двете, значи проверява се целият
път: сокет, разчитане, нормализация, познаване.

    python3 tools/fake_tikfinity.py
    python3 tools/fake_tikfinity.py --words роза зора азот --interval 1
    python3 tools/fake_tikfinity.py --interactive

Мнимият адаптер (source: "mock") заобикаля сокета и ражда събития направо.
Този сървър е за когато искаш да провериш и самата връзка.
"""

import argparse
import asyncio
import json
import random
import sys
import time

try:
    from websockets.asyncio.server import serve
except ImportError:
    sys.exit("Липсва websockets. Пусни: pip install websockets")

NAMES = [
    ("ivan_92", "Иван"), ("mariq", "Мария"), ("gosho", "Гошо"),
    ("petya_", "Петя ✨"), ("dani_bg", "Дани"), ("stefan99", "Стефан"),
    ("kalo", "Калоян"), ("vikito", "Виктория"), ("toshko", "Тошко"),
]

NOISE = [
    "здравейте", "яко е", "поздрави", "🔥🔥🔥", "kak si", "браво",
    "не мога да измисля", "хаха", "супер", "поздрав от варна", "❤️",
    "трудно е", "давай", "оооо", "непозната", "ааааа",
]

clients = set()


async def handle(websocket):
    clients.add(websocket)
    print("[фалшив TikFinity] играта се закачи (общо %d)" % len(clients))
    try:
        await websocket.wait_closed()
    finally:
        clients.discard(websocket)
        print("[фалшив TikFinity] играта се откачи (общо %d)" % len(clients))


async def send_chat(handle_name, nickname, text):
    """Обвивката е същата като на истинския TikFinity."""
    frame = json.dumps({
        "event": "chat",
        "data": {
            "comment": text,
            "nickname": nickname,
            "uniqueId": handle_name,
            "userId": str(abs(hash(handle_name)) % 10 ** 10),
            "msgId": str(time.time_ns()),
            "createTime": int(time.time() * 1000),
            "followRole": random.choice([0, 1, 2]),
            "isModerator": False,
        },
    }, ensure_ascii=False)

    for client in list(clients):
        try:
            await client.send(frame)
        except Exception:
            clients.discard(client)


async def noise_loop(words, interval, hit_rate):
    while True:
        await asyncio.sleep(random.uniform(interval * 0.4, interval * 1.6))
        if not clients:
            continue
        handle_name, nickname = random.choice(NAMES)
        if words and random.random() < hit_rate:
            text = random.choice(words)
        else:
            text = random.choice(NOISE)
        print("  %s: %s" % (nickname, text))
        await send_chat(handle_name, nickname, text)


async def interactive_loop():
    """Каквото напишеш в терминала, отива в играта като коментар."""
    loop = asyncio.get_running_loop()
    print("Пиши съобщения (Ctrl+C за изход). Формат: [име:] текст")
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            name, text = line.split(":", 1)
            name, text = name.strip(), text.strip()
        else:
            name, text = "тест", line
        await send_chat(name.lower(), name, text)
        print("  -> пратено на %d играч(и)" % len(clients))


async def run(args):
    async with serve(handle, args.host, args.port):
        print("[фалшив TikFinity] слуша на ws://%s:%d/" % (args.host, args.port))
        if args.interactive:
            await interactive_loop()
        else:
            await noise_loop(args.words, args.interval, args.hit_rate)


def main():
    parser = argparse.ArgumentParser(description="Фалшив TikFinity сървър.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=21213)
    parser.add_argument("--words", nargs="*", default=[],
                        help="думи, които мнимите зрители да познават")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="средно секунди между съобщенията")
    parser.add_argument("--hit-rate", type=float, default=0.4,
                        help="дял на съобщенията, които са истинска догадка")
    parser.add_argument("--interactive", action="store_true",
                        help="пращай каквото напишеш в терминала")
    args = parser.parse_args()

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n[фалшив TikFinity] спрян")


if __name__ == "__main__":
    main()
