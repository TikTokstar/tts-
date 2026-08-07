/* Игровият екран.
 *
 * Слуша събитията на играта и рисува. Не знае нищо за чата, за речника и за
 * точкуването - само какво се е случило и как да изглежда.
 *
 * Половината от играта е усещането при познаване, затова анимацията на
 * буквите не е украса, а основна работа тук.
 */
(function (root) {
  "use strict";

  var LETTER_STAGGER = 70;   // ms между две излитащи букви
  var FLIGHT_MS = 430;
  var BOUNCE = "cubic-bezier(0.34, 1.45, 0.5, 1)";

  function el(id) { return document.getElementById(id); }

  var escapeHtml = root.Dumichki.escapeHtml;

  function Overlay(game, config, sounds) {
    this.game = game;
    this.cfg = config;
    this.sounds = sounds;
    this.scale = 1;

    this.stage = el("stage");
    this.words = new Map();    // дума → { el, boxes }
    this.tiles = [];
    this.lastStreak = 0;
    this.lastSeconds = -1;
    this.lastPoints = -1;

    this.applyTheme();
    this.fit();

    var self = this;
    window.addEventListener("resize", function () { self.fit(); });
  }

  /* Цветовете и шрифтът идват от config.js, не са заковани в CSS. */
  Overlay.prototype.applyTheme = function () {
    var t = this.cfg.theme;
    var css = this.stage.style;
    css.setProperty("--bg", t.background);
    css.setProperty("--bg-glow", t.backgroundGlow);
    css.setProperty("--text", t.text);
    css.setProperty("--dim", t.dim);
    css.setProperty("--accent", t.accent);
    css.setProperty("--accent-soft", t.accentSoft);
    css.setProperty("--success", t.success);
    css.setProperty("--hot", t.hot);
    css.setProperty("--slot", t.slot);
    css.setProperty("--slot-edge", t.slotEdge);
    css.setProperty("--panel", t.panel);
    css.setProperty("--font", t.font);

    if (this.cfg.showSafeArea) { el("safe-area").classList.add("on"); }
  };

  /*
   * В OBS browser source-ът е точно 1080x1920 и мащабът е 1. Това тук е за
   * да се гледа и в обикновен прозорец, без да се разваля оформлението.
   */
  Overlay.prototype.fit = function () {
    this.scale = Math.min(window.innerWidth / 1080, window.innerHeight / 1920);

    // Центрираме останалото място. В OBS мащабът е 1 и отместването е 0;
    // в обикновен прозорец играта стои в средата, а не залепена вляво с
    // черна ивица отдясно, която изглежда като счупено.
    var x = Math.round((window.innerWidth - 1080 * this.scale) / 2);
    var y = Math.round((window.innerHeight - 1920 * this.scale) / 2);

    var transform = "translate(" + x + "px, " + y + "px) scale(" + this.scale + ")";
    this.stage.style.setProperty("--stage-scale", transform);
    this.stage.style.transform = transform;
  };

  /* Правоъгълникът на елемент в координатите на сцената, не на екрана. */
  Overlay.prototype.rectOf = function (node) {
    var stage = this.stage.getBoundingClientRect();
    var r = node.getBoundingClientRect();
    return {
      x: (r.left - stage.left) / this.scale,
      y: (r.top - stage.top) / this.scale,
      w: r.width / this.scale,
      h: r.height / this.scale
    };
  };

  // --- Свързване с играта ---------------------------------------------------

  Overlay.prototype.bind = function () {
    var self = this;
    var game = this.game;

    game.on("level:start", function (e) { self.onLevelStart(e); });
    game.on("round:start", function (e) { self.onRoundStart(e); });
    game.on("round:end", function (e) { self.onRoundEnd(e); });
    game.on("found", function (e) { self.onFound(e); });
    game.on("hint", function (e) { self.onHint(e); });
    game.on("shuffle", function (e) { self.onShuffle(e); });
    game.on("tick", function (e) { self.onTick(e); });
    game.on("streak:reset", function () { self.setStreak(0); });

    return this;
  };

  Overlay.prototype.onLevelStart = function (e) {
    el("level-name").textContent = "НИВО " + e.level;
    el("intermission").classList.remove("on");
  };

  Overlay.prototype.onRoundStart = function (e) {
    this.drawStack(e.round.letters);
    this.drawSlots(e.round.targets);
    this.drawTicker();
    this.drawBoard();
    this.setStreak(0);
  };

  Overlay.prototype.onRoundEnd = function (e) {
    var self = this;
    // Показваме какво никой не позна - зрителят си тръгва с отговора.
    e.missed.forEach(function (word) {
      var entry = self.words.get(word);
      if (!entry) { return; }
      for (var i = 0; i < word.length; i++) {
        entry.boxes[i].textContent = word.charAt(i).toUpperCase();
        entry.boxes[i].classList.remove("hinted");
        entry.boxes[i].classList.add("missed");
      }
    });

    this.sounds.play(e.reason === "complete" ? "round-clear" : "round-end");
    this.setStreak(0);
  };

  /*
   * Часовникът бие десет пъти в секунда, но екранът се мени най-много
   * веднъж. Пишем в DOM само при истинска промяна - иначе overlay-ът
   * прави десет излишни пренареждания в секунда с часове наред.
   */
  Overlay.prototype.onTick = function (e) {
    var seconds = Math.ceil(e.timeLeft);
    if (seconds !== this.lastSeconds) {
      this.lastSeconds = seconds;
      var timer = el("timer");
      timer.textContent = Math.floor(seconds / 60) + ":" +
        ("0" + (seconds % 60)).slice(-2);
      timer.classList.toggle("low", seconds <= 10);
    }

    var points = Math.round(e.levelPoints);
    if (points !== this.lastPoints) {
      this.lastPoints = points;
      el("progress-fill").style.width = (e.progress * 100).toFixed(1) + "%";
      el("progress-label").textContent =
        points + " / " + e.threshold + " точки до следващо ниво";
    }
  };

  // --- Стойката -------------------------------------------------------------

  Overlay.prototype.drawStack = function (letters) {
    var stack = el("stack");
    stack.innerHTML = "";
    this.tiles = letters.map(function (letter) {
      var tile = document.createElement("div");
      tile.className = "tile";
      tile.textContent = letter.toUpperCase();
      tile.dataset.letter = letter;
      stack.appendChild(tile);
      return tile;
    });
  };

  /*
   * Разбъркването е FLIP: запомняме къде са плочките, пренареждаме ги в DOM,
   * връщаме ги наглед по старите места и ги пускаме да се плъзнат.
   */
  Overlay.prototype.onShuffle = function (e) {
    var self = this;
    var stack = el("stack");
    var before = this.tiles.map(function (tile) {
      return tile.getBoundingClientRect().left;
    });

    // Подреждаме съществуващите плочки по новия ред на буквите.
    var pool = this.tiles.slice();
    var reordered = e.letters.map(function (letter) {
      for (var i = 0; i < pool.length; i++) {
        if (pool[i].dataset.letter === letter) { return pool.splice(i, 1)[0]; }
      }
      return pool.shift();
    });

    var oldLeft = new Map();
    this.tiles.forEach(function (tile, i) { oldLeft.set(tile, before[i]); });

    reordered.forEach(function (tile) { stack.appendChild(tile); });
    this.tiles = reordered;

    reordered.forEach(function (tile) {
      var delta = oldLeft.get(tile) - tile.getBoundingClientRect().left;
      if (!delta) { return; }
      tile.style.transition = "none";
      tile.style.transform = "translateX(" + (delta / self.scale) + "px)";
    });

    // Един кадър по-късно махаме преместването и CSS ги анимира обратно.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        reordered.forEach(function (tile) {
          tile.style.transition = "";
          tile.style.transform = "";
        });
      });
    });

    this.sounds.play("shuffle");
  };

  // --- Слотовете ------------------------------------------------------------

  Overlay.prototype.drawSlots = function (targets) {
    var slots = el("slots");
    slots.innerHTML = "";
    this.words.clear();

    var byLength = new Map();
    targets.forEach(function (word) {
      if (!byLength.has(word.length)) { byLength.set(word.length, []); }
      byLength.get(word.length).push(word);
    });

    var lengths = Array.from(byLength.keys()).sort(function (a, b) { return a - b; });
    var self = this;

    lengths.forEach(function (length) {
      var group = document.createElement("div");
      group.className = "group";

      var label = document.createElement("div");
      label.className = "group-label";
      label.textContent = length + " букви";
      group.appendChild(label);

      var holder = document.createElement("div");
      holder.className = "group-words";

      byLength.get(length).forEach(function (word) {
        var wordEl = document.createElement("div");
        wordEl.className = "word";
        wordEl.dataset.word = word;
        var boxes = [];
        for (var i = 0; i < word.length; i++) {
          var box = document.createElement("div");
          box.className = "box";
          wordEl.appendChild(box);
          boxes.push(box);
        }
        holder.appendChild(wordEl);
        self.words.set(word, { el: wordEl, boxes: boxes });
      });

      group.appendChild(holder);
      slots.appendChild(group);
    });
  };

  Overlay.prototype.onHint = function (e) {
    var entry = this.words.get(e.word);
    if (!entry) { return; }
    for (var i = 0; i < e.revealed && i < entry.boxes.length; i++) {
      entry.boxes[i].textContent = e.word.charAt(i).toUpperCase();
      entry.boxes[i].classList.add("hinted");
    }
    this.sounds.play("hint");
  };

  // --- Познаване ------------------------------------------------------------

  Overlay.prototype.onFound = function (e) {
    var entry = this.words.get(e.word);
    if (!entry) { return; }

    this.flyLetters(e.word, entry);
    this.showOwner(entry, e.user);
    this.setStreak(e.streak);
    this.sounds.playWord(e.streak);
    this.drawTicker();
    this.drawBoard();

    // Дългите думи са събитие - екранът да го усети.
    if (e.word.length >= 6) {
      var stage = this.stage;
      stage.classList.remove("shake");
      void stage.offsetWidth;   // рестартира анимацията
      stage.classList.add("shake");
      setTimeout(function () { stage.classList.remove("shake"); }, 450);
    }
  };

  /*
   * Буквите излитат от стойката и се приземяват в слота една по една.
   *
   * Всяка тръгва от истинската плочка със същата буква, а не от произволна -
   * иначе окото го хваща веднага.
   */
  Overlay.prototype.flyLetters = function (word, entry) {
    var self = this;
    var layer = el("flyers");
    var used = [];

    for (var i = 0; i < word.length; i++) {
      (function (index) {
        var letter = word.charAt(index);
        var tile = self.pickTile(letter, used);
        var box = entry.boxes[index];
        var from = tile ? self.rectOf(tile) : self.rectOf(el("stack"));
        var to = self.rectOf(box);

        var flyer = document.createElement("div");
        flyer.className = "flyer";
        flyer.textContent = letter.toUpperCase();
        flyer.style.left = from.x + "px";
        flyer.style.top = from.y + "px";
        flyer.style.width = from.w + "px";
        flyer.style.height = from.h + "px";
        layer.appendChild(flyer);

        var dx = to.x - from.x + (to.w - from.w) / 2;
        var dy = to.y - from.y + (to.h - from.h) / 2;
        var shrink = to.w / from.w;

        if (tile) { tile.classList.add("dimmed"); }

        var animation = flyer.animate([
          { transform: "translate(0px, 0px) scale(1)", opacity: 1 },
          // Средата е повдигната - буквата лети по дъга, не по линия.
          { transform: "translate(" + (dx * 0.5) + "px, " + (dy * 0.5 - 70) +
              "px) scale(" + ((1 + shrink) / 2) + ")", offset: 0.55 },
          { transform: "translate(" + dx + "px, " + dy + "px) scale(" + shrink + ")", opacity: 1 }
        ], {
          duration: FLIGHT_MS,
          delay: index * LETTER_STAGGER,
          easing: BOUNCE,
          fill: "forwards"
        });

        /*
         * Приземяването минава оттук веднъж, без значение кой го извика.
         *
         * Нужно е, защото при скрит source (OBS изключва browser source-а
         * при смяна на сцена) анимациите спират и onfinish не се задейства
         * никога - буквите увисват в слоя, а слотът остава празен.
         */
        var landed = false;
        function land() {
          if (landed) { return; }
          landed = true;
          flyer.remove();
          box.textContent = letter.toUpperCase();
          box.classList.remove("hinted");
          box.classList.add("filled", "pop");
          setTimeout(function () { box.classList.remove("pop"); }, 430);
          if (tile) { tile.classList.remove("dimmed"); }
        }

        animation.onfinish = land;
        setTimeout(land, FLIGHT_MS + index * LETTER_STAGGER + 600);
      })(i);
    }
  };

  /* Плочка с тази буква, която още не е ползвана в текущия полет. */
  Overlay.prototype.pickTile = function (letter, used) {
    for (var i = 0; i < this.tiles.length; i++) {
      if (used.indexOf(i) === -1 && this.tiles[i].dataset.letter === letter) {
        used.push(i);
        return this.tiles[i];
      }
    }
    return null;
  };

  Overlay.prototype.showOwner = function (entry, user) {
    var badge = document.createElement("div");
    badge.className = "word-owner";
    badge.textContent = user;
    entry.el.appendChild(badge);
    setTimeout(function () { badge.remove(); }, 3000);
  };

  Overlay.prototype.setStreak = function (streak) {
    var box = el("streak");
    el("streak-count").textContent = streak;
    box.classList.toggle("on", streak >= 2);

    if (streak > this.lastStreak && streak >= 2) {
      box.classList.remove("bump");
      void box.offsetWidth;
      box.classList.add("bump");
    }
    this.lastStreak = streak;
  };

  // --- Лента и класация ------------------------------------------------------

  /*
   * Имената идват от чата, тоест от непознат човек в интернет. Всичко,
   * което влиза в HTML, минава през escapeHtml - зрител с име
   * <img src=x onerror=...> няма да пусне код в overlay-а.
   */
  Overlay.prototype.drawTicker = function () {
    el("ticker").innerHTML = this.game.ticker.map(function (item) {
      return '<div class="ticker-item"><b>' + escapeHtml(item.word) +
        '</b><span>' + escapeHtml(item.user) + "</span></div>";
    }).join("");
  };

  Overlay.prototype.drawBoard = function () {
    var rows = this.game.totalBoard.top(this.cfg.board.inGame);
    var body = rows.map(function (row) {
      return '<div class="board-row"><span class="pos">' + row.rank +
        '.</span><span class="who">' + escapeHtml(row.user) +
        '</span><span class="pts">' + row.points + "</span></div>";
    }).join("");

    el("board-content").innerHTML = body ||
      '<div class="board-row"><span class="who">пиши в чата, за да влезеш</span></div>';
  };

  root.Dumichki.Overlay = Overlay;
})(typeof globalThis !== "undefined" ? globalThis : this);
