#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест на overlay-а - истински Chromium, истинско 1080x1920.

Кара играта през целия ѝ живот: рунд, познаване, поредица, намек,
разбъркване, край на рунд, край на ниво с двете класации. По пътя прави
екранни снимки в tools/screenshots/, за да се види какво излиза наистина.

    python3 tools/test_overlay.py
"""

import asyncio
import os
import sys

try:
    from playwright.async_api import async_playwright
except ImportError:
    sys.exit("Липсва playwright. Пусни: pip install playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = "file://" + os.path.join(ROOT, "game", "index.html")
SHOTS = os.path.join(ROOT, "tools", "screenshots")

CHROMIUM_CANDIDATES = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium/chrome-linux/chrome",
]

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


def find_chromium():
    for path in CHROMIUM_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


async def shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    await page.screenshot(path=os.path.join(SHOTS, name))


async def main():
    os.makedirs(SHOTS, exist_ok=True)

    async with async_playwright() as pw:
        options = {}
        chromium = find_chromium()
        if chromium:
            options["executable_path"] = chromium
        browser = await pw.chromium.launch(**options)

        # Точният размер на browser source-а в OBS.
        page = await browser.new_page(viewport={"width": 1080, "height": 1920})

        errors = []
        warnings = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: warnings.append(m.text)
                if m.type in ("error", "warning") else None)

        await page.goto(PAGE + "?source=mock&mute=1")
        await page.wait_for_timeout(1800)

        print("Зареждане")
        print("-" * 9)
        check("няма грешки на страницата", not errors, errors[:3])
        check("речникът е зареден", await page.evaluate("DUMICHKI_DATA.words.length") > 100000)
        check("играта върви", await page.evaluate("window.game.phase") == "playing")

        # Спираме мнимия чат и започваме рунда начисто - иначе мнимите
        # зрители са познали някоя дума и броячите вече не са наши.
        await page.evaluate("""
          window.chat.disconnect();
          window.game.streak = 0;
          window.game.cooldowns.clear();
          window.game.levelBoard.reset();
          window.game.totalBoard.reset();
          window.game.ticker = [];
          window.game.levelPoints = 0;
          window.game.startRound();
        """)
        await page.wait_for_timeout(300)

        tiles = await page.evaluate("document.querySelectorAll('.tile').length")
        check("стойката е нарисувана", tiles in (6, 7), "%d плочки" % tiles)

        boxes = await page.evaluate("document.querySelectorAll('.box').length")
        targets = await page.evaluate("window.game.round.targets")
        expected = sum(len(w) for w in targets)
        check("слотовете са нарисувани", boxes == expected,
              "%d кутийки за %d цели" % (boxes, len(targets)))

        groups = await page.evaluate(
            "Array.from(document.querySelectorAll('.group-label')).map(function(e){return e.textContent;})")
        check("думите са групирани по дължина", len(groups) >= 3, groups)
        print("     %s" % ", ".join(groups))

        # Нищо важно не бива да слиза в зоната на TikTok.
        bottom = await page.evaluate("""
          Array.from(document.querySelectorAll('#board, #ticker, #slots, #stack, #header'))
            .map(function (e) { return { id: e.id, bottom: e.getBoundingClientRect().bottom }; })
        """)
        deepest = max(item["bottom"] for item in bottom)
        check("нищо не влиза в долните 25% на екрана", deepest <= 1440,
              "най-ниското стига до %d px" % deepest)

        streak_box = await page.evaluate(
            "document.getElementById('streak').getBoundingClientRect()")
        stack_box = await page.evaluate(
            "document.getElementById('stack').getBoundingClientRect()")
        check("броячът на поредицата не пада върху стойката",
              streak_box["top"] >= stack_box["bottom"],
              "поредица от %d, стойка до %d" % (streak_box["top"], stack_box["bottom"]))

        await shot(page, "01-рунд.png")

        # --- Познаване --------------------------------------------------------

        print("\nПознаване")
        print("-" * 9)

        first = targets[0]
        await page.evaluate('window.chat.say("Иван", "%s")' % first)
        await page.wait_for_timeout(900)

        filled = await page.evaluate(
            "document.querySelectorAll('.word[data-word=\"%s\"] .box.filled').length" % first)
        check("буквите се приземиха в слота (%s)" % first, filled == len(first),
              "%d от %d" % (filled, len(first)))
        check("думата е отбелязана като намерена",
              await page.evaluate('window.game.round.found.has("%s")' % first))
        check("името на позналия се показва",
              await page.evaluate("document.querySelectorAll('.word-owner').length") == 1)
        check("класацията се обнови",
              "Иван" in await page.evaluate("document.getElementById('board-content').textContent"))
        check("лентата с последните се обнови",
              first in await page.evaluate("document.getElementById('ticker').textContent"))

        points = await page.evaluate('window.game.totalBoard.pointsOf("Иван")')
        check("точките са начислени", points > 0, points)

        await shot(page, "02-позната-дума.png")

        # Шльокавица през целия път.
        second = targets[1]
        latin = await page.evaluate("Dumichki.Shlyokavitsa.expand('%s')[0]" % second)
        await page.evaluate('window.chat.say("Мария", "%s")' % latin)
        await page.wait_for_timeout(800)
        check("шльокавица минава през играта (%s → %s)" % (latin, second),
              await page.evaluate('window.game.round.found.has("%s")' % second))

        # --- Cooldown ---------------------------------------------------------

        print("\nCooldown и поредица")
        print("-" * 19)

        third = targets[2]
        await page.evaluate('window.chat.say("Иван", "%s")' % third)
        await page.wait_for_timeout(400)
        check("същият зрител не може веднага пак",
              not await page.evaluate('window.game.round.found.has("%s")' % third))

        await page.evaluate('window.chat.say("Гошо", "%s")' % third)
        await page.wait_for_timeout(700)
        check("друг зрител може",
              await page.evaluate('window.game.round.found.has("%s")' % third))

        streak = await page.evaluate("window.game.streak")
        check("поредицата расте", streak == 3, streak)
        check("броячът на поредицата се вижда",
              "on" in await page.evaluate(
                  "document.getElementById('streak').className"))

        # Множителят трябва да е вдигнал точките на третата дума.
        base = len(third) * 10
        got = await page.evaluate('window.game.levelBoard.pointsOf("Гошо")')
        check("множителят от поредицата се брои", got > base, "%d при база %d" % (got, base))

        await shot(page, "03-поредица.png")

        # --- Намек и разбъркване ----------------------------------------------

        print("\nНамек и разбъркване")
        print("-" * 19)

        before = await page.evaluate(
            "Array.from(document.querySelectorAll('.tile')).map(function(t){return t.textContent;})")
        await page.evaluate("window.game.nextShuffleAt = 0")
        await page.wait_for_timeout(900)
        after = await page.evaluate(
            "Array.from(document.querySelectorAll('.tile')).map(function(t){return t.textContent;})")
        check("стойката се разбърква", before != after, "%s → %s" % (before, after))
        check("буквите са същите", sorted(before) == sorted(after))

        await page.evaluate("window.game.lastFindAt = 0")
        await page.wait_for_timeout(500)
        hinted = await page.evaluate("document.querySelectorAll('.box.hinted').length")
        check("намекът разкрива буква", hinted >= 1, "%d разкрити" % hinted)

        await shot(page, "04-намек.png")

        # --- Край на рунд -----------------------------------------------------

        print("\nКрай на рунд")
        print("-" * 12)

        await page.evaluate("window.game.endRound('time')")
        await page.wait_for_timeout(500)
        missed = await page.evaluate("document.querySelectorAll('.box.missed').length")
        check("непознатите думи се показват", missed > 0, "%d кутийки" % missed)
        await shot(page, "05-край-на-рунд.png")

        # --- Край на ниво -----------------------------------------------------

        print("\nКрай на ниво и двете класации")
        print("-" * 29)

        # Точки на няколко души, за да има какво да се класира.
        await page.evaluate("""
          window.game.totalBoard.add("Петя", 320);
          window.game.totalBoard.add("Тошко", 180);
          window.game.levelBoard.add("Петя", 320);
          window.game.levelBoard.add("Тошко", 180);
          window.game.levelPoints = window.game.threshold;
          window.game.phase = "playing";
          window.game.endRound("level");
        """)
        await page.wait_for_timeout(int(4.6 * 1000))

        check("паузата се показва",
              "on" in await page.evaluate("document.getElementById('intermission').className"))
        check("играта е в пауза",
              await page.evaluate("window.game.phase") == "intermission")

        level_rows = await page.evaluate(
            "document.querySelectorAll('#im-level-rows .im-row').length")
        total_rows = await page.evaluate(
            "document.querySelectorAll('#im-total-rows .im-row').length")
        check("класацията за нивото е попълнена", level_rows >= 3, level_rows)
        check("общата класация е попълнена", total_rows >= 3, total_rows)

        check("има отброяване",
              (await page.evaluate("document.getElementById('im-seconds').textContent")).isdigit())
        check("има конфети",
              await page.evaluate("document.querySelectorAll('.confetto').length") > 20)

        # При първото ниво всички са нови - пет пъти "нов" не казва нищо.
        badges = await page.evaluate(
            "document.querySelectorAll('#im-total-rows .move').length")
        check("при първото ниво няма стрелки", badges == 0, "%d значки" % badges)

        await page.wait_for_timeout(900)
        await shot(page, "06-между-нивата.png")

        # --- Следващото ниво тръгва само -------------------------------------

        print("\nСледващото ниво")
        print("-" * 15)

        await page.wait_for_timeout(int(10.5 * 1000))
        check("следващото ниво тръгва без намеса",
              await page.evaluate("window.game.level") == 2,
              await page.evaluate("window.game.level"))
        check("паузата се скри",
              "on" not in await page.evaluate(
                  "document.getElementById('intermission').className"))
        check("класацията за нивото е нулирана",
              await page.evaluate("window.game.levelBoard.size()") == 0)
        check("общата класация е запазена",
              await page.evaluate("window.game.totalBoard.size()") > 0)
        check("нивото се показва",
              "2" in await page.evaluate(
                  "document.getElementById('level-name').textContent"))

        await shot(page, "07-ниво-2.png")

        # --- Второто класиране: сега вече има какво да се сравнява ------------

        print("\nИзкачване в общата класация")
        print("-" * 27)

        # Тошко беше втори; вдигаме го над Петя, за да има истинско изкачване.
        await page.evaluate("""
          window.game.totalBoard.add("Тошко", 900);
          window.game.levelBoard.add("Тошко", 900);
          window.game.levelBoard.add("Гошо", 120);
          window.game.levelPoints = window.game.threshold;
          window.game.phase = "playing";
          window.game.endRound("level");
        """)
        await page.wait_for_timeout(int(4.8 * 1000))

        total_text = await page.evaluate(
            "document.getElementById('im-total-rows').textContent")
        check("изкачването се отбелязва със стрелка", "▲" in total_text, total_text[:90])
        check("който се е качил, е първи", total_text.strip().startswith("1.Тошко"),
              total_text[:60])

        level_text = await page.evaluate(
            "document.getElementById('im-level-rows').textContent")
        check("класацията за нивото е само от това ниво",
              "Петя" not in level_text, level_text[:90])

        await page.wait_for_timeout(700)
        await shot(page, "09-изкачване.png")

        # --- Мнимият чат кара играта сам --------------------------------------

        print("\nИграта се кара сама")
        print("-" * 19)

        # Изчакваме паузата да свърши - в нея играта не приема догадки.
        for _ in range(60):
            if await page.evaluate("window.game.phase") == "playing":
                break
            await page.wait_for_timeout(500)
        check("играта се върна в рунд след паузата",
              await page.evaluate("window.game.phase") == "playing")

        await page.evaluate("window.chat.connect()")
        found_before = await page.evaluate("window.game.round.found.size")
        await page.wait_for_timeout(9000)
        found_after = await page.evaluate("window.game.round.found.size")
        check("мнимите зрители познават думи", found_after > found_before,
              "%d → %d" % (found_before, found_after))

        check("още няма грешки", not errors, errors[:3])
        real_warnings = [w for w in warnings if "favicon" not in w.lower()]
        check("няма предупреждения в конзолата", not real_warnings, real_warnings[:3])

        await shot(page, "08-игра.png")
        await browser.close()

    print("\nОбобщение")
    print("-" * 9)
    print("  минали: %d   паднали: %d" % (passed, failed))
    print("  снимки: %s" % SHOTS)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
