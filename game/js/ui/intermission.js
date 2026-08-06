/* Паузата между нивата.
 *
 * Това не е служебен екран. Това е моментът, в който зрителят вижда, че се
 * е класирал, и решава дали да остане за още едно ниво. Затова двете
 * класации се показват пълно, изкачването се обявява със стрелка, и точно
 * тук - и само тук - има конфети.
 */
(function (root) {
  "use strict";

  var COLORS = ["#ffd23f", "#4ade80", "#ff4d6d", "#7aa2ff", "#ffe98a", "#c084fc"];

  function el(id) { return document.getElementById(id); }

  function Intermission(game, config, sounds) {
    this.game = game;
    this.cfg = config;
    this.sounds = sounds;
    this.lastSecond = -1;
  }

  Intermission.prototype.bind = function () {
    var self = this;
    this.game.on("level:end", function (e) { self.show(e); });
    this.game.on("intermission:tick", function (e) { self.tick(e); });
    this.game.on("level:start", function () { self.hide(); });
    return this;
  };

  Intermission.prototype.show = function (e) {
    el("im-level").textContent = "НИВО " + e.level;
    el("im-level-title").textContent = "КЛАСАЦИЯ ЗА НИВО " + e.level;

    el("im-level-rows").innerHTML = this.rows(e.levelTop, false) ||
      '<div class="im-empty">никой не се обади това ниво</div>';
    el("im-total-rows").innerHTML = this.rows(e.totalTop, e.showMovement) ||
      '<div class="im-empty">класацията е празна</div>';

    el("intermission").classList.add("on");
    this.lastSecond = -1;

    this.sounds.play("level-up");
    this.confetti();
  };

  Intermission.prototype.hide = function () {
    el("intermission").classList.remove("on");
    el("confetti").innerHTML = "";
  };

  /*
   * Редовете се появяват един по един отдолу нагоре - от пето към първо
   * място. Дребно, но точно то прави класирането събитие вместо таблица.
   */
  Intermission.prototype.rows = function (list, withMovement) {
    var count = list.length;
    return list.map(function (row, index) {
      var delay = (count - index - 1) * 0.11 + 0.3;
      var move = "";

      if (withMovement) {
        if (row.isNew) {
          move = '<span class="move new">нов</span>';
        } else if (row.moved > 0) {
          move = '<span class="move up">▲ ' + row.moved +
            (row.moved === 1 ? " място" : " места") + "</span>";
        } else {
          move = '<span class="move same">—</span>';
        }
      }

      return '<div class="im-row' + (index === 0 ? " first" : "") +
        '" style="animation-delay:' + delay.toFixed(2) + 's">' +
        '<span class="pos">' + row.rank + '.</span>' +
        '<span class="who">' + root.Dumichki.escapeHtml(row.user) + '</span>' +
        move +
        '<span class="pts">' + row.points + "</span></div>";
    }).join("");
  };

  Intermission.prototype.tick = function (e) {
    var seconds = Math.ceil(e.secondsLeft);
    el("im-seconds").textContent = seconds;

    // Чукането е само в последните пет секунди - иначе е досадно.
    if (seconds !== this.lastSecond) {
      if (seconds <= 5 && seconds > 0) { this.sounds.play("countdown"); }
      this.lastSecond = seconds;
    }
  };

  /* Конфети - само тук, за да не се обезценят. */
  Intermission.prototype.confetti = function () {
    var layer = el("confetti");
    layer.innerHTML = "";

    for (var i = 0; i < 90; i++) {
      var piece = document.createElement("div");
      piece.className = "confetto";
      piece.style.left = (Math.random() * 1080) + "px";
      piece.style.top = "-40px";
      piece.style.background = COLORS[i % COLORS.length];
      layer.appendChild(piece);

      var drift = (Math.random() - 0.5) * 420;
      var spin = 360 + Math.random() * 900;

      piece.animate([
        { transform: "translate(0, 0) rotate(0deg)", opacity: 1 },
        { transform: "translate(" + drift + "px, 1500px) rotate(" + spin + "deg)", opacity: 0.9 }
      ], {
        duration: 2600 + Math.random() * 1800,
        delay: Math.random() * 700,
        easing: "cubic-bezier(0.25, 0.6, 0.5, 1)",
        fill: "forwards"
      });
    }
  };

  root.Dumichki.Intermission = Intermission;
})(typeof globalThis !== "undefined" ? globalThis : this);
