/* Звукът.
 *
 * Играта не знае какво свири - вика play("word") и толкова. Файловете са в
 * game/audio/ и се сменят със свои, стига имената да са същите.
 *
 * Височината при поредица се качва чрез скоростта на пускане, за да е един
 * файл, а не дванайсет.
 */
(function (root) {
  "use strict";

  function Sounds(config) {
    this.cfg = config.audio;
    this.enabled = this.cfg.enabled;
    this.pool = {};
    this.missing = {};
  }

  /* Включва или изключва звука. Връща новото състояние. */
  Sounds.prototype.setEnabled = function (on) {
    this.enabled = !!on;
    if (!this.enabled) {
      // Спираме и това, което свири в момента - иначе последният звук
      // доиграва след натискането и изглежда, че бутонът не работи.
      var self = this;
      Object.keys(this.pool).forEach(function (name) {
        self.pool[name].items.forEach(function (audio) {
          try {
            audio.pause();
            audio.currentTime = 0;
          } catch (err) { /* тихо */ }
        });
      });
    }
    return this.enabled;
  };

  Sounds.prototype.load = function (names) {
    var self = this;
    names.forEach(function (name) {
      // По няколко копия от звук, който може да се застъпи със себе си -
      // иначе втората дума прекъсва първата.
      var copies = (name === "word" || name === "countdown") ? 4 : 2;
      self.pool[name] = { index: 0, items: [] };
      for (var i = 0; i < copies; i++) {
        var audio = new Audio(self.cfg.folder + name + ".wav");
        audio.preload = "auto";
        audio.volume = self.cfg.volume;
        self.pool[name].items.push(audio);
      }
    });
    return this;
  };

  /*
   * Пуска звук. `rate` над 1 го качва по височина.
   *
   * Пропадането е тихо нарочно: липсващ звук не бива да спира играта, а
   * браузърите отказват да свирят, докато няма взаимодействие с
   * страницата - в OBS това се случва само̀, но не веднага.
   */
  Sounds.prototype.play = function (name, rate) {
    if (!this.enabled) { return; }
    var slot = this.pool[name];
    if (!slot) {
      if (!this.missing[name]) {
        this.missing[name] = true;
        console.warn("[звук] няма зареден '" + name + "'");
      }
      return;
    }

    var audio = slot.items[slot.index];
    slot.index = (slot.index + 1) % slot.items.length;

    try {
      audio.currentTime = 0;
      audio.playbackRate = rate || 1;
      audio.volume = this.cfg.volume;
      var promise = audio.play();
      if (promise && promise.catch) { promise.catch(function () {}); }
    } catch (err) {
      /* тихо */
    }
  };

  /* Звукът на позната дума, качен според дължината на поредицата. */
  Sounds.prototype.playWord = function (streak) {
    var rate = Math.min(
      this.cfg.pitchMax,
      1 + Math.max(0, streak - 1) * this.cfg.pitchStep
    );
    this.play("word", rate);
  };

  root.Dumichki.Sounds = Sounds;
})(typeof globalThis !== "undefined" ? globalThis : this);
