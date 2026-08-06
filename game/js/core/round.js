/* Рундът - връзката между стойката, шльокавицата и чата.
 *
 * Тук няма точки, таймери и cooldown - те са част от геймплея. Тук е само
 * отговорът на въпроса "това съобщение познава ли нещо".
 */
(function (root) {
  "use strict";

  var Stack = root.Dumichki.Stack;
  var Shlyokavitsa = root.Dumichki.Shlyokavitsa;
  var Normalize = root.Dumichki.Normalize;

  /*
   * Тегли стойка и приготвя индекса за познаване.
   *
   * Индексът се строи само от целевите думи - 10-14 броя. Оттам идва и
   * бързината: разгъването на шльокавицата е скъпо, но се прави веднъж на
   * рунд за шепа думи, а не за целия речник.
   */
  function createRound(dict, options, rng) {
    var stack = Stack.generate(dict, options, rng);
    if (!stack) { return null; }

    return {
      seed: stack.seed,
      letters: stack.letters,
      targets: stack.targets,
      playable: stack.playable,
      found: new Map(),
      index: Shlyokavitsa.buildIndex(stack.targets),
      attempts: stack.attempts
    };
  }

  /*
   * Проверява съобщение от чата.
   *
   * Връща познатата дума или null. Не променя нищо - решението дали
   * познаването се брои (cooldown, изтекъл рунд) е на геймплея.
   */
  function matchGuess(round, message) {
    var options = Normalize.candidates(message);

    for (var i = 0; i < options.length; i++) {
      var words = Shlyokavitsa.lookup(round.index, options[i]);
      for (var w = 0; w < words.length; w++) {
        // При сблъсък ("san" е и "сън", и "сан") взимаме първата ненамерена.
        if (!round.found.has(words[w])) {
          return { word: words[w], spelling: options[i] };
        }
      }
    }
    return null;
  }

  /* Отбелязва думата като намерена от този зрител. */
  function reveal(round, word, user) {
    if (round.found.has(word)) { return false; }
    round.found.set(word, user);
    return true;
  }

  function remaining(round) {
    var out = [];
    for (var i = 0; i < round.targets.length; i++) {
      if (!round.found.has(round.targets[i])) { out.push(round.targets[i]); }
    }
    return out;
  }

  function isComplete(round) {
    return round.found.size >= round.targets.length;
  }

  root.Dumichki.Round = {
    createRound: createRound,
    matchGuess: matchGuess,
    reveal: reveal,
    remaining: remaining,
    isComplete: isComplete
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = root.Dumichki.Round;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
