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
import time

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


async def wait_until(page, expression, timeout=20):
    """
    Чака JS израз да стане истина.

    Нарочно не спим фиксиран брой секунди: продължителностите идват от
    config.js и всяка промяна там би счупила теста, без нищо да е счупено.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if await page.evaluate(expression):
            return True
        await page.wait_for_timeout(100)
    return False


async def main():
    os.makedirs(SHOTS, exist_ok=True)

    async with async_playwright() as pw:
        options = {}
        chromium = find_chromium()
        if chromium:
            options["executable_path"] = chromium
        browser = await pw.chromium.launch(**options)

        # Точният размер на лентата - това е подредбата по подразбиране.
        page = await browser.new_page(viewport={"width": 1080, "height": 480})

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

        check("подредбата е лента",
              "band" in await page.evaluate("document.getElementById('stage').className"))

        # В лента всеки пиксел е зает - нищо не бива да излиза навън.
        overflow = await page.evaluate("""
          (function () {
            var stage = document.getElementById('stage').getBoundingClientRect();
            var out = [];
            ['header', 'stack', 'slots', 'board'].forEach(function (id) {
              var r = document.getElementById(id).getBoundingClientRect();
              if (r.bottom > stage.bottom + 1 || r.right > stage.right + 1 ||
                  r.left < stage.left - 1) {
                out.push(id);
              }
            });
            return out;
          })()
        """)
        check("нищо не излиза извън лентата", not overflow, overflow)

        # Рунд с пет различни дължини иска пет реда, а те не се събират в
        # 480px. Дълго време най-горният и най-долният се режеха наполовина,
        # без нищо да "излиза извън лентата" - #slots ги отрязваше вътре в
        # себе си. Затова се мери всяка група поотделно, а не само рамката.
        clipped = await page.evaluate("""
          (function () {
            var slots = document.getElementById('slots');
            var box = slots.getBoundingClientRect();
            var out = [];
            for (var i = 0; i < slots.children.length; i++) {
              var g = slots.children[i].getBoundingClientRect();
              if (g.top < box.top - 1 || g.bottom > box.bottom + 1) { out.push(i); }
            }
            return out;
          })()
        """)
        check("нито един ред с думи не е отрязан", not clipped,
              "отрязани редове: %s" % clipped)

        # Най-тежкият случай не идва при всеки рунд - изкарваме го нарочно.
        worst = await page.evaluate("""
          (function () {
            var slots = document.getElementById('slots');
            var seen = 0, bad = [];
            for (var round = 0; round < 25 && seen < 3; round++) {
              window.game.startRound();
              var groups = slots.children;
              if (groups.length < 5) { continue; }
              seen++;
              var box = slots.getBoundingClientRect();
              for (var i = 0; i < groups.length; i++) {
                var g = groups[i].getBoundingClientRect();
                if (g.top < box.top - 1 || g.bottom > box.bottom + 1) {
                  bad.push(round + ":" + i);
                }
              }
            }
            return { seen: seen, bad: bad,
                     fit: getComputedStyle(slots).getPropertyValue("--slot-fit").trim() };
          })()
        """)
        check("и при пет реда нищо не се реже", not worst["bad"],
              "%d рунда с 5 реда, свиване %s, отрязани %s"
              % (worst["seen"], worst["fit"], worst["bad"]))

        # Горното изкара двайсетина рунда - думите отдолу трябва да са от
        # този, който стои на екрана сега, а не от отдавна отминал.
        await page.evaluate("""
          window.game.levelPoints = 0;
          window.game.startRound();
        """)
        await page.wait_for_timeout(300)
        targets = await page.evaluate("window.game.round.targets")

        # Поредицата стои на реда на челото, не върху таймера.
        collide = await page.evaluate("""
          (function () {
            var a = document.getElementById('streak').getBoundingClientRect();
            var b = document.getElementById('timer').getBoundingClientRect();
            return !(a.right <= b.left || b.right <= a.left);
          })()
        """)
        check("поредицата не пада върху таймера", not collide)

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

        # --- Име от чата не бива да е код --------------------------------------

        print("\nЗлонамерено име от чата")
        print("-" * 23)

        # Имената идват от непознат човек в интернет и влизат в лентата и в
        # класацията. Ако не се екранират, зрител с такова име пуска код в
        # overlay-а насред стрийм.
        await page.evaluate("""
          window.injected = false;
          window.chat.say(
            '<img src=x onerror="window.injected=true">',
            window.game.round.targets[3]);
        """)
        await page.wait_for_timeout(900)

        check("вграденият код не се изпълнява",
              not await page.evaluate("window.injected"))
        check("името се вижда като текст",
              "<img" in await page.evaluate(
                  "document.getElementById('ticker').textContent"))
        check("не се е появил истински таг",
              await page.evaluate(
                  "document.querySelectorAll('#ticker img, #board img').length") == 0)
        check("класацията също е чиста",
              "<img" in await page.evaluate(
                  "document.getElementById('board-content').textContent"))


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
        reached = await wait_until(page, "window.game.phase === 'intermission'")

        check("играта влиза в пауза", reached)
        check("паузата се показва",
              "on" in await page.evaluate("document.getElementById('intermission').className"))

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

        advanced = await wait_until(page, "window.game.level === 2", timeout=30)
        check("следващото ниво тръгва без намеса", advanced,
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
        second = await wait_until(page, "window.game.phase === 'intermission'")
        check("второто класиране се показва", second)

        total_text = await page.evaluate(
            "document.getElementById('im-total-rows').textContent")
        check("изкачването се отбелязва със стрелка", "▲" in total_text, total_text[:90])
        # Мястото вече е значка с голо число, без точка след него.
        check("който се е качил, е първи", total_text.strip().startswith("1Тошко"),
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
        check("играта се върна в рунд след паузата",
              await wait_until(page, "window.game.phase === 'playing'", timeout=30))

        # Броим през събитието, а не размера на found: ако рундът свърши в
        # този прозорец, found се нулира и проверката пада без причина.
        await page.evaluate("""
          window.foundCount = 0;
          window.game.on("found", function () { window.foundCount++; });
          window.chat.connect();
        """)
        check("мнимите зрители познават думи",
              await wait_until(page, "window.foundCount >= 2", timeout=30),
              await page.evaluate("window.foundCount"))

        check("още няма грешки", not errors, errors[:3])
        real_warnings = [w for w in warnings if "favicon" not in w.lower()]
        check("няма предупреждения в конзолата", not real_warnings, real_warnings[:3])


        # --- Звукът ------------------------------------------------------------

        print("\nБутонът за звука")
        print("-" * 16)

        inside = await page.evaluate("""
          (function () {
            var s = document.getElementById('stage').getBoundingClientRect();
            var b = document.getElementById('mute-btn').getBoundingClientRect();
            return b.right <= s.right + 1 && b.bottom <= s.bottom + 1;
          })()
        """)
        check("бутонът е вътре в лентата", inside)
        check("бутонът е блед, за да не личи на стрийма",
              float(await page.evaluate(
                  "getComputedStyle(document.getElementById('mute-btn')).opacity")) < 0.6)

        # Поредицата качва височината чрез playbackRate. Браузърите обаче
        # по подразбиране ПАЗЯТ височината при смяна на скоростта - тогава
        # звукът просто свири по-бързо на същия тон и целият ефект липсва.
        pitch = await page.evaluate("""
          (function () {
            var items = window.dumichkiSounds.pool.word.items;
            return items.map(function (a) { return a.preservesPitch; });
          })()
        """)
        check("звукът се качва по височина, не само по скорост",
              all(value is False for value in pitch), pitch)

        rates = await page.evaluate("""
          (function () {
            var s = window.dumichkiSounds;
            var out = [];
            [1, 3, 8, 40].forEach(function (streak) {
              out.push(Math.min(s.cfg.pitchMax,
                       1 + Math.max(0, streak - 1) * s.cfg.pitchStep));
            });
            return out;
          })()
        """)
        check("височината расте с поредицата и има таван",
              rates[0] == 1 and rates[1] > rates[0] and rates[2] > rates[1]
              and rates[3] <= 1.9001, rates)

        async def sound_on():
            return await page.evaluate("window.dumichkiSounds.enabled")

        before = await sound_on()
        await page.click("#mute-btn")
        await page.wait_for_timeout(200)
        check("натискането обръща състоянието", await sound_on() != before)

        icon = await page.evaluate("document.getElementById('mute-btn').textContent")
        check("иконата следва състоянието",
              icon == ("🔊" if await sound_on() else "🔇"), icon)

        await page.keyboard.press("m")
        await page.wait_for_timeout(200)
        check("клавишът M също работи", await sound_on() == before)

        # Изборът трябва да преживее презареждане на browser source-а.
        want_off = before
        if await sound_on() != (not want_off):
            await page.click("#mute-btn")
            await page.wait_for_timeout(200)
        state_before_reload = await sound_on()

        # Нарочно БЕЗ ?mute=1: изричното в адреса бие запомненото, тоест
        # с него в адреса тази проверка не би измервала нищо.
        await page.goto(PAGE + "?source=mock")
        await page.wait_for_timeout(1600)
        check("изборът се помни след презареждане",
              await sound_on() == state_before_reload,
              "беше %s, стана %s" % (state_before_reload, await sound_on()))

        # И обратното: ?mute=1 трябва да надделява над запомненото.
        await page.goto(PAGE + "?source=mock&mute=1")
        await page.wait_for_timeout(1400)
        check("?mute=1 в адреса бие запомненото", not await sound_on())

        await page.evaluate("localStorage.removeItem('dumichki.audio')")


        # --- Целият екран още работи -------------------------------------------

        print("\nПодредба за цял екран")
        print("-" * 21)

        tall = await browser.new_page(viewport={"width": 1080, "height": 1920})
        tall_errors = []
        tall.on("pageerror", lambda e: tall_errors.append(str(e)))
        await tall.goto(PAGE + "?source=mock&mute=1&layout=tall")
        await tall.wait_for_timeout(1800)

        check("зарежда се без грешки", not tall_errors, tall_errors[:2])
        check("сцената е 1080x1920", await tall.evaluate(
            "(function(){var r=document.getElementById('stage').getBoundingClientRect();"
            "return Math.round(r.width) + 'x' + Math.round(r.height);})()") == "1080x1920")

        deepest = await tall.evaluate("""
          Math.max.apply(null,
            Array.from(document.querySelectorAll('#board, #ticker, #slots, #stack, #header'))
              .map(function (e) { return e.getBoundingClientRect().bottom; }))
        """)
        check("нищо не влиза в долните 25% на екрана", deepest <= 1440,
              "най-ниското стига до %d px" % deepest)

        # Тук поредицата е встрани от слотовете, не в челото - трябва да е
        # под стойката, а не върху нея.
        gap = await tall.evaluate("""
          (function () {
            var a = document.getElementById('streak').getBoundingClientRect();
            var b = document.getElementById('stack').getBoundingClientRect();
            return Math.round(a.top - b.bottom);
          })()
        """)
        check("броячът на поредицата не пада върху стойката", gap >= 0,
              "разлика %d px" % gap)

        btn_top = await tall.evaluate(
            "document.getElementById('mute-btn').getBoundingClientRect().top")
        check("бутонът за звука е в закритата зона", btn_top >= 1440,
              "стои от %d px" % btn_top)

        check("думите пишат и мярката", "букви" in " ".join(await tall.evaluate(
            "Array.from(document.querySelectorAll('.group-label'))"
            ".map(function(e){return e.textContent;})")))

        await shot(tall, "09-цял-екран.png")
        await tall.close()

        await shot(page, "08-игра.png")
        await browser.close()

    print("\nОбобщение")
    print("-" * 9)
    print("  минали: %d   паднали: %d" % (passed, failed))
    print("  снимки: %s" % SHOTS)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
