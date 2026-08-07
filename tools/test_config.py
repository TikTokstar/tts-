#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест на конфигурацията.

Две неща, които заданието обещава и които не се виждат от кода:

  1. Сгрешена настройка да казва какво е сгрешено, вместо да остави
     празен екран, за който разбираш чак на живо.
  2. Промяна в config.js наистина да променя играта - иначе файлът е
     украса.

Тестът пипа game/config.js за кратко и го връща както е бил, включително
ако нещо гръмне по средата.

    python3 tools/test_config.py
"""

import asyncio
import json
import os
import shutil
import sys
import time

try:
    from playwright.async_api import async_playwright
except ImportError:
    sys.exit("Липсва playwright. Пусни: pip install playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "game", "config.js")
BACKUP = CONFIG + ".backup"
PAGE = "file://" + os.path.join(ROOT, "game", "index.html")

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


async def wait_until(page, expression, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if await page.evaluate(expression):
            return True
        await page.wait_for_timeout(100)
    return False


def write_config(**overrides):
    """
    Пише config.js със заменени стойности върху разумна основа.

    Сглобява се като речник и излиза като JSON - обектът в config.js е
    JSON-съвместим, а така не се борим с екраниране на скоби.
    """
    cfg = {
        "layout": {"mode": "band", "width": 1080, "height": 480, "backdrop": 0.82},
        "chat": {"source": "mock", "host": "localhost", "port": None,
                 "debug": False, "cooldown": 8},
        "round": {"duration": 90, "hintAfter": 25, "shuffleEvery": 15, "gap": 5},
        "level": {"baseThreshold": 800, "thresholdGrowth": 200, "intermission": 10},
        "scoring": {"pointsPerLetter": 10, "speedWindow": 5, "speedBonus": 1.5,
                    "streakStep": 0.1, "streakMax": 2.0, "streakTimeout": 15},
        "stack": {"seedLengths": [6, 7], "targetsMin": 8, "targetsMax": 9,
                  "minPlayable": 10, "maxPlayable": 40,
                  "minVowels": 2, "maxRareLetters": 1},
        "board": {"inGame": 3, "intermission": 5, "ticker": 4},
        "audio": {"enabled": False, "volume": 0.55, "folder": "audio/",
                  "pitchStep": 0.06, "pitchMax": 1.9},
        "theme": {"background": "#0d0b1a", "backgroundGlow": "#2a1a5e",
                  "text": "#f4f2ff", "dim": "#8b86ad", "accent": "#ffd23f",
                  "accentSoft": "#ffe98a", "success": "#4ade80", "hot": "#ff4d6d",
                  "slot": "#1c1836", "slotEdge": "#332c5c",
                  "panel": "rgba(20, 16, 44, 0.82)",
                  "font": "'Trebuchet MS', sans-serif"},
        "showSafeArea": False,
    }

    # Ключът "раздел.настройка" е недвусмислен - иначе intermission е и в
    # level, и в board.
    for dotted, value in overrides.items():
        section, key = dotted.split(".")
        cfg[section][key] = value

    with open(CONFIG, "w", encoding="utf-8") as fh:
        fh.write("window.DUMICHKI_CONFIG = %s;\n"
                 % json.dumps(cfg, ensure_ascii=False, indent=2))


async def load(page, **overrides):
    write_config(**overrides)
    await page.goto(PAGE + "?mute=1")
    await page.wait_for_timeout(1500)


async def main():
    shutil.copy(CONFIG, BACKUP)
    try:
        return await run()
    finally:
        shutil.move(BACKUP, CONFIG)
        print("\nconfig.js е върнат както си беше.")


async def run():
    async with async_playwright() as pw:
        options = {}
        chromium = find_chromium()
        if chromium:
            options["executable_path"] = chromium
        browser = await pw.chromium.launch(**options)
        page = await browser.new_page(viewport={"width": 1080, "height": 1920})

        messages = []
        page.on("console", lambda m: messages.append(m.text))

        # --- Сгрешена конфигурация казва какво е сгрешено ---------------------

        print("Сгрешена конфигурация")
        print("-" * 21)

        # Точно капанът: изглежда разумно, но речникът е построен до 7 букви.
        await load(page, **{"stack.seedLengths": [8]})
        shown = "on" in await page.evaluate("document.getElementById('fatal').className")
        text = await page.evaluate("document.getElementById('fatal').textContent")
        check("стойка над речника спира играта с обяснение", shown, text[:70])
        check("обяснението казва какво да се пусне",
              "--runtime-max-len 8" in text, text[:120])
        check("играта не тръгва", await page.evaluate("typeof window.game") == "undefined")

        await load(page, **{"chat.source": "tikfinityy"})
        text = await page.evaluate("document.getElementById('fatal').textContent")
        check("сгрешено име на източник се хваща", "tikfinityy" in text, text[:70])
        check("изброяват се възможните", "tikfinity" in text and "mock" in text, text[:110])

        await load(page, **{"stack.targetsMin": 14, "stack.targetsMax": 10})
        check("разменени targetsMin/Max се хващат",
              "on" in await page.evaluate("document.getElementById('fatal').className"))

        await load(page, **{"layout.mode": "лента"})
        text = await page.evaluate("document.getElementById('fatal').textContent")
        check("непозната подредба се хваща", "layout.mode" in text, text[:70])
        check("казва кои са двете", "band" in text and "tall" in text, text[:110])

        # --- Съмнителни, но допустими настройки -------------------------------

        print("\nПредупреждения")
        print("-" * 14)

        messages.clear()
        await load(page, **{"chat.cooldown": 0, "level.intermission": 2})
        warnings = [m for m in messages if "конфигурация" in m]
        check("нулев cooldown предупреждава",
              any("cooldown" in w for w in warnings), warnings[:2])
        check("твърде къса пауза предупреждава",
              any("intermission" in w for w in warnings), warnings[:2])
        check("но играта пак тръгва",
              await page.evaluate("window.game && window.game.phase") == "playing")

        # --- Настройките наистина управляват играта ----------------------------

        print("\nПромяната в config.js стига до играта")
        print("-" * 36)

        await load(page, **{"round.duration": 20, "scoring.pointsPerLetter": 3,
                            "scoring.speedWindow": 0, "chat.cooldown": 0,
                            "board.inGame": 5, "theme.accent": "#00ff88",
                            "layout.mode": "tall", "layout.height": 1920})
        # Начисто: ако мнимият чат е познал дума в тези 1.5 секунди,
        # поредицата тръгва от 2 и множителят разваля сметката за точките.
        await page.evaluate("""
          window.chat.disconnect();
          window.game.streak = 0;
          window.game.cooldowns.clear();
          window.game.levelBoard.reset();
          window.game.totalBoard.reset();
          window.game.startRound();
        """)
        await page.wait_for_timeout(400)

        timer = await page.evaluate("document.getElementById('timer').textContent")
        check("round.duration управлява таймера", timer in ("0:20", "0:19"), timer)

        targets = await page.evaluate("window.game.round.targets")
        word = targets[0]
        await page.evaluate('window.chat.say("Тест", "%s")' % word)
        await page.wait_for_timeout(400)
        points = await page.evaluate('window.game.totalBoard.pointsOf("Тест")')
        check("scoring.pointsPerLetter управлява точките",
              points == len(word) * 3, "%d точки за %d букви" % (points, len(word)))

        await page.evaluate('window.chat.say("Тест", "%s")' % targets[1])
        await page.wait_for_timeout(400)
        check("chat.cooldown: 0 пуска същия зрител веднага",
              await page.evaluate('window.game.round.found.size') == 2)

        await page.evaluate("""
          ["а","б","в","г","д","е"].forEach(function (name, i) {
            window.game.totalBoard.add("зрител " + name, 100 - i);
          });
        """)
        await page.evaluate("window.game.startRound()")
        await page.wait_for_timeout(300)
        rows = await page.evaluate("document.querySelectorAll('#board-content .board-row').length")
        check("board.inGame управлява реда в класацията", rows == 5, "%d реда" % rows)

        color = await page.evaluate(
            "getComputedStyle(document.getElementById('level-name')).color")
        check("theme.accent управлява цвета", color == "rgb(0, 255, 136)", color)

        check("layout.mode управлява подредбата",
              "tall" in await page.evaluate(
                  "document.getElementById('stage').className"))
        check("layout.height управлява височината",
              await page.evaluate(
                  "document.getElementById('stage').getBoundingClientRect().height") == 1920)

        # --- Читавата конфигурация минава чиста --------------------------------

        print("\nКонфигурацията по подразбиране")
        print("-" * 30)

        shutil.copy(BACKUP, CONFIG)
        messages.clear()
        await page.goto(PAGE + "?mute=1")
        await page.wait_for_timeout(1600)

        check("минава без спираща грешка",
              "on" not in await page.evaluate("document.getElementById('fatal').className"))
        complaints = [m for m in messages if "конфигурация" in m]
        check("минава и без предупреждения", not complaints, complaints[:3])
        check("играта тръгва",
              await page.evaluate("window.game.phase") == "playing")

        await browser.close()

    print("\nОбобщение")
    print("-" * 9)
    print("  минали: %d   паднали: %d" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
