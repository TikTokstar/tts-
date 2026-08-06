/* TikFinity - основният източник.
 *
 * Приложението на TikFinity върви локално и излага WebSocket на порт 21213,
 * по който препредава събитията от TikTok Live. Не иска developer акаунт и
 * само̀ се оправя с промените в протокола на TikTok.
 *
 * Схемата на събитията не е официално документирана и се е местила между
 * версиите, затото четенето на полетата е нарочно търпимо - пробваме
 * няколко имена за едно и също нещо. Ако нищо не съвпадне, пусни с
 * debug: true и виж суровите кадри в конзолата.
 */
(function (root) {
  "use strict";

  // Имената, под които различните версии пращат едно и също. Първото
  // намерено печели.
  var TEXT_FIELDS = ["comment", "message", "text", "content"];
  var NAME_FIELDS = ["nickname", "uniqueId", "displayName", "username", "user"];
  var ID_FIELDS = ["userId", "uniqueId", "secUid", "id"];
  var MSG_ID_FIELDS = ["msgId", "messageId", "id"];

  function firstString(source, fields) {
    if (!source) { return ""; }
    for (var i = 0; i < fields.length; i++) {
      var value = source[fields[i]];
      if (typeof value === "string" && value) { return value; }
      if (typeof value === "number") { return String(value); }
    }
    return "";
  }

  function parse(payload, config) {
    if (!payload || typeof payload !== "object") { return null; }

    // Обвивката е ту {event, data}, ту {type, data}, ту самото събитие.
    var name = payload.event || payload.type || payload.eventName || "";
    var data = payload.data || payload.payload || payload;

    // Подаръци, лайкове и влизания минават по същия сокет - не са наша работа.
    if (name && name !== "chat" && name !== "comment" && name !== "message") {
      return null;
    }

    var text = firstString(data, TEXT_FIELDS);
    if (!text) { return null; }

    // Потребителят понякога е вложен обект, понякога е разпльокан отгоре.
    var user = firstString(data, NAME_FIELDS) || firstString(data.user, NAME_FIELDS);
    var userId = firstString(data, ID_FIELDS) || firstString(data.user, ID_FIELDS);

    if (!user && !userId) {
      if (config && config.debug) {
        console.warn("[tikfinity] съобщение без потребител:", payload);
      }
      return null;
    }

    return {
      user: user || userId,
      userId: userId || user,
      message: text,
      id: firstString(data, MSG_ID_FIELDS),
      timestamp: Number(data.createTime) || Date.now(),
      raw: payload
    };
  }

  root.Dumichki.Chat.register("tikfinity", {
    label: "TikFinity",
    url: function (config) {
      return "ws://" + (config.host || "localhost") + ":" + (config.port || 21213) + "/";
    },
    parse: parse
  });
})(typeof globalThis !== "undefined" ? globalThis : this);
