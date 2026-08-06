/* Речникът и търсенето "кои думи се съставят от тези букви".
 *
 * Наивният подход е да минем през всичките 113 хиляди думи и да броим
 * буквите на всяка. Работи, но е бавно, а при стойка от 7 букви има далеч
 * по-добър начин.
 *
 * Индексираме думите по "подпис" - буквите ѝ, сортирани. "роза" и "зора"
 * имат един подпис "азор". После за стойката генерираме подписите на
 * всичките ѝ подмножества - при 7 букви те са най-много 127 - и правим 127
 * търсения в хеш вместо 113 хиляди проверки.
 */
(function (root) {
  "use strict";

  var VOWELS = "аеиоуъюя";
  // Букви, с които почти нищо не се съставя. Две такива в една стойка я
  // правят мъртва.
  var RARE = "фщьюц";

  /*
   * Подписът на думата: буквите ѝ, сортирани.
   *
   * Очевидното е word.split("").sort().join(""), но то се вика 113 хиляди
   * пъти при зареждане и хаби 180 ms в разпределяне на масиви. Думите са
   * най-много 7 букви, а при толкова малко елементи сортирането чрез
   * вмъкване върху кодовете е девет пъти по-бързо.
   */
  function signature(word) {
    var codes = [];
    for (var i = 0; i < word.length; i++) {
      var code = word.charCodeAt(i);
      var j = i - 1;
      while (j >= 0 && codes[j] > code) {
        codes[j + 1] = codes[j];
        j--;
      }
      codes[j + 1] = code;
    }
    return String.fromCharCode.apply(null, codes);
  }

  function Dictionary(data) {
    this.minLength = data.minLength || 3;
    this.maxLength = data.maxLength || 7;
    this.words = data.words;

    this.bySignature = new Map();
    for (var i = 0; i < data.words.length; i++) {
      var word = data.words[i];
      var sig = signature(word);
      var bucket = this.bySignature.get(sig);
      if (bucket) { bucket.push(word); } else { this.bySignature.set(sig, [word]); }
    }

    this.rank = new Map();
    for (var c = 0; c < data.common.length; c++) {
      this.rank.set(data.common[c], c);
    }

    this._commonByLength = new Map();
    for (var k = 0; k < data.common.length; k++) {
      var w = data.common[k];
      var pool = this._commonByLength.get(w.length);
      if (pool) { pool.push(w); } else { this._commonByLength.set(w.length, [w]); }
    }
  }

  /* Известна ли е думата изобщо. */
  Dictionary.prototype.has = function (word) {
    var bucket = this.bySignature.get(signature(word));
    return !!bucket && bucket.indexOf(word) !== -1;
  };

  /* Разговорно честа ли е - тоест има ли смисъл да я търсим от зрителите. */
  Dictionary.prototype.isCommon = function (word) {
    return this.rank.has(word);
  };

  /* Колкото по-малко, толкова по-честа. Infinity за непозната. */
  Dictionary.prototype.rankOf = function (word) {
    var r = this.rank.get(word);
    return r === undefined ? Infinity : r;
  };

  /* Честите думи с дадена дължина - оттук се тегли семето. */
  Dictionary.prototype.commonOfLength = function (length) {
    return this._commonByLength.get(length) || [];
  };

  /*
   * Всички думи, които се съставят от буквите на стойката.
   *
   * Буквите се ползват най-много толкова пъти, колкото ги има в стойката -
   * затова подмножества, а не просто "всяка буква я има".
   */
  Dictionary.prototype.findInStack = function (letters, minLength, maxLength) {
    var min = minLength || this.minLength;
    var max = maxLength || letters.length;
    var sorted = letters.slice().sort();
    var n = sorted.length;
    var signatures = new Set();

    for (var mask = 1; mask < (1 << n); mask++) {
      var sig = "";
      for (var i = 0; i < n; i++) {
        if (mask & (1 << i)) { sig += sorted[i]; }
      }
      // Подписът се гради от вече сортиран масив, значи и той е сортиран.
      if (sig.length >= min && sig.length <= max) { signatures.add(sig); }
    }

    var found = [];
    var iter = signatures.values();
    for (var step = iter.next(); !step.done; step = iter.next()) {
      var bucket = this.bySignature.get(step.value);
      if (bucket) {
        for (var b = 0; b < bucket.length; b++) { found.push(bucket[b]); }
      }
    }
    return found;
  };

  function countVowels(letters) {
    var n = 0;
    for (var i = 0; i < letters.length; i++) {
      if (VOWELS.indexOf(letters[i]) !== -1) { n++; }
    }
    return n;
  }

  function countRare(letters) {
    var n = 0;
    for (var i = 0; i < letters.length; i++) {
      if (RARE.indexOf(letters[i]) !== -1) { n++; }
    }
    return n;
  }

  root.Dumichki = root.Dumichki || {};
  root.Dumichki.Dictionary = Dictionary;
  root.Dumichki.dictUtil = {
    signature: signature,
    countVowels: countVowels,
    countRare: countRare,
    VOWELS: VOWELS,
    RARE: RARE
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { Dictionary: Dictionary, util: root.Dumichki.dictUtil };
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
