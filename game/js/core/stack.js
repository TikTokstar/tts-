/* Генериране на стойката.
 *
 * Случайни букви не стават - излизат стойки като Щ Ю Ф Ь Ц Ъ, от които не
 * се съставя нищо. Затова тръгваме от истинска дума: тегли се семе от 6-7
 * букви, буквите му стават стойката, и оттам гарантирано има поне един
 * пълен отговор.
 *
 * После стойката се проверява и ако не мине - тегли се ново семе.
 */
(function (root) {
  "use strict";

  var util = root.Dumichki.dictUtil;

  var DEFAULTS = {
    seedLengths: [6, 7],
    minWordLength: 3,
    // Праговете се броят по ЧЕСТИТЕ находки, не по всички. Стойка с 20
    // находки, от които 16 са "зер", "мър" и "зре", е мъртъв рунд, макар
    // формално да минава.
    minPlayable: 10,
    maxPlayable: 40,
    minVowels: 2,
    maxRareLetters: 1,
    targetsMin: 10,
    targetsMax: 14,
    maxAttempts: 400
  };

  function pick(array, rng) {
    return array[Math.floor(rng() * array.length)];
  }

  /* Разбърква копие на масива - Fisher-Yates. */
  function shuffle(array, rng) {
    var random = rng || Math.random;
    var out = array.slice();
    for (var i = out.length - 1; i > 0; i--) {
      var j = Math.floor(random() * (i + 1));
      var tmp = out[i];
      out[i] = out[j];
      out[j] = tmp;
    }
    return out;
  }

  /*
   * Избира кои от находките стават цели за рунда.
   *
   * Не просто най-честите: върви се в кръг по дължините, като най-дългите
   * са първи. Иначе целите излизат само от 3 и 4 букви (късите думи са
   * по-чести) и рундът остава без нито една дълга дума, а точно те носят
   * точките и ефектите.
   */
  function selectTargets(playable, dict, count) {
    var byLength = new Map();
    for (var i = 0; i < playable.length; i++) {
      var word = playable[i];
      var bucket = byLength.get(word.length);
      if (bucket) { bucket.push(word); } else { byLength.set(word.length, [word]); }
    }

    var lengths = [];
    var iter = byLength.keys();
    for (var step = iter.next(); !step.done; step = iter.next()) {
      lengths.push(step.value);
      byLength.get(step.value).sort(function (a, b) {
        return dict.rankOf(a) - dict.rankOf(b);
      });
    }
    lengths.sort(function (a, b) { return b - a; });

    var cursor = {};
    for (var l = 0; l < lengths.length; l++) { cursor[lengths[l]] = 0; }

    var picked = [];
    var progressed = true;
    while (picked.length < count && progressed) {
      progressed = false;
      for (var k = 0; k < lengths.length && picked.length < count; k++) {
        var length = lengths[k];
        var pool = byLength.get(length);
        if (cursor[length] < pool.length) {
          picked.push(pool[cursor[length]++]);
          progressed = true;
        }
      }
    }

    picked.sort(function (a, b) {
      return a.length - b.length || a.localeCompare(b, "bg");
    });
    return picked;
  }

  /*
   * Тегли стойка, докато излезе годна.
   *
   * Проверките са подредени от евтина към скъпа: гласните и редките букви
   * се броят наум, а търсенето на находките е най-тежката стъпка и се пази
   * за накрая.
   */
  function generate(dict, options, rng) {
    var cfg = Object.assign({}, DEFAULTS, options || {});
    var random = rng || Math.random;
    var attempts = 0;
    var rejected = { vowels: 0, rare: 0, tooFew: 0, tooMany: 0 };

    while (attempts < cfg.maxAttempts) {
      attempts++;

      var seedLength = pick(cfg.seedLengths, random);
      var pool = dict.commonOfLength(seedLength);
      if (!pool.length) { continue; }
      var seed = pick(pool, random);
      var letters = seed.split("");

      if (util.countVowels(letters) < cfg.minVowels) { rejected.vowels++; continue; }
      if (util.countRare(letters) > cfg.maxRareLetters) { rejected.rare++; continue; }

      var found = dict.findInStack(letters, cfg.minWordLength, letters.length);
      var playable = [];
      for (var i = 0; i < found.length; i++) {
        if (dict.isCommon(found[i])) { playable.push(found[i]); }
      }

      if (playable.length < cfg.minPlayable) { rejected.tooFew++; continue; }
      if (playable.length > cfg.maxPlayable) { rejected.tooMany++; continue; }

      // Колкото по-богата е стойката, толкова повече цели - иначе бедна и
      // богата стойка изглеждат еднакво и рундът не диша.
      var count = Math.round(playable.length / 2);
      count = Math.max(cfg.targetsMin, Math.min(cfg.targetsMax, count));
      count = Math.min(count, playable.length);

      return {
        seed: seed,
        letters: shuffle(letters, random),
        found: found,
        playable: playable,
        targets: selectTargets(playable, dict, count),
        attempts: attempts,
        rejected: rejected
      };
    }

    return null;
  }

  root.Dumichki.Stack = {
    generate: generate,
    selectTargets: selectTargets,
    shuffle: shuffle,
    DEFAULTS: DEFAULTS
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = root.Dumichki.Stack;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
