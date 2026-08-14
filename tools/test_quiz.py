#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест на "Стани богат" - истински Chromium.

Проверява гласуването, мнозинството, стълбата, 50:50 и края на играта.

    python3 tools/test_quiz.py
"""

import asyncio
import json
import os
import re
import sys
import time

try:
    from playwright.async_api import async_playwright
except ImportError:
    sys.exit("Липсва playwright. Пусни: pip install playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = "file://" + os.path.join(ROOT, "game", "quiz.html")
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


async def wait_until(page, expression, timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if await page.evaluate(expression):
            return True
        await page.wait_for_timeout(100)
    return False


def check_question_bank():
    """Банката се чете без браузър - грешките в нея са най-скъпи."""
    print("Банката с въпроси")
    print("-" * 17)

    path = os.path.join(ROOT, "game", "data", "questions.js")
    source = open(path, encoding="utf-8").read()

    rows = re.findall(r"\{\s*q:\s*(\".*?\"),\s*a:\s*(\[.*?\]),\s*t:\s*(\d),\s*lvl:\s*(\d)\s*\}",
                      source, re.S)
    check("въпросите се четат", len(rows) > 50, "%d намерени" % len(rows))

    bad_answers = []
    bad_target = []
    duplicate_answers = []
    seen = {}
    duplicates = []
    levels = {1: 0, 2: 0, 3: 0}

    for q, a, t, lvl in rows:
        question = json.loads(q)
        answers = json.loads(a)
        target = int(t)
        level = int(lvl)
        levels[level] = levels.get(level, 0) + 1

        if len(answers) != 4:
            bad_answers.append(question)
        if not (0 <= target < len(answers)):
            bad_target.append(question)
        if len(set(answers)) != len(answers):
            duplicate_answers.append(question)
        if question in seen:
            duplicates.append(question)
        seen[question] = True

    check("всеки въпрос има точно 4 отговора", not bad_answers, bad_answers[:2])
    check("верният отговор сочи към съществуващ", not bad_target, bad_target[:2])
    check("няма повтарящи се отговори в един въпрос",
          not duplicate_answers, duplicate_answers[:2])
    check("няма повтарящи се въпроси", not duplicates, duplicates[:2])
    check("има въпроси и от трите нива",
          all(levels.get(n, 0) >= 10 for n in (1, 2, 3)), levels)
    print("     ниво 1: %d   ниво 2: %d   ниво 3: %d"
          % (levels.get(1, 0), levels.get(2, 0), levels.get(3, 0)))


async def main():
    check_question_bank()

    async with async_playwright() as pw:
        options = {}
        chromium = find_chromium()
        if chromium:
            options["executable_path"] = chromium
        browser = await pw.chromium.launch(**options)
        page = await browser.new_page(viewport={"width": 1080, "height": 480})

        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append("CONSOLE " + m.text)
                if m.type == "error" else None)

        await page.goto(PAGE + "?source=mock&mute=1")
        await page.wait_for_timeout(1500)

        print("\nЗареждане")
        print("-" * 9)
        check("няма грешки на страницата", not errors, errors[:2])
        check("въпросите са заредени",
              await page.evaluate("window.DUMICHKI_QUESTIONS.length") > 50)
        check("играта пита", await page.evaluate("window.quiz.phase") == "asking")

        # Спираме мнимите гласоподаватели, за да гласуваме ние.
        await page.evaluate("window.chat.disconnect(); window.quiz.votes.clear();")

        check("показани са 4 отговора",
              await page.evaluate("document.querySelectorAll('.answer').length") == 4)
        check("въпросът е изписан",
              len(await page.evaluate(
                  "document.getElementById('q-text').textContent")) > 10)

        overflow = await page.evaluate("""
          (function () {
            var s = document.getElementById('stage').getBoundingClientRect();
            var out = [];
            ['q-header', 'q-text', 'q-answers', 'q-foot'].forEach(function (id) {
              var r = document.getElementById(id).getBoundingClientRect();
              if (r.bottom > s.bottom + 1 || r.right > s.right + 1) { out.push(id); }
            });
            return out;
          })()
        """)
        check("нищо не излиза извън лентата", not overflow, overflow)

        await page.screenshot(path=os.path.join(SHOTS, "quiz-1.png"))

        # --- Гласуване --------------------------------------------------------

        print("\nГласуване")
        print("-" * 9)

        await page.evaluate('window.chat.say("Иван", "2")')
        await page.wait_for_timeout(250)
        counts = await page.evaluate("window.quiz.tally()")
        check("гласът се брои", counts[1] == 1, counts)

        await page.evaluate('window.chat.say("Иван", "3")')
        await page.wait_for_timeout(250)
        counts = await page.evaluate("window.quiz.tally()")
        check("промяна на мнението не добавя втори глас",
              sum(counts) == 1 and counts[2] == 1, counts)

        await page.evaluate('window.chat.say("Мария", "б")')
        await page.evaluate('window.chat.say("Гошо", "C")')
        await page.wait_for_timeout(300)
        counts = await page.evaluate("window.quiz.tally()")
        check("кирилски и латински букви също са гласове",
              counts[1] == 1 and counts[2] == 2, counts)

        await page.evaluate('window.chat.say("Спам", "имам 2 идеи")')
        await page.evaluate('window.chat.say("Спам", "здравейте")')
        await page.evaluate('window.chat.say("Спам", "7")')
        await page.wait_for_timeout(300)
        check("изречения и грешни числа не се броят",
              sum(await page.evaluate("window.quiz.tally()")) == 3)

        shown = await page.evaluate(
            "document.getElementById('q-votes').textContent")
        check("броят гласове се показва", "3" in shown, shown)

        await page.screenshot(path=os.path.join(SHOTS, "quiz-2.png"))

        # --- 50:50 ------------------------------------------------------------

        print("\n50:50")
        print("-" * 5)

        for i in range(5):
            await page.evaluate('window.chat.say("зрител %d", "50")' % i)
        await page.wait_for_timeout(400)

        check("50:50 се задейства от чата",
              await page.evaluate("window.quiz.fiftyUsed"))
        gone = await page.evaluate("document.querySelectorAll('.answer.gone').length")
        check("два отговора отпадат", gone == 2, gone)

        correct = await page.evaluate("window.quiz.correctPosition()")
        removed = await page.evaluate("window.quiz.removed")
        check("верният отговор не е сред махнатите", correct not in removed,
              "верен %d, махнати %s" % (correct, removed))

        await page.screenshot(path=os.path.join(SHOTS, "quiz-3.png"))

        # --- Разкриване и изкачване -------------------------------------------

        print("\nРазкриване")
        print("-" * 10)

        # Всички гласуват вярно, за да мине нагоре.
        await page.evaluate("""
          window.quiz.votes.clear();
          var right = window.quiz.correctPosition();
          ["а", "б", "в"].forEach(function (name, i) {
            window.quiz.votes.set("зрител " + name, right);
          });
          window.quiz.reveal();
        """)
        await page.wait_for_timeout(400)

        check("верният отговор се маркира",
              await page.evaluate("document.querySelectorAll('.answer.right').length") == 1)
        check("няма сгрешен маркер при верен отговор",
              await page.evaluate("document.querySelectorAll('.answer.wrong').length") == 0)
        check("гласувалите вярно получават точки",
              await page.evaluate("window.quiz.board.size()") == 3)

        step_before = await page.evaluate("window.quiz.step")
        await wait_until(page, "window.quiz.phase === 'asking'")
        check("играта се качва на следващо стъпало",
              await page.evaluate("window.quiz.step") == step_before + 1)

        prize = await page.evaluate("document.getElementById('q-prize').textContent")
        check("наградата расте", "200" in prize, prize)

        # --- Грешка слага край -------------------------------------------------

        print("\nГрешен отговор")
        print("-" * 14)

        await page.evaluate("""
          window.quiz.votes.clear();
          var right = window.quiz.correctPosition();
          var wrong = (right + 1) % 4;
          window.quiz.votes.set("грешащ", wrong);
          window.quiz.reveal();
        """)
        await page.wait_for_timeout(400)

        check("грешният избор се маркира",
              await page.evaluate("document.querySelectorAll('.answer.wrong').length") == 1)

        ended = await wait_until(page, "window.quiz.phase === 'over'")
        check("играта свършва", ended)
        check("показва се краят",
              "on" in await page.evaluate(
                  "document.getElementById('q-end').className"))
        check("показва се сумата",
              "лв" in await page.evaluate(
                  "document.getElementById('q-end-prize').textContent"))

        # Изчакваме избледняването, иначе на снимката краят прозира зад
        # отговорите и изглежда като счупен слой.
        await page.wait_for_timeout(700)
        await page.screenshot(path=os.path.join(SHOTS, "quiz-4.png"))

        started = await wait_until(page, "window.quiz.phase === 'asking'", timeout=30)
        check("нова игра тръгва сама", started)
        check("стълбата се нулира", await page.evaluate("window.quiz.step") == 0)

        # --- Мнимият чат кара сам ---------------------------------------------

        print("\nМнимите зрители")
        print("-" * 15)

        await page.evaluate("""
          window.voted = 0;
          window.quiz.on("vote", function () { window.voted++; });
          window.chat.connect();
        """)
        check("мнимите зрители гласуват",
              await wait_until(page, "window.voted >= 3", timeout=25),
              await page.evaluate("window.voted"))

        check("още няма грешки", not errors, errors[:2])
        await browser.close()

    print("\nОбобщение")
    print("-" * 9)
    print("  минали: %d   паднали: %d" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
