/* Мнимият чат - за разработка без жив стрийм.
 *
 * Не имитира TikTok формата, а направо ражда нормализирани събития. Целта
 * не е да е реалистичен протоколно, а трафикът да прилича на истински:
 * повечето съобщения са боклук, част от догадките са на шльокавица, а
 * едни и същи хора се обаждат по няколко пъти.
 */
(function (root) {
  "use strict";

  var NAMES = [
    "ivan_92", "Мария", "gosho", "Петя ✨", "dani_bg", "Стефан",
    "kaloyan", "Виктория", "toshko", "Ели", "mitko_99", "Ани",
    "borko", "Габи", "niki", "Радост", "спас", "vanko"
  ];

  var NOISE = [
    "здравейте", "яко е", "поздрави", "🔥🔥🔥", "аз съм нов тук",
    "kak si", "браво", "не мога да измисля", "хаха", "супер",
    "поздрав от варна", "❤️", "трудно е", "давай", "оооо",
    "азбука", "непозната", "гювеч", "ааааа", "къде си"
  ];

  var timer = null;

  function pick(list) {
    return list[Math.floor(Math.random() * list.length)];
  }

  function start(config, deliver) {
    var minGap = (config.mockInterval && config.mockInterval[0]) || 700;
    var maxGap = (config.mockInterval && config.mockInterval[1]) || 2200;
    var hitRate = config.mockHitRate === undefined ? 0.4 : config.mockHitRate;

    function tick() {
      var user = pick(NAMES);
      var text;

      // Играта подава кои думи още се търсят, за да има какво да се познае.
      var available = config.mockWords ? config.mockWords() : [];

      if (available.length && Math.random() < hitRate) {
        var word = pick(available);
        // Част от зрителите пишат на шльокавица - точно тях трябва да
        // ловим, значи точно тях трябва да упражняваме.
        if (Math.random() < 0.45 && root.Dumichki.Shlyokavitsa) {
          var forms = root.Dumichki.Shlyokavitsa.expand(word);
          text = pick(forms);
        } else {
          text = Math.random() < 0.2 ? word.toUpperCase() : word;
        }
        if (Math.random() < 0.25) { text += pick(["!", "!!", " 🔥", "?", " ..."]); }
      } else {
        text = pick(NOISE);
      }

      deliver({
        user: user,
        userId: "mock:" + user,
        message: text,
        id: "mock:" + Date.now() + ":" + Math.random(),
        timestamp: Date.now()
      });

      timer = setTimeout(tick, minGap + Math.random() * (maxGap - minGap));
    }

    timer = setTimeout(tick, 400);
  }

  function stop() {
    clearTimeout(timer);
    timer = null;
  }

  root.Dumichki.Chat.register("mock", {
    label: "мним чат",
    start: start,
    stop: stop
  });
})(typeof globalThis !== "undefined" ? globalThis : this);
