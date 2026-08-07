/* Връзката с чата.
 *
 * Ядрото на играта не знае откъде идват съобщенията. Знае само това:
 *
 *     { user: "Име", userId: "123", message: "текст", timestamp: 1699999999999 }
 *
 * Всичко останало - кой сървър, каква схема, какво става при разпадане на
 * връзката - живее тук. Смяната на източник е един ред в конфигурацията.
 */
(function (root) {
  "use strict";

  var adapters = {};

  /* Регистрира източник. Виж adapter-*.js за трите налични. */
  function register(name, adapter) {
    adapters[name] = adapter;
  }

  var DEFAULTS = {
    source: "tikfinity",
    debug: false,
    // Стриймът върви с часове - връзката ще падне поне веднъж. Изкачването
    // е бързо в началото, защото прекъсване по време на рунд боли.
    reconnectMin: 1000,
    reconnectMax: 15000,
    // Колко msgId-та помним, за да не броим едно съобщение два пъти.
    dedupeSize: 200
  };

  function Chat(config) {
    this.config = Object.assign({}, DEFAULTS, config || {});
    this.adapter = adapters[this.config.source];
    if (!this.adapter) {
      throw new Error("Непознат източник за чат: " + this.config.source +
        ". Налични: " + Object.keys(adapters).join(", "));
    }

    this.handlers = { message: [], status: [] };
    this.socket = null;
    this.stopped = true;
    this.attempt = 0;
    this.timer = null;
    this.recent = [];
    this.recentSet = Object.create(null);
    this.stats = { received: 0, duplicates: 0, connects: 0, lastMessageAt: 0 };
  }

  Chat.prototype.on = function (event, handler) {
    if (this.handlers[event]) { this.handlers[event].push(handler); }
    return this;
  };

  Chat.prototype._emit = function (event, payload) {
    var list = this.handlers[event];
    for (var i = 0; i < list.length; i++) {
      try {
        list[i](payload);
      } catch (err) {
        console.error("[чат] грешка в обработчик на '" + event + "':", err);
      }
    }
  };

  /*
   * Обявява промяна в състоянието.
   *
   * Грешките се пишат в конзолата пестеливо: ако TikFinity не върви, ще се
   * къса на всеки няколко секунди с часове наред, а хиляди еднакви реда не
   * казват нищо повече от първите три - само пречат при търсене на нещо
   * друго. Бележката на екрана и без това стои през цялото време.
   */
  Chat.prototype._status = function (state, detail) {
    var worthLogging = this.config.debug ||
      (state === "error" && (this.attempt < 3 || this.attempt % 20 === 0));

    if (worthLogging) {
      console.log("[чат] " + state + (detail ? " - " + detail : "") +
        (this.attempt > 3 ? "  (опит " + this.attempt + ")" : ""));
    }
    this._emit("status", { state: state, detail: detail || "", source: this.config.source });
  };

  /*
   * Пуска съобщението към играта.
   *
   * Тук отпадат дубликатите: TikTok понякога праща едно съобщение два пъти,
   * а двойно броене значи двойни точки.
   */
  Chat.prototype._deliver = function (event) {
    if (!event || !event.message) { return; }

    if (event.id) {
      if (this.recentSet[event.id]) {
        this.stats.duplicates++;
        return;
      }
      this.recentSet[event.id] = true;
      this.recent.push(event.id);
      if (this.recent.length > this.config.dedupeSize) {
        delete this.recentSet[this.recent.shift()];
      }
    }

    event.source = this.config.source;
    if (!event.timestamp) { event.timestamp = Date.now(); }

    this.stats.received++;
    this.stats.lastMessageAt = event.timestamp;
    this._emit("message", event);
  };

  Chat.prototype.connect = function () {
    this.stopped = false;

    // Източници без WebSocket (mock) сами си карат събитията.
    if (this.adapter.start) {
      var self = this;
      this._status("connected", this.adapter.label || this.config.source);
      this.stats.connects++;
      this.adapter.start(this.config, function (event) { self._deliver(event); });
      return this;
    }

    this._open();
    return this;
  };

  Chat.prototype._open = function () {
    var self = this;
    var url = this.config.url || this.adapter.url(this.config);

    this._status("connecting", url);

    try {
      this.socket = new WebSocket(url);
    } catch (err) {
      this._status("error", String(err));
      this._scheduleReconnect();
      return;
    }

    this.socket.onopen = function () {
      self.attempt = 0;
      self.stats.connects++;
      self._status("connected", url);
      if (self.adapter.onOpen) { self.adapter.onOpen(self.socket, self.config); }
    };

    this.socket.onmessage = function (frame) {
      if (self.config.debug) { console.log("[чат] сурово:", frame.data); }

      var payload;
      try {
        payload = JSON.parse(frame.data);
      } catch (err) {
        return;  // не е JSON - не ни интересува
      }

      var event = self.adapter.parse(payload, self.config);
      if (event) { self._deliver(event); }
    };

    this.socket.onerror = function () {
      // Подробностите идват в onclose - тук само отбелязваме.
      self._status("error", "проблем с връзката към " + url);
    };

    this.socket.onclose = function () {
      self.socket = null;
      if (!self.stopped) {
        self._status("disconnected", url);
        self._scheduleReconnect();
      }
    };
  };

  /* Изкачващо се изчакване с разсейване, за да не удряме сървъра в такт. */
  Chat.prototype._scheduleReconnect = function () {
    if (this.stopped) { return; }
    var self = this;
    this.attempt++;

    // Разсейването се прилага преди ограничението, не след него - иначе
    // таванът не е таван и на екрана пише "след 17 секунди" при обявени 15.
    var delay = this.config.reconnectMin * Math.pow(2, this.attempt - 1);
    delay = delay * (0.8 + Math.random() * 0.4);
    delay = Math.round(Math.min(this.config.reconnectMax, delay));

    this._status("reconnecting", "опит " + this.attempt + " след " + delay + " ms");
    clearTimeout(this.timer);
    this.timer = setTimeout(function () { self._open(); }, delay);
  };

  Chat.prototype.disconnect = function () {
    this.stopped = true;
    clearTimeout(this.timer);
    if (this.adapter.stop) { this.adapter.stop(); }
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.close();
      this.socket = null;
    }
    this._status("disconnected", "спряно ръчно");
    return this;
  };

  /*
   * Вкарва съобщение на ръка - за проверка на overlay-а без жив стрийм.
   * От конзолата на browser source-а:  chat.say("иван", "яко")
   */
  Chat.prototype.say = function (user, message) {
    this._deliver({
      user: user || "тест",
      userId: "ръчно:" + (user || "тест"),
      message: message,
      timestamp: Date.now()
    });
    return this;
  };

  root.Dumichki = root.Dumichki || {};
  root.Dumichki.Chat = {
    Chat: Chat,
    register: register,
    create: function (config) { return new Chat(config); },
    sources: function () { return Object.keys(adapters); }
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = root.Dumichki.Chat;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
