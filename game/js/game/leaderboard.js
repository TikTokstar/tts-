/* Класация. В играта живеят две от тях едновременно.
 *
 * Едната се нулира при всяко ниво, другата - само при презареждане на
 * browser source-а. Затова е отделен обект, а не два речника, разхвърляни
 * из играта.
 */
(function (root) {
  "use strict";

  function Leaderboard() {
    this.points = new Map();
  }

  Leaderboard.prototype.add = function (user, amount) {
    this.points.set(user, (this.points.get(user) || 0) + amount);
  };

  Leaderboard.prototype.pointsOf = function (user) {
    return this.points.get(user) || 0;
  };

  /* Подредени по точки, при равенство - по азбучен ред, за да не подскачат. */
  Leaderboard.prototype.sorted = function () {
    var rows = [];
    this.points.forEach(function (value, user) {
      rows.push({ user: user, points: value });
    });
    rows.sort(function (a, b) {
      return b.points - a.points || a.user.localeCompare(b.user, "bg");
    });
    for (var i = 0; i < rows.length; i++) { rows[i].rank = i + 1; }
    return rows;
  };

  Leaderboard.prototype.top = function (count) {
    return this.sorted().slice(0, count);
  };

  /* Кой на кое място е - за стрелките при изкачване. */
  Leaderboard.prototype.ranks = function () {
    var map = new Map();
    this.sorted().forEach(function (row) { map.set(row.user, row.rank); });
    return map;
  };

  Leaderboard.prototype.reset = function () {
    this.points.clear();
  };

  Leaderboard.prototype.size = function () {
    return this.points.size;
  };

  root.Dumichki = root.Dumichki || {};
  root.Dumichki.Leaderboard = Leaderboard;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = Leaderboard;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
