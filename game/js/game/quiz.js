/* "Стани богат" - викторина, в която чатът гласува.
 *
 * Зрителят пише 1, 2, 3 или 4 в чата. Мнозинството решава. Верен отговор
 * качва по стълбата, грешен слага край на играта.
 *
 * Освен колективния резултат всеки зрител си трупа лични точки за верните
 * си гласове - иначе мълчаливото мнозинство няма причина да участва.
 *
 * Като ядрото на Думички, тук няма нищо визуално. Интерфейсът само слуша.
 */
(function (root) {
  "use strict";

  var Leaderboard = root.Dumichki.Leaderboard;
  var TICK_MS = 100;

  // Класическата стълба. Празните места между тях са само за напрежение -
  // важните са застраховките.
  var LADDER = [
    100, 200, 300, 500, 1000,
    2000, 4000, 8000, 16000, 32000,
    64000, 125000, 250000, 500000, 1000000
  ];

  // След тези стъпала загубата не сваля до нула.
  var SAFE = [4, 9];

  function Quiz(questions, config) {
    this.all = questions;
    this.cfg = config;
    this.handlers = {};

    this.phase = "idle";     // idle | asking | revealing | over
    this.step = 0;           // докъде сме по стълбата
    this.question = null;
    this.order = [];         // разбъркан ред на отговорите за текущия въпрос
    this.votes = new Map();  // зрител → индекс на отговора
    this.removed = [];       // махнатите от 50:50
    this.fiftyUsed = false;
    this.fiftyCalls = new Set();
    this.used = { 1: [], 2: [], 3: [] };

    this.board = new Leaderboard();
    this.timer = null;
    this.phaseEndsAt = 0;
  }

  // --- Събития --------------------------------------------------------------

  Quiz.prototype.on = function (event, handler) {
    (this.handlers[event] = this.handlers[event] || []).push(handler);
    return this;
  };

  Quiz.prototype.emit = function (event, payload) {
    var list = this.handlers[event] || [];
    for (var i = 0; i < list.length; i++) {
      try {
        list[i](payload);
      } catch (err) {
        console.error("[викторина] грешка при '" + event + "':", err);
      }
    }
  };

  // --- Ход на играта --------------------------------------------------------

  Quiz.prototype.start = function () {
    var self = this;
    this.newGame();
    this.timer = setInterval(function () { self.tick(); }, TICK_MS);
    return this;
  };

  Quiz.prototype.stop = function () {
    clearInterval(this.timer);
    this.timer = null;
    this.phase = "idle";
  };

  Quiz.prototype.newGame = function () {
    this.step = 0;
    this.fiftyUsed = false;
    this.emit("game:start", { ladder: LADDER, safe: SAFE });
    this.ask();
  };

  /*
   * Трудността расте със стъпалото. Въпросите не се повтарят, докато не
   * свършат всички от нивото - иначе на един стрийм се въртят все същите
   * пет въпроса.
   */
  Quiz.prototype.levelFor = function (step) {
    if (step < 5) { return 1; }
    if (step < 10) { return 2; }
    return 3;
  };

  Quiz.prototype.pickQuestion = function (level) {
    var pool = [];
    for (var i = 0; i < this.all.length; i++) {
      if (this.all[i].lvl === level && this.used[level].indexOf(i) === -1) {
        pool.push(i);
      }
    }
    if (!pool.length) {                 // изчерпахме нивото - почваме отначало
      this.used[level] = [];
      for (var j = 0; j < this.all.length; j++) {
        if (this.all[j].lvl === level) { pool.push(j); }
      }
    }
    if (!pool.length) { return null; }

    var index = pool[Math.floor(Math.random() * pool.length)];
    this.used[level].push(index);
    return this.all[index];
  };

  Quiz.prototype.ask = function () {
    var level = this.levelFor(this.step);
    var question = this.pickQuestion(level);
    if (!question) {
      console.error("[викторина] няма въпроси за ниво " + level);
      return;
    }

    this.question = question;
    // Отговорите се разбъркват, за да не е верният винаги на едно място.
    this.order = shuffle([0, 1, 2, 3]);
    this.votes.clear();
    this.removed = [];
    this.fiftyCalls.clear();
    this.phase = "asking";
    this.phaseEndsAt = Date.now() + this.cfg.quiz.answerTime * 1000;

    this.emit("question", {
      step: this.step,
      level: level,
      prize: LADDER[this.step],
      text: question.q,
      answers: this.displayAnswers(),
      seconds: this.cfg.quiz.answerTime
    });
  };

  /* Отговорите в реда, в който се показват на екрана. */
  Quiz.prototype.displayAnswers = function () {
    var self = this;
    return this.order.map(function (original, position) {
      return {
        text: self.question.a[original],
        removed: self.removed.indexOf(position) !== -1
      };
    });
  };

  /* Кой показан отговор е верният. */
  Quiz.prototype.correctPosition = function () {
    return this.order.indexOf(this.question.t);
  };

  Quiz.prototype.reveal = function () {
    if (this.phase !== "asking") { return; }

    var counts = this.tally();
    var correct = this.correctPosition();
    var winner = -1;
    var best = -1;
    for (var i = 0; i < 4; i++) {
      if (counts[i] > best) { best = counts[i]; winner = i; }
    }
    // Без нито един глас мнозинството не съществува - смята се за грешка.
    var chatRight = best > 0 && winner === correct;

    // Личните точки: всеки, който е гласувал вярно, печели според стъпалото.
    var self = this;
    var scorers = [];
    this.votes.forEach(function (choice, user) {
      if (choice === correct) {
        var points = self.cfg.quiz.pointsPerLevel * (self.levelFor(self.step));
        self.board.add(user, points);
        scorers.push(user);
      }
    });

    this.phase = "revealing";
    this.phaseEndsAt = Date.now() + this.cfg.quiz.revealTime * 1000;

    this.emit("reveal", {
      correct: correct,
      chosen: best > 0 ? winner : -1,
      right: chatRight,
      counts: counts,
      votes: this.votes.size,
      scorers: scorers.length,
      prize: LADDER[this.step],
      step: this.step
    });

    this.pendingRight = chatRight;
  };

  Quiz.prototype.advance = function () {
    if (this.pendingRight) {
      this.step++;
      if (this.step >= LADDER.length) {
        this.finish(true);
      } else {
        this.ask();
      }
    } else {
      this.finish(false);
    }
  };

  Quiz.prototype.finish = function (won) {
    var safeStep = -1;
    for (var i = 0; i < SAFE.length; i++) {
      if (this.step > SAFE[i]) { safeStep = SAFE[i]; }
    }

    this.phase = "over";
    this.phaseEndsAt = Date.now() + this.cfg.quiz.summaryTime * 1000;

    this.emit("game:end", {
      won: won,
      step: this.step,
      reached: this.step > 0 ? LADDER[this.step - 1] : 0,
      guaranteed: won ? LADDER[LADDER.length - 1]
        : (safeStep >= 0 ? LADDER[safeStep] : 0),
      top: this.board.top(this.cfg.board.intermission),
      seconds: this.cfg.quiz.summaryTime
    });
  };

  // --- Часовникът -----------------------------------------------------------

  Quiz.prototype.tick = function () {
    var now = Date.now();
    var left = Math.max(0, (this.phaseEndsAt - now) / 1000);

    if (this.phase === "asking") {
      this.emit("tick", {
        timeLeft: left,
        total: this.cfg.quiz.answerTime,
        counts: this.tally(),
        votes: this.votes.size
      });
      if (left <= 0) { this.reveal(); }

    } else if (this.phase === "revealing") {
      if (left <= 0) { this.advance(); }

    } else if (this.phase === "over") {
      this.emit("summary:tick", { secondsLeft: left });
      if (left <= 0) { this.newGame(); }
    }
  };

  // --- Чатът ----------------------------------------------------------------

  /*
   * Гласуване. Приема "2", "б", "B", "отговор 3" и подобни, но нарочно е
   * строго: съобщението трябва да е самият глас, не изречение, в което се
   * среща цифра. Иначе "имам 2 идеи" става глас.
   */
  Quiz.prototype.handleChat = function (event) {
    if (this.phase !== "asking") { return null; }

    var key = event.userId || event.user;
    var text = String(event.message || "")
      .toLowerCase()
      .replace(/^\s*@\S+\s*/g, "")
      .replace(/^(отговор|отг|answer)\s*/, "")
      .replace(/[^0-9a-zа-я]/g, "");

    // Повикване на 50:50 от чата.
    if (text === "5050" || text === "50") {
      if (!this.fiftyUsed) {
        this.fiftyCalls.add(key);
        this.emit("fifty:progress", {
          calls: this.fiftyCalls.size,
          needed: this.cfg.quiz.fiftyVotes
        });
        if (this.fiftyCalls.size >= this.cfg.quiz.fiftyVotes) { this.useFifty(); }
      }
      return null;
    }

    var choice = VOTE_TOKENS[text];
    if (choice === undefined) { return null; }
    if (this.removed.indexOf(choice) !== -1) { return null; }

    // Промяна на мнението се позволява, докато тече времето - едно гласуване
    // на човек, но последното брои.
    var changed = this.votes.get(key) !== choice;
    this.votes.set(key, choice);

    if (changed) {
      this.emit("vote", {
        user: event.user,
        choice: choice,
        counts: this.tally(),
        votes: this.votes.size
      });
    }
    return choice;
  };

  Quiz.prototype.tally = function () {
    var counts = [0, 0, 0, 0];
    this.votes.forEach(function (choice) { counts[choice]++; });
    return counts;
  };

  /* Маха два грешни отговора. */
  Quiz.prototype.useFifty = function () {
    if (this.fiftyUsed || this.phase !== "asking") { return; }
    this.fiftyUsed = true;

    var correct = this.correctPosition();
    var wrong = [];
    for (var i = 0; i < 4; i++) {
      if (i !== correct) { wrong.push(i); }
    }
    wrong = shuffle(wrong).slice(0, 2);
    this.removed = wrong;

    // Гласовете за махнатите отпадат - иначе човек остава с мъртъв глас.
    var self = this;
    var dropped = [];
    this.votes.forEach(function (choice, user) {
      if (wrong.indexOf(choice) !== -1) { dropped.push(user); }
    });
    dropped.forEach(function (user) { self.votes.delete(user); });

    this.emit("fifty", {
      removed: wrong,
      answers: this.displayAnswers(),
      counts: this.tally()
    });
  };

  function shuffle(array) {
    var out = array.slice();
    for (var i = out.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = out[i];
      out[i] = out[j];
      out[j] = tmp;
    }
    return out;
  }

  // Какво се брои за глас. Цифри, български и латински букви - зрителите
  // пишат каквото им е под ръка.
  var VOTE_TOKENS = {
    "1": 0, "2": 1, "3": 2, "4": 3,
    "а": 0, "б": 1, "в": 2, "г": 3,
    "a": 0, "b": 1, "c": 2, "d": 3
  };

  root.Dumichki.Quiz = Quiz;
  root.Dumichki.Quiz.LADDER = LADDER;
  root.Dumichki.Quiz.SAFE = SAFE;
  root.Dumichki.Quiz.VOTE_TOKENS = VOTE_TOKENS;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = Quiz;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
