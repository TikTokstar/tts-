/* Нормализация на съобщенията от чата.
 *
 * Каквото дойде от TikTok - емоджита, удивителни, @споменавания, главни
 * букви - излиза оттук като чист низ, годен за сравнение.
 */
(function (root) {
  "use strict";

  var CYRILLIC = /[Ѐ-ӿ]/;
  var DROP_CYRILLIC = /[^абвгдежзийклмнопрстуфхцчшщъьюя]/g;
  // В латиница пазим само буквите и цифрите 4 и 6 - те са букви в
  // шльокавицата (ч и ш). Всичко останало е шум.
  var DROP_LATIN = /[^a-z46]/g;
  var LEADING_MENTIONS = /^(?:\s*@[^\s]+)+\s*/;

  // Колко думи от едно съобщение проверяваме. Зрителите пишат "мисля че е
  // яко", а не само "яко" - но не искаме и цял роман да се сканира.
  var MAX_TOKENS = 6;

  function hasCyrillic(text) {
    return CYRILLIC.test(text);
  }

  /* Свежда една дума до голите ѝ букви. */
  function normalizeToken(token) {
    if (!token) { return ""; }
    var s = token.normalize("NFC").toLowerCase();
    return hasCyrillic(s) ? s.replace(DROP_CYRILLIC, "") : s.replace(DROP_LATIN, "");
  }

  /*
   * Връща всички низа, които си струва да проверим за едно съобщение.
   *
   * Първо цялото съобщение без интервали - хваща "q k o" и "с ъ р ц е".
   * После всяка дума поотделно - хваща "мисля че е яко". Двете заедно
   * покриват как хората наистина пишат в чата.
   */
  function candidates(text) {
    if (typeof text !== "string" || !text) { return []; }

    var stripped = text.normalize("NFC").toLowerCase().replace(LEADING_MENTIONS, "");
    var out = [];
    var seen = Object.create(null);

    function add(value) {
      if (value && !seen[value]) {
        seen[value] = true;
        out.push(value);
      }
    }

    add(normalizeToken(stripped.replace(/\s+/g, "")));

    var tokens = stripped.split(/\s+/);
    for (var i = 0; i < tokens.length && i < MAX_TOKENS; i++) {
      add(normalizeToken(tokens[i]));
    }

    return out;
  }

  root.Dumichki = root.Dumichki || {};
  root.Dumichki.Normalize = {
    candidates: candidates,
    normalizeToken: normalizeToken,
    hasCyrillic: hasCyrillic
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = root.Dumichki.Normalize;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
