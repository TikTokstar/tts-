/* Играта - всичко, което се случва, без нищо, което се вижда.
 *
 * Държи рундовете, точките, нивата и двете класации, и обявява какво става
 * със събития. Интерфейсът само слуша и рисува. Затова логиката се
 * проверява без браузър, а визията се сменя, без да се пипа логиката.
 */
(function (root) {
  "use strict";

  var Round = root.Dumichki.Round;
  var Leaderboard = root.Dumichki.Leaderboard;

  var TICK_MS = 100;

  function Game(dict, config) {
    this.dict = dict;
    this.cfg = config;
    this.handlers = {};

    this.phase = "idle";       // idle | playing | between | intermission
    this.level = 0;
    this.levelPoints = 0;
    this.threshold = 0;
    this.round = null;

    this.streak = 0;
    this.bestStreak = 0;
    this.lastFindAt = 0;
    this.cooldowns = new Map();
    this.hints = new Map();     // дума → колко букви са разкрити
    this.ticker = [];

    this.levelBoard = new Leaderboard();
    this.totalBoard = new Leaderboard();
    this.previousRanks = new Map();

    this.timer = null;
    this.phaseEndsAt = 0;
    this.roundStartedAt = 0;
    this.nextShuffleAt = 0;
    this.nextSweepAt = 0;
  }

  // Изтекли cooldown-и се чистят веднъж на толкова. Без това речникът расте
  // с всеки нов зрител и за няколко часа стрийм става десетки хиляди записа,
  // от които почти всички са отдавна изтекли.
  var COOLDOWN_SWEEP_MS = 60000;

  // --- Събития --------------------------------------------------------------

  Game.prototype.on = function (event, handler) {
    (this.handlers[event] = this.handlers[event] || []).push(handler);
    return this;
  };

  Game.prototype.emit = function (event, payload) {
    var list = this.handlers[event] || [];
    for (var i = 0; i < list.length; i++) {
      try {
        list[i](payload);
      } catch (err) {
        console.error("[игра] грешка при '" + event + "':", err);
      }
    }
  };

  // --- Ход на играта --------------------------------------------------------

  Game.prototype.start = function () {
    var self = this;
    this.startLevel(1);
    this.timer = setInterval(function () { self.tick(); }, TICK_MS);
    return this;
  };

  Game.prototype.stop = function () {
    clearInterval(this.timer);
    this.timer = null;
    this.phase = "idle";
  };

  Game.prototype.startLevel = function (level) {
    this.level = level;
    this.levelPoints = 0;
    this.threshold = this.cfg.level.baseThreshold +
      (level - 1) * this.cfg.level.thresholdGrowth;
    this.levelBoard.reset();

    this.emit("level:start", { level: level, threshold: this.threshold });
    this.startRound();
  };

  Game.prototype.startRound = function () {
    var round = Round.createRound(this.dict, this.cfg.stack);
    if (!round) {
      console.error("[игра] не се получи стойка - проверявам пак");
      var self = this;
      setTimeout(function () { self.startRound(); }, 500);
      return;
    }

    this.round = round;
    this.hints.clear();
    this.phase = "playing";

    var now = Date.now();
    this.roundStartedAt = now;
    this.phaseEndsAt = now + this.cfg.round.duration * 1000;
    this.lastFindAt = now;
    this.nextShuffleAt = now + this.cfg.round.shuffleEvery * 1000;

    this.emit("round:start", { round: round, level: this.level });
  };

  Game.prototype.endRound = function (reason) {
    if (this.phase !== "playing") { return; }

    var missed = Round.remaining(this.round);
    this.phase = "between";
    this.phaseEndsAt = Date.now() + this.cfg.round.gap * 1000;
    this.streak = 0;

    this.emit("round:end", { reason: reason, missed: missed, round: this.round });
  };

  /*
   * Краят на нивото е моментът, заради който зрителят остава още едно ниво.
   * Тук се снима кой къде е бил, за да излязат стрелките в паузата.
   */
  Game.prototype.endLevel = function () {
    var count = this.cfg.board.intermission;
    var currentRanks = this.totalBoard.ranks();
    var previous = this.previousRanks;
    // При първото ниво всички са нови - пет пъти "нов" не казва нищо.
    var showMovement = previous.size > 0;

    var totalTop = this.totalBoard.top(count).map(function (row) {
      var was = previous.get(row.user);
      return {
        user: row.user,
        points: row.points,
        rank: row.rank,
        moved: was === undefined ? null : was - row.rank,
        isNew: was === undefined
      };
    });

    this.previousRanks = currentRanks;
    this.phase = "intermission";
    this.phaseEndsAt = Date.now() + this.cfg.level.intermission * 1000;

    this.emit("level:end", {
      level: this.level,
      levelTop: this.levelBoard.top(count),
      totalTop: totalTop,
      showMovement: showMovement,
      nextLevel: this.level + 1,
      seconds: this.cfg.level.intermission
    });
  };

  // --- Часовникът -----------------------------------------------------------

  Game.prototype.tick = function () {
    var now = Date.now();

    if (now >= this.nextSweepAt) {
      this.nextSweepAt = now + COOLDOWN_SWEEP_MS;
      this.sweepCooldowns(now);
    }

    if (this.phase === "playing") {
      // Поредицата пада, ако дълго няма нов успех - иначе множителят
      // остава качен през цялото затишие.
      if (this.streak > 0 &&
          now - this.lastFindAt > this.cfg.scoring.streakTimeout * 1000) {
        this.streak = 0;
        this.emit("streak:reset", {});
      }

      if (now >= this.nextShuffleAt) {
        this.nextShuffleAt = now + this.cfg.round.shuffleEvery * 1000;
        this.round.letters = shuffleLetters(this.round.letters);
        this.emit("shuffle", { letters: this.round.letters });
      }

      if (now - this.lastFindAt > this.cfg.round.hintAfter * 1000) {
        this.giveHint();
      }

      if (now >= this.phaseEndsAt) {
        this.endRound("time");
      }

      this.emit("tick", {
        timeLeft: Math.max(0, (this.phaseEndsAt - now) / 1000),
        duration: this.cfg.round.duration,
        levelPoints: this.levelPoints,
        threshold: this.threshold,
        progress: Math.min(1, this.levelPoints / this.threshold),
        streak: this.streak
      });

    } else if (this.phase === "between") {
      if (now >= this.phaseEndsAt) {
        if (this.levelPoints >= this.threshold) {
          this.endLevel();
        } else {
          this.startRound();
        }
      }

    } else if (this.phase === "intermission") {
      var left = Math.max(0, (this.phaseEndsAt - now) / 1000);
      this.emit("intermission:tick", { secondsLeft: left });
      if (left <= 0) {
        this.startLevel(this.level + 1);
      }
    }
  };

  /* Изхвърля изтеклите cooldown-и. Стриймът върви с часове. */
  Game.prototype.sweepCooldowns = function (now) {
    var expired = [];
    this.cooldowns.forEach(function (until, key) {
      if (until <= now) { expired.push(key); }
    });
    for (var i = 0; i < expired.length; i++) {
      this.cooldowns.delete(expired[i]);
    }
  };

  /* Разкрива следващата буква на най-късата ненамерена дума. */
  Game.prototype.giveHint = function () {
    var left = Round.remaining(this.round);
    if (!left.length) { return; }

    left.sort(function (a, b) { return a.length - b.length; });
    var word = left[0];
    var revealed = (this.hints.get(word) || 0) + 1;

    // Ако само една буква липсва, това вече е отговорът - не подаряваме.
    if (revealed >= word.length) {
      this.lastFindAt = Date.now();
      return;
    }

    this.hints.set(word, revealed);
    this.lastFindAt = Date.now();
    this.emit("hint", { word: word, revealed: revealed });
  };

  // --- Чатът ----------------------------------------------------------------

  /*
   * Съобщение от зрител. Грешките не се обявяват - тихо, без спам на екрана.
   */
  Game.prototype.handleChat = function (event) {
    if (this.phase !== "playing" || !this.round) { return null; }

    var hit = Round.matchGuess(this.round, event.message);
    if (!hit) { return null; }

    var now = Date.now();
    var key = event.userId || event.user;
    var until = this.cooldowns.get(key) || 0;
    if (now < until) {
      this.emit("cooldown", {
        user: event.user,
        word: hit.word,
        secondsLeft: (until - now) / 1000
      });
      return null;
    }

    Round.reveal(this.round, hit.word, event.user);
    this.cooldowns.set(key, now + this.cfg.chat.cooldown * 1000);

    this.streak++;
    if (this.streak > this.bestStreak) { this.bestStreak = this.streak; }
    this.lastFindAt = now;

    var points = this.scoreFor(hit.word, now);
    this.levelPoints += points;
    this.levelBoard.add(event.user, points);
    this.totalBoard.add(event.user, points);

    this.ticker.unshift({ word: hit.word, user: event.user, at: now });
    this.ticker = this.ticker.slice(0, this.cfg.board.ticker);

    var found = {
      word: hit.word,
      user: event.user,
      spelling: hit.spelling,
      points: points,
      streak: this.streak,
      index: this.round.targets.indexOf(hit.word),
      remaining: Round.remaining(this.round).length
    };
    this.emit("found", found);

    if (Round.isComplete(this.round)) {
      this.endRound("complete");
    } else if (this.levelPoints >= this.threshold) {
      this.endRound("level");
    }

    return found;
  };

  Game.prototype.scoreFor = function (word, now) {
    var s = this.cfg.scoring;
    var points = word.length * s.pointsPerLetter;

    if (now - this.roundStartedAt < s.speedWindow * 1000) {
      points *= s.speedBonus;
    }

    var multiplier = Math.min(s.streakMax, 1 + (this.streak - 1) * s.streakStep);
    return Math.round(points * multiplier);
  };

  /* Кои думи още се търсят - ползва се от мнимия чат. */
  Game.prototype.remaining = function () {
    return this.round && this.phase === "playing" ? Round.remaining(this.round) : [];
  };

  Game.prototype.hintFor = function (word) {
    return this.hints.get(word) || 0;
  };

  function shuffleLetters(letters) {
    var out = letters.slice();
    for (var i = out.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = out[i];
      out[i] = out[j];
      out[j] = tmp;
    }
    // Едно и също подреждане два пъти подред изглежда като счупена анимация.
    if (out.join("") === letters.join("") && letters.length > 1) {
      out.push(out.shift());
    }
    return out;
  }

  root.Dumichki.Game = Game;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = Game;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
