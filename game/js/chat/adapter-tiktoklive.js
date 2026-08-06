/* TikTokLive - резервният източник.
 *
 * Говори с bridge/tiktok_bridge.py, който върви локално, чете стрийма през
 * библиотеката TikTokLive и препредава коментарите по WebSocket.
 *
 * Тук схемата е известна докрай, защото мостът е наш - затова четенето е
 * строго, за разлика от адаптера за TikFinity.
 */
(function (root) {
  "use strict";

  function parse(payload) {
    if (!payload || payload.event !== "chat") { return null; }

    var data = payload.data;
    if (!data || !data.message) { return null; }

    return {
      user: data.user || data.userId || "?",
      userId: data.userId || data.user || "?",
      message: data.message,
      id: data.id || "",
      timestamp: data.timestamp || Date.now(),
      raw: payload
    };
  }

  root.Dumichki.Chat.register("tiktoklive", {
    label: "TikTokLive мост",
    url: function (config) {
      return "ws://" + (config.host || "localhost") + ":" + (config.port || 21214) + "/";
    },
    parse: parse
  });
})(typeof globalThis !== "undefined" ? globalThis : this);
