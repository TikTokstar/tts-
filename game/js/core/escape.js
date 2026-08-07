/* Екраниране на текст, преди да влезе в HTML.
 *
 * Отделен файл, защото се ползва и от overlay-а, и от страницата за
 * проверка, а защитна мярка с две копия рано или късно става защитна мярка
 * с едно копие.
 *
 * Имената и съобщенията идват от чата - тоест от непознат човек в
 * интернет. Зрител с име <img src=x onerror="..."> не бива да може да
 * пусне каквото и да е в overlay-а.
 */
(function (root) {
  "use strict";

  var REPLACEMENTS = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  };

  function escapeHtml(text) {
    if (text === null || text === undefined) { return ""; }
    return String(text).replace(/[&<>"']/g, function (ch) {
      return REPLACEMENTS[ch];
    });
  }

  root.Dumichki = root.Dumichki || {};
  root.Dumichki.escapeHtml = escapeHtml;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = escapeHtml;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
