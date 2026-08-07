#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест на връзката с чата - от край до край.

Вдига фалшив TikFinity, пуска истински Chromium, зарежда overlay-а през
file:// (точно както прави OBS) и проверява какво стига до играта.

Проверява това, което не се вижда от кода:
  - зарежда ли се страницата през file:// без CORS проблем
  - разчита ли адаптерът схемата на TikFinity
  - минават ли коментарите през нормализацията и познаването
  - вдига ли се връзката пак, ако сървърът падне

    pip install websockets playwright
    python3 tools/test_chat.py
"""

import asyncio
import json
import os
import sys
import time

from websockets.asyncio.server import serve

try:
    from playwright.async_api import async_playwright
except ImportError:
    sys.exit("Липсва playwright. Пусни: pip install playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = "file://" + os.path.join(ROOT, "game", "chat-test.html")
PORT = 21299

# Ако средата има готов Chromium, ползваме него вместо да теглим нов.
CHROMIUM_CANDIDATES = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium/chrome-linux/chrome",
]


def find_chromium():
    for path in CHROMIUM_CANDIDATES:
        if os.path.exists(path):
            return path
    return None  # Playwright ще си намери своя

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  ✓ %s" % name)
    else:
        failed += 1
        print("  ✗ %s%s" % (name, "  -> " + str(detail) if detail else ""))


class FakeTikFinity:
    """Праща кадри с обвивката на истинския TikFinity."""

    def __init__(self):
        self.clients = set()
        self.server = None

    async def handle(self, websocket):
        self.clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.clients.discard(websocket)

    async def start(self):
        self.server = await serve(self.handle, "127.0.0.1", PORT)

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()
        for client in list(self.clients):
            await client.close()
        self.clients.clear()

    async def send(self, nickname, text, msg_id=None):
        frame = json.dumps({
            "event": "chat",
            "data": {
                "comment": text,
                "nickname": nickname,
                "uniqueId": nickname.lower(),
                "userId": "42",
                "msgId": msg_id or str(time.time_ns()),
                "createTime": int(time.time() * 1000),
            },
        }, ensure_ascii=False)
        for client in list(self.clients):
            await client.send(frame)

    async def send_raw(self, payload):
        frame = json.dumps(payload, ensure_ascii=False)
        for client in list(self.clients):
            await client.send(frame)

    async def wait_for_client(self, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.clients:
                return True
            await asyncio.sleep(0.05)
        return False


async def wait_until(page, expression, timeout=8):
    """Чака JS израз да върне истина. Връща False при изтекло време."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if await page.evaluate(expression):
            return True
        await asyncio.sleep(0.08)
    return False


async def main():
    fake = FakeTikFinity()
    await fake.start()
    print("Фалшив TikFinity на порт %d\n" % PORT)

    async with async_playwright() as pw:
        launch_options = {}
        chromium = find_chromium()
        if chromium:
            launch_options["executable_path"] = chromium
        browser = await pw.chromium.launch(**launch_options)
        page = await browser.new_page()

        console_lines = []
        page.on("console", lambda msg: console_lines.append(msg.text))
        page.on("pageerror", lambda err: console_lines.append("PAGEERROR: " + str(err)))

        url = PAGE + "?source=tikfinity&port=%d" % PORT
        await page.goto(url)

        # Само записваме какво минава. Познаването го върши самата страница,
        # иначе тестът щеше да проверява себе си вместо нея.
        await page.evaluate("""
          window.messages = [];
          window.chat.on("message", function (e) { window.messages.push(e); });
        """)

        print("Зареждане и свързване")
        print("-" * 21)

        errors = [line for line in console_lines if line.startswith("PAGEERROR")]
        check("страницата се зарежда без грешки", not errors, errors[:2])
        check("речникът е зареден през file://",
              await page.evaluate("DUMICHKI_DATA.words.length") == 113721)
        check("играта се закачи за сокета", await fake.wait_for_client())

        connected = await wait_until(page, "window.chat.stats.connects > 0")
        check("състоянието е 'свързан'", connected)

        # --- Разчитане на схемата -------------------------------------------

        print("\nРазчитане на схемата на TikFinity")
        print("-" * 33)

        await fake.send("Иван", "здравейте")
        got = await wait_until(page, "window.messages.length >= 1")
        check("коментарът стига до играта", got)

        if got:
            msg = await page.evaluate("window.messages[0]")
            check("името е разчетено", msg["user"] == "Иван", msg.get("user"))
            check("текстът е разчетен", msg["message"] == "здравейте", msg.get("message"))
            check("userId е разчетен", msg["userId"] == "42", msg.get("userId"))

        # Подаръци и лайкове минават по същия сокет - не бива да ги броим.
        await fake.send_raw({"event": "gift", "data": {"giftName": "роза", "nickname": "Гошо"}})
        await fake.send_raw({"event": "like", "data": {"likeCount": 15, "nickname": "Петя"}})
        await asyncio.sleep(0.4)
        count = await page.evaluate("window.messages.length")
        check("подаръци и лайкове се пропускат", count == 1, "%d съобщения" % count)

        # Дубликат със същия msgId - не бива да се брои два пъти.
        await fake.send("Мария", "тест", msg_id="повторка")
        await asyncio.sleep(0.3)
        await fake.send("Мария", "тест", msg_id="повторка")
        await asyncio.sleep(0.4)
        dups = await page.evaluate("window.chat.stats.duplicates")
        check("повторените съобщения се отсяват", dups == 1, "%d отсети" % dups)

        # --- Познаване -------------------------------------------------------

        print("\nПознаване през целия път")
        print("-" * 24)

        targets = await page.evaluate("window.round.targets")
        cyrillic = targets[0]
        latin = await page.evaluate("Dumichki.Shlyokavitsa.expand('%s')[0]" % targets[1])

        await fake.send("Гошо", cyrillic.upper() + "!!")
        await fake.send("Петя", latin)
        await fake.send("Тошко", "🔥🔥🔥")
        await fake.send("Дани", "някаква глупост")

        await wait_until(page, "window.round.found.size >= 2")
        found = await page.evaluate("Array.from(window.round.found.entries())")
        words = [entry[0] for entry in found]
        check("догадка на кирилица се хваща (%s)" % cyrillic.upper(),
              cyrillic in words, found)
        check("догадка на шльокавица се хваща (%s → %s)" % (latin, targets[1]),
              targets[1] in words, found)
        check("грешните догадки се пропускат тихо", len(found) == 2, found)
        check("познатата дума носи името на позналия",
              dict(found).get(cyrillic) == "Гошо", found)

        # --- Възстановяване на връзката --------------------------------------

        print("\nВъзстановяване след прекъсване")
        print("-" * 30)

        before = await page.evaluate("window.chat.stats.connects")
        await fake.stop()
        await asyncio.sleep(0.5)
        state = await page.evaluate("window.chat.socket === null")
        check("падането на сървъра се забелязва", state)

        await fake.start()
        back = await wait_until(page, "window.chat.stats.connects > %d" % before, timeout=12)
        check("връзката се вдига сама", back)

        if back:
            await fake.wait_for_client()
            await fake.send("Стефан", "пак съм тук")
            again = await wait_until(page, """
              window.messages.some(function (m) { return m.message === "пак съм тук"; })
            """)
            check("съобщенията текат пак след прекъсване", again)

        # --- Конзолата --------------------------------------------------------

        print("\nКоментарите в конзолата")
        print("-" * 23)
        comments = [line for line in console_lines if line.startswith("[коментар]")]
        check("коментарите се печатат в конзолата", len(comments) >= 3,
              "%d реда" % len(comments))
        if comments:
            print("     напр.  " + comments[0])

        # --- Смяна на източника ------------------------------------------------

        print("\nСмяна на източника")
        print("-" * 18)

        # Смяната на source трябва да стига - всеки адаптер си знае порта.
        # Ако конфигурацията закове порт, смяната мълчаливо търси моста на
        # порта на TikFinity и нищо не работи.
        ports = await page.evaluate("""
          ["tikfinity", "tiktoklive"].map(function (name) {
            var cfg = { source: name, host: "localhost", port: null };
            return name + "=" + Dumichki.Chat.create(cfg).adapter.url(cfg);
          })
        """)
        check("TikFinity отива на 21213", "21213" in ports[0], ports[0])
        check("мостът отива на 21214", "21214" in ports[1], ports[1])

        override = await page.evaluate("""
          (function () {
            var cfg = { source: "tiktoklive", host: "1.2.3.4", port: 9999 };
            return Dumichki.Chat.create(cfg).adapter.url(cfg);
          })()
        """)
        check("изричен порт и хост имат предимство",
              override == "ws://1.2.3.4:9999/", override)

        # --- Мостът и играта говорят ли на един език ---------------------------

        print("\nМостът към играта")
        print("-" * 17)

        # Кадърът се строи от СЪЩИЯ код, който ползва мостът - иначе двете
        # страни може тихо да се разминат при промяна в едната.
        sys.path.insert(0, os.path.join(ROOT, "bridge"))
        from tiktok_bridge import extract_comment

        class FakeUser:
            nickname = "Гошо"
            display_id = "gosho_bg"
            id = 12345

        class FakeCommon:
            msg_id = 777

        class FakeEvent:
            user = FakeUser()
            common = FakeCommon()
            comment = "сърце"

        payload = extract_comment(FakeEvent())
        check("мостът вади името", payload["user"] == "Гошо", payload)
        check("мостът вади текста", payload["message"] == "сърце", payload)
        check("мостът вади идентификатор", payload["userId"] == "12345", payload)

        bridge_page = await browser.new_page()
        bridge_url = "file://" + os.path.join(ROOT, "game", "chat-test.html")
        await bridge_page.goto(bridge_url + "?source=tiktoklive&port=%d" % PORT)
        await fake.wait_for_client()
        await bridge_page.evaluate("""
          window.got = [];
          window.chat.on("message", function (e) { window.got.push(e); });
        """)

        await fake.send_raw({"event": "chat", "data": payload})
        arrived = await wait_until(bridge_page, "window.got.length >= 1")
        check("кадърът на моста стига до играта", arrived)

        if arrived:
            got = await bridge_page.evaluate("window.got[0]")
            check("името оцелява по пътя", got["user"] == "Гошо", got)
            check("текстът оцелява по пътя", got["message"] == "сърце", got)

        await bridge_page.close()

        # --- Бележката за състоянието -----------------------------------------

        print("\nБележката за състоянието на чата")
        print("-" * 32)

        # config.js е с tikfinity по подразбиране. Ако програмата не върви,
        # играта изглежда жива, но мъртва - трябва да казва защо.
        game_page = await browser.new_page(viewport={"width": 1080, "height": 1920})
        game_url = "file://" + os.path.join(ROOT, "game", "index.html")
        await game_page.goto(game_url + "?mute=1&source=tikfinity&port=21298")
        await game_page.wait_for_timeout(2500)

        visible = "on" in await game_page.evaluate(
            "document.getElementById('status-note').className")
        text = await game_page.evaluate(
            "document.getElementById('status-note').textContent")
        check("без връзка се показва бележка", visible, text[:60])
        check("бележката казва какво да се провери", "TikFinity" in text, text[:80])
        check("играта пак върви",
              await game_page.evaluate("window.game.phase") == "playing")

        # А щом връзката се вдигне, бележката изчезва.
        await game_page.goto(game_url + "?mute=1&source=tikfinity&port=%d" % PORT)
        connected = await wait_until(game_page, "window.chat.stats.connects > 0")
        check("връзката се вдига", connected)
        await game_page.wait_for_timeout(300)
        check("бележката изчезва при връзка",
              "on" not in await game_page.evaluate(
                  "document.getElementById('status-note').className"))

        await game_page.close()

        # --- Мнимият чат ------------------------------------------------------

        print("\nМним чат (за разработка без стрийм)")
        print("-" * 35)

        mock_page = await browser.new_page()
        mock_errors = []
        mock_page.on("pageerror", lambda err: mock_errors.append(str(err)))
        await mock_page.goto(PAGE + "?source=mock")

        flowing = await wait_until(mock_page, "window.chat.stats.received >= 8", timeout=20)
        check("мнимият чат ражда съобщения", flowing)
        check("без грешки на страницата", not mock_errors, mock_errors[:2])

        guessed = await wait_until(mock_page, "window.round.found.size >= 2", timeout=25)
        check("мнимите зрители познават думи", guessed,
              await mock_page.evaluate("window.round.found.size"))

        sample = await mock_page.evaluate(
            "Array.from(window.round.found.entries()).slice(0, 3)")
        if sample:
            print("     напр.  " + ", ".join("%s — %s" % (w, u) for w, u in sample))

        await mock_page.close()
        await browser.close()

    await fake.stop()

    print("\nОбобщение")
    print("-" * 9)
    print("  минали: %d   паднали: %d" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
