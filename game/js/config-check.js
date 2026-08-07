/* Проверка на config.js преди играта да тръгне.
 *
 * Конфигурацията се пипа на ръка, между стриймове, често набързо. Една
 * сгрешена стойност не бива да остави черен екран без обяснение - точно
 * това е най-скъпият вид грешка, защото се вижда чак на живо.
 *
 * Затова: спиращите грешки излизат на екрана с думи, а съмнителните
 * настройки отиват в конзолата като предупреждение.
 */
(function (root) {
  "use strict";

  function isNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  function check(cfg, data, sources) {
    var errors = [];
    var warnings = [];

    function need(condition, message) {
      if (!condition) { errors.push(message); }
    }
    function warn(condition, message) {
      if (!condition) { warnings.push(message); }
    }

    // --- Има ли изобщо конфигурация -----------------------------------------

    if (!cfg) {
      return { errors: ["config.js не е зареден изобщо."], warnings: [] };
    }
    var sections = ["layout", "chat", "round", "level", "scoring", "stack",
                    "board", "audio", "theme"];
    for (var i = 0; i < sections.length; i++) {
      if (!cfg[sections[i]]) {
        errors.push("Липсва раздел \"" + sections[i] + "\" в config.js.");
      }
    }
    if (errors.length) { return { errors: errors, warnings: warnings }; }

    // --- Подредба -------------------------------------------------------------

    need(cfg.layout.mode === "band" || cfg.layout.mode === "tall",
      "layout.mode е \"" + cfg.layout.mode + "\", а може да бъде само " +
      "\"band\" (лента под геймплея) или \"tall\" (целият екран).");
    need(isNumber(cfg.layout.width) && cfg.layout.width >= 400,
      "layout.width трябва да е число, поне 400.");
    need(isNumber(cfg.layout.height) && cfg.layout.height >= 240,
      "layout.height трябва да е число, поне 240.");
    warn(!(cfg.layout.mode === "band" && cfg.layout.height > 900),
      "layout.height е " + cfg.layout.height + " при подредба \"band\" - " +
      "толкова висока лента вероятно иска mode: \"tall\".");
    warn(!(cfg.layout.mode === "band" && cfg.stack.targetsMax > 10),
      "stack.targetsMax е " + cfg.stack.targetsMax + " при лента - думите " +
      "ще станат ситни. За лента 7-9 се чете по-добре.");

    // --- Чат ------------------------------------------------------------------

    need(sources.indexOf(cfg.chat.source) !== -1,
      "chat.source е \"" + cfg.chat.source + "\", а може да бъде само: " +
      sources.join(", ") + ".");
    need(isNumber(cfg.chat.cooldown) && cfg.chat.cooldown >= 0,
      "chat.cooldown трябва да е число секунди, не по-малко от 0.");
    warn(cfg.chat.cooldown >= 3,
      "chat.cooldown е " + cfg.chat.cooldown + " секунди - един зрител с " +
      "анаграм солвър може да изяде целия рунд.");

    // --- Стойка спрямо речника ------------------------------------------------

    var lengths = cfg.stack.seedLengths;
    need(Array.isArray(lengths) && lengths.length > 0,
      "stack.seedLengths трябва да е списък, например [6, 7].");

    if (Array.isArray(lengths)) {
      for (var s = 0; s < lengths.length; s++) {
        var length = lengths[s];
        // Тази е важната: речникът се строи до определена дължина и по-дълга
        // стойка просто няма от какво да се получи. Играта би се въртяла в
        // празни опити, без нищо на екрана.
        if (length > data.maxLength) {
          errors.push(
            "stack.seedLengths иска стойка от " + length + " букви, но речникът " +
            "е построен до " + data.maxLength + ". Пусни отново:\n" +
            "    python3 tools/build_dictionary.py --runtime-max-len " + length);
        } else if (length < 4) {
          errors.push("stack.seedLengths иска стойка от " + length +
            " букви - от толкова малко не се съставя нищо.");
        }
      }
    }

    need(isNumber(cfg.stack.targetsMin) && isNumber(cfg.stack.targetsMax) &&
      cfg.stack.targetsMin <= cfg.stack.targetsMax,
      "stack.targetsMin не бива да е по-голямо от stack.targetsMax.");
    need(isNumber(cfg.stack.minPlayable) && isNumber(cfg.stack.maxPlayable) &&
      cfg.stack.minPlayable <= cfg.stack.maxPlayable,
      "stack.minPlayable не бива да е по-голямо от stack.maxPlayable.");
    warn(cfg.stack.minPlayable >= cfg.stack.targetsMin,
      "stack.minPlayable (" + cfg.stack.minPlayable + ") е под targetsMin (" +
      cfg.stack.targetsMin + ") - някои рундове ще имат по-малко цели от " +
      "искания брой.");

    // --- Времена --------------------------------------------------------------

    need(isNumber(cfg.round.duration) && cfg.round.duration >= 10,
      "round.duration трябва да е поне 10 секунди.");
    need(isNumber(cfg.round.shuffleEvery) && cfg.round.shuffleEvery > 0,
      "round.shuffleEvery трябва да е положително число секунди.");
    need(isNumber(cfg.round.gap) && cfg.round.gap >= 0,
      "round.gap трябва да е число секунди, не по-малко от 0.");
    warn(cfg.round.hintAfter < cfg.round.duration,
      "round.hintAfter (" + cfg.round.hintAfter + "s) е колкото рунда или " +
      "повече - намек няма да се появи никога.");
    warn(cfg.round.gap >= 3,
      "round.gap е " + cfg.round.gap + "s - непозналите думи ще се мернат " +
      "твърде бързо, за да се прочетат.");

    need(isNumber(cfg.level.baseThreshold) && cfg.level.baseThreshold > 0,
      "level.baseThreshold трябва да е положително число точки.");
    need(isNumber(cfg.level.intermission) && cfg.level.intermission >= 0,
      "level.intermission трябва да е число секунди.");
    warn(cfg.level.intermission >= 5,
      "level.intermission е " + cfg.level.intermission + "s - двете класации " +
      "няма да се успеят да се прочетат.");

    // --- Точки ----------------------------------------------------------------

    need(isNumber(cfg.scoring.pointsPerLetter) && cfg.scoring.pointsPerLetter > 0,
      "scoring.pointsPerLetter трябва да е положително число.");
    need(isNumber(cfg.scoring.streakMax) && cfg.scoring.streakMax >= 1,
      "scoring.streakMax трябва да е поне 1 (1 значи без множител).");

    // Груба сметка колко рунда ще трае едно ниво - за да не се окаже, че
    // прагът е недостижим и нивото не свършва никога.
    var perRound = cfg.stack.targetsMin * 5 * cfg.scoring.pointsPerLetter;
    warn(cfg.level.baseThreshold <= perRound * 6,
      "level.baseThreshold е " + cfg.level.baseThreshold + " точки, а един " +
      "рунд дава около " + perRound + ". Нивото ще трае много рундове.");

    // --- Класации и изглед ----------------------------------------------------

    need(isNumber(cfg.board.inGame) && cfg.board.inGame >= 1,
      "board.inGame трябва да е поне 1.");
    need(isNumber(cfg.board.intermission) && cfg.board.intermission >= 1,
      "board.intermission трябва да е поне 1.");
    warn(cfg.board.inGame <= 5,
      "board.inGame е " + cfg.board.inGame + " - в лентата по време на игра " +
      "има място за около 5 реда.");

    need(isNumber(cfg.audio.volume) && cfg.audio.volume >= 0 && cfg.audio.volume <= 1,
      "audio.volume трябва да е между 0 и 1.");

    var themeKeys = ["background", "text", "accent", "success", "hot", "slot", "font"];
    for (var t = 0; t < themeKeys.length; t++) {
      if (!cfg.theme[themeKeys[t]]) {
        errors.push("Липсва theme." + themeKeys[t] + " в config.js.");
      }
    }

    return { errors: errors, warnings: warnings };
  }

  /* Показва грешките на екрана - иначе стриймърът вижда само черно. */
  function report(result) {
    for (var w = 0; w < result.warnings.length; w++) {
      console.warn("[конфигурация] " + result.warnings[w]);
    }
    if (!result.errors.length) { return false; }

    var escapeHtml = root.Dumichki.escapeHtml;
    var box = document.getElementById("fatal");
    box.innerHTML = "<h1>Грешка в config.js</h1>" +
      result.errors.map(function (message) {
        return "<p>" + escapeHtml(message) + "</p>";
      }).join("") +
      "<div class=\"hint\">Поправи файла и обнови browser source-а.</div>";
    box.classList.add("on");

    result.errors.forEach(function (message) {
      console.error("[конфигурация] " + message);
    });
    return true;
  }

  root.Dumichki = root.Dumichki || {};
  root.Dumichki.checkConfig = check;
  root.Dumichki.reportConfig = report;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { check: check };
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
