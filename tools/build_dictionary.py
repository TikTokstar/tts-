#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Построява речника за играта "Думички".

Сваля hunspell речника за български (BGoffice), разгъва афиксите до всички
словоформи, изчиства нежеланото и записва плосък JSON списък.

Произвежда два файла:

  data/words.json   всички валидни словоформи. Ползва се за проверката
                    "тази дума съставя ли се от буквите на стойката".
  data/common.json  подмножеството от разговорно честите думи, подредено
                    от най-честата надолу. Ползва се САМО за избор на семе
                    и на целеви думи за рунда.

Второто е разликата между играема и неиграема игра: речникът съдържа форми
като "глумящо" и "сопаш" - валидни, но никой зрител няма да ги напише.

Пуска се ВЕДНЪЖ, преди стрийма. По време на игра се четат само готовите
JSON файлове - никакви заявки към интернет.

    python3 tools/build_dictionary.py

Опции:
    --max-len N     максимална дължина на дума в изхода (по подразбиране 9)
    --min-len N     минимална дължина (по подразбиране 3)
    --offline       не сваля нищо, ползва вече свалените файлове в data/source/
    --out PATH      къде да запише (по подразбиране data/words.json)
    --no-frequency  пропуска честотния списък (не се препоръчва)
"""

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.request
from collections import Counter

# --- Пътища -----------------------------------------------------------------

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIR = os.path.join(ROOT, "data", "source")
DEFAULT_OUT = os.path.join(ROOT, "data", "words.json")
DEFAULT_COMMON_OUT = os.path.join(ROOT, "data", "common.json")
DEFAULT_RUNTIME_OUT = os.path.join(ROOT, "game", "data", "dictionary.js")

# Огледала за hunspell речника. LibreOffice/dictionaries е поддържаното
# репо на BGoffice речника; останалите са резервни копия на същия източник.
MIRRORS = [
    (
        "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/bg_BG/bg_BG.aff",
        "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/bg_BG/bg_BG.dic",
    ),
    (
        "https://raw.githubusercontent.com/wooorm/dictionaries/main/dictionaries/bg/index.aff",
        "https://raw.githubusercontent.com/wooorm/dictionaries/main/dictionaries/bg/index.dic",
    ),
    (
        "https://raw.githubusercontent.com/titoBouzout/Dictionaries/master/Bulgarian.aff",
        "https://raw.githubusercontent.com/titoBouzout/Dictionaries/master/Bulgarian.dic",
    ),
]

# Честотен списък от субтитри (OpenSubtitles 2018). Точно регистърът, на
# който се пише в TikTok чата - разговорен, не книжовно-архаичен.
FREQ_MIRRORS = [
    "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/bg/bg_50k.txt",
    "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2016/bg/bg_50k.txt",
]

# --- Българската азбука -----------------------------------------------------

BG_ALPHABET = "абвгдежзийклмнопрстуфхцчшщъьюя"
BG_SET = frozenset(BG_ALPHABET)
VOWELS = frozenset("аеиоуъюя")  # ъ е гласна - важно за валидацията на стойките

# Символи, които веднага дисквалифицират думата (съкращения, съставни форми).
REJECT_CHARS = frozenset(".-‐‑‒–—'’ʼ´` /\\")


# --- Четене на hunspell .aff ------------------------------------------------


class AffixRule:
    """Едно PFX/SFX правило: махни `strip`, добави `add`, ако пасва `condition`."""

    __slots__ = ("kind", "flag", "strip", "add", "cond_re", "cross")

    def __init__(self, kind, flag, strip, add, condition, cross):
        self.kind = kind          # "PFX" или "SFX"
        self.flag = flag
        self.strip = "" if strip == "0" else strip
        self.add = "" if add == "0" else add
        self.cross = cross
        self.cond_re = compile_condition(condition, kind)


def compile_condition(condition, kind):
    """
    Превежда hunspell условието в regex.

    Hunspell ползва подмножество на regex: `.` е произволен знак, `[абв]` е
    клас, `[^абв]` е отрицание, всичко останало е буквално. Условието се
    проверява в края на думата за суфикс и в началото за префикс.
    """
    if condition in (".", "", "0"):
        return None  # пасва на всичко - не хабим време за regex

    out = []
    i = 0
    while i < len(condition):
        ch = condition[i]
        if ch == "[":
            end = condition.find("]", i)
            if end == -1:  # счупено условие - третираме скобата буквално
                out.append(re.escape(ch))
                i += 1
                continue
            body = condition[i + 1:end]
            negate = body.startswith("^")
            if negate:
                body = body[1:]
            out.append("[%s%s]" % ("^" if negate else "", re.escape(body)))
            i = end + 1
        elif ch == ".":
            out.append(".")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1

    pattern = "".join(out)
    # Суфиксното условие описва КРАЯ на думата, префиксното - началото.
    return re.compile(pattern + "$" if kind == "SFX" else "^" + pattern)


def parse_flags(raw, flag_mode, aliases):
    """Разбива низа с флагове от .dic реда според FLAG режима на .aff файла."""
    if not raw:
        return []
    if aliases and raw.isdigit():
        return aliases.get(int(raw), [])
    if flag_mode == "num":
        return [f for f in raw.split(",") if f]
    if flag_mode == "long":
        return [raw[i:i + 2] for i in range(0, len(raw), 2)]
    return list(raw)  # по подразбиране: един знак = един флаг


def parse_aff(path):
    """Чете .aff файла и връща (правила по флаг, FLAG режим, AF псевдоними)."""
    rules = {}
    flag_mode = "char"
    aliases = {}

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()

    i = 0
    alias_index = 0
    while i < len(lines):
        parts = lines[i].split()
        i += 1
        if not parts or parts[0].startswith("#"):
            continue

        key = parts[0]

        if key == "FLAG" and len(parts) >= 2:
            flag_mode = parts[1].lower()

        elif key == "AF" and len(parts) >= 2:
            if parts[1].isdigit() and alias_index == 0 and len(parts) == 2:
                alias_index = 1  # заглавен ред "AF <брой>"
            else:
                aliases[alias_index] = parse_flags(parts[1], flag_mode, None)
                alias_index += 1

        elif key in ("PFX", "SFX") and len(parts) >= 4:
            flag, cross_flag, count = parts[1], parts[2], parts[3]
            if cross_flag not in ("Y", "N") or not count.isdigit():
                continue  # не е заглавен ред на блок - пропускаме
            cross = cross_flag == "Y"

            for _ in range(int(count)):
                if i >= len(lines):
                    break
                rule_parts = lines[i].split()
                i += 1
                if len(rule_parts) < 4 or rule_parts[0] != key:
                    i -= 1  # блокът свърши по-рано от обявеното
                    break
                strip = rule_parts[2]
                add = rule_parts[3]
                if "/" in add:  # продължаващи флагове - не ги ползваме
                    add = add.split("/", 1)[0]
                cond = rule_parts[4] if len(rule_parts) > 4 else "."
                rules.setdefault(flag, []).append(
                    AffixRule(key, flag, strip, add, cond, cross)
                )

    return rules, flag_mode, aliases


# --- Разгъване на афиксите --------------------------------------------------


def apply_rule(word, rule):
    """Прилага едно правило. Връща None, ако не пасва на думата."""
    if rule.kind == "SFX":
        # Hunspell изисква думата наистина да завършва на `strip`.
        if rule.strip:
            if not word.endswith(rule.strip):
                return None
            stem = word[: len(word) - len(rule.strip)]
        else:
            stem = word
        if not stem:
            return None
        if rule.cond_re and not rule.cond_re.search(word):
            return None
        return stem + rule.add

    if rule.strip:
        if not word.startswith(rule.strip):
            return None
        stem = word[len(rule.strip):]
    else:
        stem = word
    if not stem:
        return None
    if rule.cond_re and not rule.cond_re.search(word):
        return None
    return rule.add + stem


def expand(stem, flags, rules):
    """Връща основната форма плюс всички словоформи от афиксите ѝ."""
    forms = [stem]

    suffixed = []
    for flag in flags:
        for rule in rules.get(flag, ()):
            if rule.kind != "SFX":
                continue
            form = apply_rule(stem, rule)
            if form:
                forms.append(form)
                if rule.cross:
                    suffixed.append(form)

    # Кръстосано произведение: префикс върху вече суфиксираните форми.
    for flag in flags:
        for rule in rules.get(flag, ()):
            if rule.kind != "PFX":
                continue
            base = apply_rule(stem, rule)
            if base:
                forms.append(base)
            if rule.cross:
                for form in suffixed:
                    crossed = apply_rule(form, rule)
                    if crossed:
                        forms.append(crossed)

    return forms


# --- Филтриране -------------------------------------------------------------


def reject_reason(word, min_len, max_len):
    """Връща причината думата да отпадне, или None ако е чиста."""
    if not word:
        return "празна"
    if any(ch in REJECT_CHARS for ch in word):
        return "съкращение/тире/апостроф"
    if any(ch.isupper() for ch in word):
        return "главна буква (собствено име)"
    if any(ch.isdigit() for ch in word):
        return "цифри"
    # Нормализираме, за да хванем разложени диакритики (ѝ = и + U+0300).
    if any(ch not in BG_SET for ch in unicodedata.normalize("NFC", word)):
        return "буква извън българската азбука"
    if len(word) < min_len:
        return "под %d букви" % min_len
    if len(word) > max_len:
        return "над %d букви" % max_len
    return None


# --- Сваляне ----------------------------------------------------------------


def download(offline):
    """Сваля .aff/.dic (или ползва кеша). Връща пътищата до двата файла."""
    os.makedirs(SOURCE_DIR, exist_ok=True)
    aff_path = os.path.join(SOURCE_DIR, "bg_BG.aff")
    dic_path = os.path.join(SOURCE_DIR, "bg_BG.dic")

    if os.path.exists(aff_path) and os.path.exists(dic_path):
        print("Ползвам вече свалените файлове в %s" % SOURCE_DIR)
        return aff_path, dic_path

    if offline:
        sys.exit("Няма кеширани файлове в %s, а --offline е зададено." % SOURCE_DIR)

    last_error = None
    for aff_url, dic_url in MIRRORS:
        try:
            print("Свалям от %s ..." % aff_url.rsplit("/", 2)[0])
            for url, path in ((aff_url, aff_path), (dic_url, dic_path)):
                with urllib.request.urlopen(url, timeout=60) as resp:
                    data = resp.read()
                if len(data) < 1024:
                    raise IOError("подозрително малък файл: %s (%d байта)" % (url, len(data)))
                with open(path, "wb") as fh:
                    fh.write(data)
            print("  готово: %s (%d KB), %s (%d KB)" % (
                os.path.basename(aff_path), os.path.getsize(aff_path) // 1024,
                os.path.basename(dic_path), os.path.getsize(dic_path) // 1024,
            ))
            return aff_path, dic_path
        except Exception as exc:  # огледалото не работи - пробваме следващото
            last_error = exc
            print("  неуспех: %s" % exc)

    sys.exit("Нито едно огледало не отговори. Последна грешка: %s" % last_error)


def download_frequency(offline):
    """
    Сваля честотния списък. Връща пътя или None.

    Не е фатално, ако липсва - играта работи и без него, просто избира
    целевите думи по-глупаво.
    """
    os.makedirs(SOURCE_DIR, exist_ok=True)
    freq_path = os.path.join(SOURCE_DIR, "bg_50k.txt")

    if os.path.exists(freq_path):
        return freq_path
    if offline:
        print("Няма кеширан честотен списък, а --offline е зададено - пропускам.")
        return None

    for url in FREQ_MIRRORS:
        try:
            print("Свалям честотния списък ...")
            with urllib.request.urlopen(url, timeout=60) as resp:
                data = resp.read()
            if len(data) < 1024:
                raise IOError("подозрително малък файл (%d байта)" % len(data))
            with open(freq_path, "wb") as fh:
                fh.write(data)
            print("  готово: bg_50k.txt (%d KB)" % (os.path.getsize(freq_path) // 1024))
            return freq_path
        except Exception as exc:
            print("  неуспех: %s" % exc)

    print("ВНИМАНИЕ: честотният списък не се свали. Целевите думи ще се "
          "избират без подредба по честота - рундовете ще са по-трудни.")
    return None


RUNTIME_TEMPLATE = """\
/* Генериран от tools/build_dictionary.py - не се редактира на ръка.
 *
 * Данните са .js, а не .json, нарочно: OBS зарежда browser source през
 * file://, където fetch() към локален файл се блокира от CORS. Script
 * таговете не минават през тази проверка.
 *
 * Думите са един низ, разделен с интервали, вместо JSON масив - спестява
 * около 220 KB и се разгъва с един split.
 *
 * Речник: %(words_count)d думи с дължина %(min_len)d-%(max_len)d.
 * Чести:  %(common_count)d думи, подредени по честота.
 */
(function (root) {
  "use strict";

  var DATA = {
    maxLength: %(max_len)d,
    minLength: %(min_len)d,
    words: "%(words)s".split(" "),
    common: "%(common)s".split(" ")
  };

  root.DUMICHKI_DATA = DATA;
  if (typeof module !== "undefined" && module.exports) { module.exports = DATA; }
})(typeof globalThis !== "undefined" ? globalThis : this);
"""


def write_runtime_bundle(path, words, common, min_len, max_len):
    """
    Записва пакета, който играта чете в браузъра.

    Съдържа само думите, които изобщо могат да се съставят от стойката -
    при стойка от 7 букви 8- и 9-буквените са мъртъв товар. Ако вдигнеш
    размера на стойката в конфигурацията, пусни скрипта наново с
    --runtime-max-len.
    """
    runtime_words = [w for w in words if len(w) <= max_len]
    runtime_common = [w for w in common if len(w) <= max_len]

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(RUNTIME_TEMPLATE % {
            "words": " ".join(runtime_words),
            "common": " ".join(runtime_common),
            "words_count": len(runtime_words),
            "common_count": len(runtime_common),
            "min_len": min_len,
            "max_len": max_len,
        })
    return runtime_words, runtime_common


def build_common(freq_path, valid_words, min_len, max_len):
    """
    Пресича честотния списък с разгънатия речник.

    Сечението върши двойна работа: маха правописните грешки и чуждиците от
    субтитрите, а от речника оставя само това, което хората наистина ползват.
    Редът се запазва - най-честата дума е първа.
    """
    common = []
    seen = set()
    with open(freq_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) != 2:
                continue
            word = parts[0].strip().lower()
            if word in seen:
                continue
            if reject_reason(word, min_len, max_len):
                continue
            if word not in valid_words:
                continue
            seen.add(word)
            common.append(word)
    return common


# --- Главна логика ----------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Строи words.json за играта Думички.")
    parser.add_argument("--min-len", type=int, default=3,
                        help="минимална дължина на дума (по подразбиране 3)")
    parser.add_argument("--max-len", type=int, default=9,
                        help="максимална дължина; играта ползва думи до размера "
                             "на стойката, 9 оставя запас (по подразбиране 9)")
    parser.add_argument("--out", default=DEFAULT_OUT, help="изходен JSON файл")
    parser.add_argument("--common-out", default=DEFAULT_COMMON_OUT,
                        help="изходен файл за честите думи")
    parser.add_argument("--runtime-out", default=DEFAULT_RUNTIME_OUT,
                        help="пакетът, който играта чете в браузъра")
    parser.add_argument("--runtime-max-len", type=int, default=7,
                        help="най-дългата дума в runtime пакета; трябва да е "
                             "поне колкото стойката (по подразбиране 7)")
    parser.add_argument("--offline", action="store_true",
                        help="не сваля нищо, ползва кеша в data/source/")
    parser.add_argument("--no-frequency", action="store_true",
                        help="пропуска честотния списък (не се препоръчва)")
    args = parser.parse_args()

    aff_path, dic_path = download(args.offline)

    print("\nЧета афиксните правила ...")
    rules, flag_mode, aliases = parse_aff(aff_path)
    n_sfx = sum(1 for rs in rules.values() for r in rs if r.kind == "SFX")
    n_pfx = sum(1 for rs in rules.values() for r in rs if r.kind == "PFX")
    print("  %d флага, %d суфиксни и %d префиксни правила (FLAG режим: %s)"
          % (len(rules), n_sfx, n_pfx, flag_mode))

    print("Разгъвам словоформите ...")
    with open(dic_path, "r", encoding="utf-8", errors="replace") as fh:
        dic_lines = fh.read().splitlines()

    # Първият ред на .dic е броят записи, ако е само число.
    if dic_lines and dic_lines[0].strip().isdigit():
        dic_lines = dic_lines[1:]

    words = set()
    rejected = Counter()
    stems_total = 0
    stems_capitalised = 0
    forms_generated = 0

    for line in dic_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Морфологичните полета са след табулация/интервал - режем ги.
        line = re.split(r"[\t ]", line, 1)[0]
        if not line:
            continue

        if "/" in line:
            stem, raw_flags = line.split("/", 1)
        else:
            stem, raw_flags = line, ""
        if not stem:
            continue

        stems_total += 1

        # Собствените имена отпадат още тук - иначе разгъваме стотици хиляди
        # форми, които после така или иначе изхвърляме.
        if any(ch.isupper() for ch in stem):
            stems_capitalised += 1
            rejected["главна буква (собствено име)"] += 1
            continue

        flags = parse_flags(raw_flags, flag_mode, aliases)
        for form in expand(stem, flags, rules):
            forms_generated += 1
            reason = reject_reason(form, args.min_len, args.max_len)
            if reason:
                rejected[reason] += 1
            else:
                words.add(form)

    result = sorted(words)

    # --- Честите думи -------------------------------------------------------

    common = []
    if not args.no_frequency:
        freq_path = download_frequency(args.offline)
        if freq_path:
            common = build_common(freq_path, words, args.min_len, args.max_len)

    # --- Статистика ---------------------------------------------------------

    by_length = Counter(len(w) for w in result)
    common_by_length = Counter(len(w) for w in common)
    vowel_free = sum(1 for w in result if not (VOWELS & set(w)))

    stats = {
        "източник": "hunspell bg_BG (BGoffice), LibreOffice/dictionaries",
        "основи_в_речника": stems_total,
        "основи_собствени_имена": stems_capitalised,
        "генерирани_словоформи": forms_generated,
        "думи_в_изхода": len(result),
        "мин_дължина": args.min_len,
        "макс_дължина": args.max_len,
        "по_дължина": {str(k): by_length[k] for k in sorted(by_length)},
        "отпаднали": dict(rejected.most_common()),
        "чести_думи": len(common),
        "чести_по_дължина": {str(k): common_by_length[k] for k in sorted(common_by_length)},
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, separators=(",", ":"))
    if common:
        os.makedirs(os.path.dirname(os.path.abspath(args.common_out)), exist_ok=True)
        with open(args.common_out, "w", encoding="utf-8") as fh:
            json.dump(common, fh, ensure_ascii=False, separators=(",", ":"))
    runtime_words, runtime_common = write_runtime_bundle(
        args.runtime_out, result, common, args.min_len, args.runtime_max_len)
    stats["runtime_думи"] = len(runtime_words)
    stats["runtime_чести"] = len(runtime_common)
    stats["runtime_макс_дължина"] = args.runtime_max_len

    stats_path = os.path.splitext(args.out)[0] + ".stats.json"
    with open(stats_path, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)

    size_mb = os.path.getsize(args.out) / (1024 * 1024)

    print("\n" + "=" * 52)
    print("РЕЧНИК ГОТОВ")
    print("=" * 52)
    print("Основи в hunspell речника : %8d" % stems_total)
    print("  от тях собствени имена  : %8d" % stems_capitalised)
    print("Генерирани словоформи     : %8d" % forms_generated)
    print("Думи в изхода             : %8d" % len(result))
    print("Файл                      : %s (%.1f MB)" % (args.out, size_mb))
    print("\nРазбивка по дължина:")
    total = len(result) or 1
    for length in sorted(by_length):
        count = by_length[length]
        bar = "#" * max(1, round(40 * count / max(by_length.values())))
        print("  %2d букви : %7d  (%5.1f%%)  %s" % (length, count, 100 * count / total, bar))

    print("\nОтпаднали форми:")
    for reason, count in rejected.most_common():
        print("  %-34s %9d" % (reason + ":", count))

    if common:
        common_size_kb = os.path.getsize(args.common_out) / 1024
        print("\n" + "-" * 52)
        print("ЧЕСТИ ДУМИ (за избор на семе и цели)")
        print("-" * 52)
        print("Думи                      : %8d  (%.1f%% от речника)"
              % (len(common), 100 * len(common) / total))
        print("Файл                      : %s (%.0f KB)"
              % (args.common_out, common_size_kb))
        print("Разбивка по дължина:")
        for length in sorted(common_by_length):
            print("  %2d букви : %7d" % (length, common_by_length[length]))

    # Зона за играта: семената са 6-7 букви, находките 3-7.
    print("\n" + "-" * 52)
    print("ГОДНОСТ ЗА ИГРАТА")
    print("-" * 52)
    print("Runtime пакет             : %s (%.1f MB)"
          % (args.runtime_out, os.path.getsize(args.runtime_out) / (1024 * 1024)))
    print("  думи до %d букви        : %8d" % (args.runtime_max_len, len(runtime_words)))
    print("  от тях чести            : %8d" % len(runtime_common))
    print("Семена 6-7 букви, чести   : %8d" % (common_by_length[6] + common_by_length[7]))
    print("Семена 6-7 букви, всички  : %8d" % (by_length[6] + by_length[7]))
    print("Находки 3-7 букви, всички : %8d" % sum(by_length[n] for n in range(3, 8)))
    if vowel_free:
        print("Думи без гласна           : %8d  (напр. %s)"
              % (vowel_free, ", ".join([w for w in result if not (VOWELS & set(w))][:5])))
    print("\nСтатистиката е записана и в %s" % stats_path)


if __name__ == "__main__":
    main()
