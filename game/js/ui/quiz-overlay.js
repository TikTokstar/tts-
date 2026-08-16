/* Екранът на "Стани богат".
 *
 * Слуша викторината и рисува. Не знае нищо за чата и за въпросите - само
 * какво се е случило.
 */
(function (root) {
  "use strict";

  var escapeHtml = root.Dumichki.escapeHtml;

  function el(id) { return document.getElementById(id); }

  function withAlpha(hex, alpha) {
    var value = String(hex).replace("#", "");
    if (value.length === 3) {
      value = value[0] + value[0] + value[1] + value[1] + value[2] + value[2];
    }
    if (value.length !== 6) { return hex; }
    return "rgba(" + parseInt(value.slice(0, 2), 16) + ", " +
      parseInt(value.slice(2, 4), 16) + ", " +
      parseInt(value.slice(4, 6), 16) + ", " + alpha + ")";
  }

  function QuizOverlay(quiz, config, sounds) {
    this.quiz = quiz;
    this.cfg = config;
    this.sounds = sounds;

    var layout = config.layout || {};
    this.width = layout.width || 1080;
    this.height = layout.height || 480;

    this.stage = el("stage");
    this.stage.classList.add("quiz");
    this.stage.style.width = this.width + "px";
    this.stage.style.height = this.height + "px";

    this.answers = [];
    this.lastSecond = -1;

    this.applyTheme();
    this.fit();

    var self = this;
    window.addEventListener("resize", function () { self.fit(); });
  }

  QuizOverlay.prototype.applyTheme = function () {
    var t = this.cfg.theme;
    var css = this.stage.style;
    var map = {
      "--bg": t.background, "--bg-glow": t.backgroundGlow, "--text": t.text,
      "--dim": t.dim, "--accent": t.accent, "--accent-soft": t.accentSoft,
      "--success": t.success, "--hot": t.hot, "--slot": t.slot,
      "--slot-edge": t.slotEdge, "--panel": t.panel, "--font": t.font
    };
    Object.keys(map).forEach(function (key) { css.setProperty(key, map[key]); });

    var backdrop = this.cfg.layout && this.cfg.layout.backdrop;
    css.setProperty("--stage-bg",
      withAlpha(t.background, backdrop === undefined ? 0.82 : backdrop));
  };

  QuizOverlay.prototype.fit = function () {
    var scale = Math.min(window.innerWidth / this.width,
                         window.innerHeight / this.height);
    var x = Math.round((window.innerWidth - this.width * scale) / 2);
    var y = Math.round((window.innerHeight - this.height * scale) / 2);
    var transform = "translate(" + x + "px, " + y + "px) scale(" + scale + ")";
    this.stage.style.setProperty("--stage-scale", transform);
    this.stage.style.transform = transform;
  };

  // --- Свързване ------------------------------------------------------------

  QuizOverlay.prototype.bind = function () {
    var self = this;
    this.quiz.on("game:start", function () { el("q-end").classList.remove("on"); });
    this.quiz.on("question", function (e) { self.onQuestion(e); });
    this.quiz.on("tick", function (e) { self.onTick(e); });
    this.quiz.on("vote", function (e) { self.onVote(e); });
    this.quiz.on("fifty", function (e) { self.onFifty(e); });
    this.quiz.on("fifty:progress", function (e) { self.onFiftyProgress(e); });
    this.quiz.on("reveal", function (e) { self.onReveal(e); });
    this.quiz.on("game:end", function (e) { self.onEnd(e); });
    this.quiz.on("summary:tick", function (e) {
      el("q-end-seconds").textContent = Math.ceil(e.secondsLeft);
    });
    return this;
  };

  QuizOverlay.prototype.onQuestion = function (e) {
    el("q-end").classList.remove("on");
    el("q-step").textContent = "ВЪПРОС " + (e.step + 1) + "/15";
    el("q-prize").textContent = formatPrize(e.prize) + " лв.";
    el("q-text").textContent = e.text;
    el("q-fifty").classList.remove("on");
    var hint = el("q-hint");
    hint.className = "";
    hint.textContent = "ПИШИ 1 2 3 ИЛИ 4";

    var holder = el("q-answers");
    holder.innerHTML = "";
    this.answers = e.answers.map(function (answer, index) {
      var node = document.createElement("div");
      node.className = "answer";
      node.innerHTML =
        '<div class="answer-bar"></div>' +
        '<div class="answer-num">' + (index + 1) + "</div>" +
        '<div class="answer-text">' + escapeHtml(answer.text) + "</div>" +
        '<div class="answer-count">0</div>';
      holder.appendChild(node);
      return {
        node: node,
        bar: node.querySelector(".answer-bar"),
        count: node.querySelector(".answer-count")
      };
    });

    this.lastSecond = -1;
    this.sounds.play("shuffle");
    this.drawBoard();
  };

  QuizOverlay.prototype.onTick = function (e) {
    var seconds = Math.ceil(e.timeLeft);
    if (seconds !== this.lastSecond) {
      this.lastSecond = seconds;
      var timer = el("q-timer");
      timer.textContent = seconds;
      timer.classList.toggle("low", seconds <= 5);
      if (seconds <= 5 && seconds > 0) { this.sounds.play("countdown"); }
    }
    el("q-bar-fill").style.width = (100 * e.timeLeft / e.total).toFixed(1) + "%";
    this.drawVotes(e.counts, e.votes);
  };

  QuizOverlay.prototype.onVote = function (e) {
    this.drawVotes(e.counts, e.votes);
  };

  QuizOverlay.prototype.drawVotes = function (counts, total) {
    el("q-votes").textContent = total + (total === 1 ? " глас" : " гласа");
    var max = Math.max(1, counts[0], counts[1], counts[2], counts[3]);
    for (var i = 0; i < this.answers.length; i++) {
      this.answers[i].count.textContent = counts[i];
      this.answers[i].bar.style.width = (100 * counts[i] / max) + "%";
    }
  };

  QuizOverlay.prototype.onFiftyProgress = function (e) {
    var node = el("q-fifty");
    node.textContent = "50:50 — " + e.calls + "/" + e.needed;
    node.classList.add("on");
  };

  QuizOverlay.prototype.onFifty = function (e) {
    var self = this;
    e.removed.forEach(function (index) {
      self.answers[index].node.classList.add("gone");
    });
    el("q-fifty").textContent = "50:50 ИЗПОЛЗВАНО";
    this.sounds.play("hint");
    this.drawVotes(e.counts, e.counts[0] + e.counts[1] + e.counts[2] + e.counts[3]);
  };

  QuizOverlay.prototype.onReveal = function (e) {
    this.answers[e.correct].node.classList.add("right");
    if (!e.right && e.chosen >= 0) {
      this.answers[e.chosen].node.classList.add("wrong");
      this.shake();
    }
    var hint = el("q-hint");
    hint.className = e.right ? "ok" : "bad";
    hint.textContent = e.right
      ? "ВЯРНО — " + e.scorers + (e.scorers === 1 ? " познал" : " познали")
      : (e.chosen < 0 ? "НИКОЙ НЕ ГЛАСУВА" : "ГРЕШКА");
    this.sounds.play(e.right ? "round-clear" : "round-end");
    this.drawBoard();
  };

  QuizOverlay.prototype.onEnd = function (e) {
    var title = el("q-end-title");
    title.textContent = e.won ? "ЧАТЪТ ПЕЧЕЛИ ВСИЧКО" :
      (e.step === 0 ? "КРАЙ ОЩЕ НА ПЪРВИЯ" : "КРАЙ");
    title.className = e.won ? "won" : "lost";

    el("q-end-prize").textContent = formatPrize(e.guaranteed) + " лв.";
    el("q-end-board").innerHTML = e.top.map(function (row) {
      return '<div class="row"><span class="pos" data-rank="' + row.rank +
        '">' + row.rank + '</span>' +
        "<span>" + escapeHtml(row.user) + '</span><span class="pts">' +
        row.points + "</span></div>";
    }).join("") || '<div class="row">никой не гласува</div>';

    el("q-end").classList.add("on");
    this.sounds.play(e.won ? "level-up" : "round-end");
    if (!e.won) { this.shake(); }
  };

  QuizOverlay.prototype.drawBoard = function () {
    var rows = this.quiz.board.top(this.cfg.board.inGame);
    el("q-board").innerHTML = rows.map(function (row) {
      return '<div class="row"><span class="pos" data-rank="' + row.rank +
        '">' + row.rank + '</span>' +
        "<span>" + escapeHtml(row.user) + '</span><span class="pts">' +
        row.points + "</span></div>";
    }).join("");
  };

  QuizOverlay.prototype.shake = function () {
    var stage = this.stage;
    stage.classList.remove("shake");
    void stage.offsetWidth;
    stage.classList.add("shake");
    setTimeout(function () { stage.classList.remove("shake"); }, 450);
  };

  /* 1000000 -> "1 000 000" */
  function formatPrize(value) {
    return String(value).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }

  root.Dumichki.QuizOverlay = QuizOverlay;
})(typeof globalThis !== "undefined" ? globalThis : this);
