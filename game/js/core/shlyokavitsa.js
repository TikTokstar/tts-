/* Шльокавица - латинските изписвания на българските думи.
 *
 * Обща транслитерация латиница -> кирилица не става: "c" може да е к, с
 * или ц, "j" може да е ж или й, а "6" е ш. Гадаенето бърка.
 *
 * Обръщаме посоката. За всеки рунд валидните отговори са 10-14 думи. За
 * всяка от тях разгъваме предварително всички правдоподобни изписвания и
 * ги слагаме в един индекс. Проверката после е едно търсене в хеш - точна,
 * бърза, без гадаене.
 */
(function (root) {
  "use strict";

  var MAP = {
    "а": ["a"],
    "б": ["b"],
    "в": ["v", "w"],
    "г": ["g"],
    "д": ["d"],
    "е": ["e"],
    "ж": ["j", "zh", "z"],
    "з": ["z"],
    "и": ["i", "y"],
    "й": ["i", "y", "j"],
    "к": ["k", "c"],
    "л": ["l"],
    "м": ["m"],
    "н": ["n"],
    "о": ["o"],
    "п": ["p"],
    "р": ["r"],
    "с": ["s", "c"],
    "т": ["t"],
    "у": ["u"],
    "ф": ["f"],
    "х": ["h", "x"],
    "ц": ["c", "ts"],
    "ч": ["ch", "4", "c"],
    "ш": ["sh", "6", "s"],
    "щ": ["sht", "6t"],
    // ъ се изпуска изцяло много често: sarce, srce, krv. Празният вариант
    // не е екзотика, а норма.
    "ъ": ["a", "u", "y", ""],
    "ь": ["", "y"],
    "ю": ["yu", "u", "ju", "iu"],
    "я": ["ya", "q", "ia", "ja"]
  };

  // Таван на разгъването за една дума. Най-лошият случай при 7 букви е
  // около 16 хиляди варианта; таванът е предпазител, не ограничение.
  var DEFAULT_CAP = 50000;

  /* Разгъва една кирилска дума до всички латински изписвания. */
  function expand(word, cap) {
    var limit = cap || DEFAULT_CAP;
    var results = [""];
    var truncated = false;

    for (var i = 0; i < word.length; i++) {
      var options = MAP[word.charAt(i)];
      if (!options) { options = [word.charAt(i)]; }

      var next = [];
      for (var r = 0; r < results.length; r++) {
        for (var o = 0; o < options.length; o++) {
          next.push(results[r] + options[o]);
          if (next.length >= limit) { truncated = true; break; }
        }
        if (truncated) { break; }
      }
      results = next;
      if (truncated) { break; }
    }

    var unique = [];
    var seen = Object.create(null);
    for (var k = 0; k < results.length; k++) {
      var form = results[k];
      if (form && !seen[form]) {
        seen[form] = true;
        unique.push(form);
      }
    }
    return unique;
  }

  /*
   * Строи индекса за един рунд.
   *
   * Ключ е изписване (кирилско или латинско), стойност е списък от думите,
   * които се пишат така. Списък, а не една дума, защото сблъсъци се
   * случват: "сън" и "сан" дават и двете "san".
   */
  function buildIndex(words, cap) {
    var index = new Map();

    function put(key, word) {
      var bucket = index.get(key);
      if (!bucket) {
        index.set(key, [word]);
      } else if (bucket.indexOf(word) === -1) {
        bucket.push(word);
      }
    }

    for (var i = 0; i < words.length; i++) {
      var word = words[i];
      put(word, word);
      var forms = expand(word, cap);
      for (var f = 0; f < forms.length; f++) {
        put(forms[f], word);
      }
    }

    return index;
  }

  /* Кои думи отговарят на това изписване. Празен масив, ако никоя. */
  function lookup(index, spelling) {
    return index.get(spelling) || [];
  }

  root.Dumichki = root.Dumichki || {};
  root.Dumichki.Shlyokavitsa = {
    expand: expand,
    buildIndex: buildIndex,
    lookup: lookup,
    MAP: MAP
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = root.Dumichki.Shlyokavitsa;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
