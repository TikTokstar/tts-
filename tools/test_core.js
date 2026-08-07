/* Тестове на ядрото. Пуска се с:  node tools/test_core.js
 *
 * Проверява това, което може да провали играта тихо: шльокавицата да не
 * пропуска, subset търсенето да не лъже, стойките да излизат играеми.
 */
"use strict";

var path = require("path");
var CORE = path.join(__dirname, "..", "game", "js", "core");

var data = require(path.join(__dirname, "..", "game", "data", "dictionary.js"));
require(path.join(CORE, "escape.js"));
require(path.join(CORE, "normalize.js"));
require(path.join(CORE, "shlyokavitsa.js"));
require(path.join(CORE, "dictionary.js"));
require(path.join(CORE, "stack.js"));
require(path.join(CORE, "round.js"));

var D = globalThis.Dumichki;

var passed = 0;
var failed = 0;

function check(name, condition, detail) {
  if (condition) {
    passed++;
    console.log("  ✓ " + name);
  } else {
    failed++;
    console.log("  ✗ " + name + (detail ? "  -> " + detail : ""));
  }
}

function section(title) {
  console.log("\n" + title);
  console.log("-".repeat(title.length));
}

/* Възпроизводим генератор, за да са тестовете стабилни. */
function mulberry32(seed) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6D2B79F5) | 0;
    var t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// --- Зареждане --------------------------------------------------------------

section("Речник");

var t0 = Date.now();
var dict = new D.Dictionary(data);
var loadMs = Date.now() - t0;

console.log("  " + data.words.length + " думи, " + data.common.length +
  " чести, индексът се строи за " + loadMs + " ms");
check("зареждането е под 1500 ms", loadMs < 1500, loadMs + " ms");
check("познава 'сърце'", dict.has("сърце"));
check("познава 'човек'", dict.has("човек"));
check("не познава 'ъъъъ'", !dict.has("ъъъъ"));
check("'човек' е честа дума", dict.isCommon("човек"));

// --- Шльокавица -------------------------------------------------------------

section("Шльокавица - изискваните случаи");

var cases = [
  ["яко", "qko"],
  ["човек", "4ovek"],
  ["сърце", "sarce"]
];

cases.forEach(function (pair) {
  var forms = D.Shlyokavitsa.expand(pair[0]);
  check("'" + pair[0] + "' -> '" + pair[1] + "'",
    forms.indexOf(pair[1]) !== -1,
    "разгънати " + forms.length + " варианта, примерни: " + forms.slice(0, 6).join(", "));
});

section("Шльокавица - още изписвания");

var more = [
  ["сърце", ["sarce", "srce", "surce", "syrce", "sarce"]],
  ["кръв", ["krv", "krav", "kruv"]],
  ["шапка", ["6apka", "shapka", "sapka"]],
  ["жена", ["jena", "zhena", "zena"]],
  ["щерка", ["6terka", "shterka"]],
  ["дъщеря", ["da6terq", "dashteria", "d6terya"]],
  ["яйце", ["qice", "yaice", "jajce"]],
  ["чушка", ["4u6ka", "chushka", "cuska"]],
  ["любов", ["lyubov", "lubov", "ljubow"]],
  ["мляко", ["mlqko", "mlyako", "mliako"]]
];

more.forEach(function (pair) {
  var forms = D.Shlyokavitsa.expand(pair[0]);
  var missing = pair[1].filter(function (f) { return forms.indexOf(f) === -1; });
  check("'" + pair[0] + "' покрива " + pair[1].join(", "),
    missing.length === 0, "липсват: " + missing.join(", "));
});

section("Шльокавица - размер на разгъването");

var sizes = ["сърце", "дъщеря", "щастлив", "любов", "чушка"].map(function (w) {
  return w + ":" + D.Shlyokavitsa.expand(w).length;
});
console.log("  " + sizes.join("  "));
var worst = 0;
for (var i = 0; i < data.common.length && i < 3000; i++) {
  var n = D.Shlyokavitsa.expand(data.common[i]).length;
  if (n > worst) { worst = n; }
}
check("най-лошият случай остава разумен", worst < 20000, worst + " варианта");

// --- Нормализация -----------------------------------------------------------

section("Нормализация на входа");

var normCases = [
  ["ЯКО", "яко"],
  ["Яко!!!", "яко"],
  ["  яко  ", "яко"],
  ["яко 🔥🔥🔥", "яко"],
  ["@someuser яко", "яко"],
  ["@a @b сърце", "сърце"],
  ["4OVEK", "4ovek"],
  ["q k o", "qko"],
  ["мисля че е яко", "яко"],
  ["думата е сърце мисля", "сърце"]
];

normCases.forEach(function (pair) {
  var got = D.Normalize.candidates(pair[0]);
  check("'" + pair[0] + "' дава '" + pair[1] + "'",
    got.indexOf(pair[1]) !== -1, "получено: " + JSON.stringify(got));
});

// --- Екраниране -------------------------------------------------------------

section("Екраниране на имена от чата");

var nasty = [
  ['<img src=x onerror="alert(1)">',
   "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"],
  ["<script>alert(1)</script>",
   "&lt;script&gt;alert(1)&lt;/script&gt;"],
  ['" onmouseover="alert(1)',
   "&quot; onmouseover=&quot;alert(1)"],
  ["Гошо & Пешо", "Гошо &amp; Пешо"],
  ["it's", "it&#39;s"]
];

nasty.forEach(function (pair) {
  var out = D.escapeHtml(pair[0]);
  check("'" + pair[0].slice(0, 26) + "' се обезврежда", out === pair[1], out);
});

// Нито един от опасните знаци не бива да оцелее суров.
var mixed = D.escapeHtml("<a href='x' onclick=\"y\">&</a>");
check("нищо суро не остава",
  !/[<>]/.test(mixed) && mixed.indexOf("'") === -1 && mixed.indexOf('"') === -1,
  mixed);

check("нормалните имена остават четими",
  D.escapeHtml("Мария ✨") === "Мария ✨");
check("празно и липсващо не гърмят",
  D.escapeHtml("") === "" && D.escapeHtml(null) === "" &&
  D.escapeHtml(undefined) === "");

// --- Subset търсене ---------------------------------------------------------

section("Търсене по стойка");

var letters = "розата".split("");
var found = dict.findInStack(letters, 3, 6);
check("'роза' се намира в стойката на 'розата'", found.indexOf("роза") !== -1);
check("'зора' се намира (анаграм)", found.indexOf("зора") !== -1);
check("'азот' се намира", found.indexOf("азот") !== -1);
check("'рози' НЕ се намира (няма 'и')", found.indexOf("рози") === -1);
check("'аз' НЕ се намира (под 3 букви)", found.indexOf("аз") === -1);

// Буквите се ползват най-много колкото ги има.
var double = dict.findInStack("кака".split(""), 3, 4);
check("'кака' се намира в 'кака' (две к, две а)", double.indexOf("кака") !== -1);
var single = dict.findInStack("каси".split(""), 3, 4);
check("'кака' НЕ се намира в 'каси' (само едно к)", single.indexOf("кака") === -1);

// Кръстосана проверка срещу наивния метод - индексът трябва да дава същото.
function naive(stackLetters, min, max) {
  var pool = {};
  stackLetters.forEach(function (ch) { pool[ch] = (pool[ch] || 0) + 1; });
  return data.words.filter(function (word) {
    if (word.length < min || word.length > max) { return false; }
    var need = {};
    for (var k = 0; k < word.length; k++) {
      need[word[k]] = (need[word[k]] || 0) + 1;
      if (need[word[k]] > (pool[word[k]] || 0)) { return false; }
    }
    return true;
  });
}

var rngCheck = mulberry32(11);
var mismatches = 0;
for (var s = 0; s < 5; s++) {
  var seedPool = dict.commonOfLength(7);
  var seed = seedPool[Math.floor(rngCheck() * seedPool.length)];
  var fast = dict.findInStack(seed.split(""), 3, 7).slice().sort();
  var slow = naive(seed.split(""), 3, 7).slice().sort();
  if (fast.join("|") !== slow.join("|")) { mismatches++; }
}
check("индексът съвпада с наивното търсене (5 стойки)", mismatches === 0,
  mismatches + " разминавания");

var tSearch = Date.now();
for (var q = 0; q < 200; q++) { dict.findInStack("розата".split(""), 3, 6); }
var perSearch = (Date.now() - tSearch) / 200;
console.log("  едно търсене: " + perSearch.toFixed(2) + " ms");
check("търсенето е под 5 ms", perSearch < 5, perSearch.toFixed(2) + " ms");

// --- Генериране на стойки ---------------------------------------------------

section("Генериране на стойки");

var rng = mulberry32(2024);
var rounds = [];
var totalAttempts = 0;
var tGen = Date.now();
for (var g = 0; g < 200; g++) {
  var round = D.Round.createRound(dict, {}, rng);
  if (round) { rounds.push(round); totalAttempts += round.attempts; }
}
var genMs = (Date.now() - tGen) / 200;

check("200 от 200 стойки са генерирани", rounds.length === 200, rounds.length + "");
console.log("  средно " + (totalAttempts / rounds.length).toFixed(1) +
  " опита на стойка, " + genMs.toFixed(1) + " ms на рунд");
check("генерирането е под 100 ms на рунд", genMs < 100, genMs.toFixed(1) + " ms");

var badVowels = 0, badRare = 0, badTargets = 0, badFit = 0, badLength = 0;
rounds.forEach(function (r) {
  if (D.dictUtil.countVowels(r.letters) < 2) { badVowels++; }
  if (D.dictUtil.countRare(r.letters) > 1) { badRare++; }
  if (r.targets.length < 10 || r.targets.length > 14) { badTargets++; }
  r.targets.forEach(function (word) {
    if (!dict.isCommon(word)) { badFit++; }
    if (word.length < 3 || word.length > r.letters.length) { badLength++; }
  });
});

check("всички стойки имат поне 2 гласни", badVowels === 0, badVowels + " нарушения");
check("нито една с повече от 1 рядка буква", badRare === 0, badRare + " нарушения");
check("всички имат 10-14 цели", badTargets === 0, badTargets + " нарушения");
check("всички цели са чести думи", badFit === 0, badFit + " нарушения");
check("всички цели са с валидна дължина", badLength === 0, badLength + " нарушения");

var withLong = rounds.filter(function (r) {
  return r.targets.some(function (w) { return w.length >= r.letters.length - 1; });
}).length;
check("почти всички рундове имат дълга дума",
  withLong >= rounds.length * 0.95, withLong + "/" + rounds.length);

// --- Познаване от чата ------------------------------------------------------

section("Познаване от чата");

var demo = null;
var demoRng = mulberry32(77);
while (!demo) {
  var candidate = D.Round.createRound(dict, {}, demoRng);
  if (candidate && candidate.targets.length >= 10) { demo = candidate; }
}

console.log("  стойка: " + demo.letters.join(" ").toUpperCase() +
  "   (семе: " + demo.seed + ")");
console.log("  цели: " + demo.targets.join(", "));

var hitsCyrillic = 0;
var hitsLatin = 0;
demo.targets.forEach(function (word) {
  if (D.Round.matchGuess(demo, word.toUpperCase() + "!!")) { hitsCyrillic++; }
  var latin = D.Shlyokavitsa.expand(word)[0];
  if (D.Round.matchGuess(demo, latin)) { hitsLatin++; }
});

check("всички цели се познават на кирилица", hitsCyrillic === demo.targets.length,
  hitsCyrillic + "/" + demo.targets.length);
check("всички цели се познават на шльокавица", hitsLatin === demo.targets.length,
  hitsLatin + "/" + demo.targets.length);

check("грешна дума не се брои", D.Round.matchGuess(demo, "ъъъъъъ") === null);
check("празно съобщение не се брои", D.Round.matchGuess(demo, "") === null);
check("само емоджи не се брои",
  D.Round.matchGuess(demo, "🔥😂") === null);

var firstTarget = demo.targets[0];
D.Round.reveal(demo, firstTarget, "иван");
check("намерена дума не се брои втори път",
  D.Round.matchGuess(demo, firstTarget) === null);
check("останалите намаляват след познаване",
  D.Round.remaining(demo).length === demo.targets.length - 1);
check("рундът не е завършен", !D.Round.isComplete(demo));

demo.targets.forEach(function (w) { D.Round.reveal(demo, w, "петър"); });
check("рундът завършва при всички познати", D.Round.isComplete(demo));

// --- Обобщение --------------------------------------------------------------

section("Обобщение");
console.log("  минали: " + passed + "   паднали: " + failed);
process.exit(failed === 0 ? 0 : 1);
