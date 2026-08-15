#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пази кодировките на файловете, които тръгват към Windows.

Тук няма нито cmd.exe, нито PowerShell, тоест грешка в кодировката се вижда
чак на чуждата машина - и се вижда като неразбираема грешка при разчитане,
не като "файлът е с грешна кодировка". Два пъти вече стана точно това.

    python3 tools/test_files.py
"""

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOM = b"\xef\xbb\xbf"

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  ✓ %s" % name)
    else:
        failed += 1
        print("  ✗ %s%s" % (name, "  -> " + str(detail) if detail else ""))


def lone_lf(data):
    """Редове с LF, който не е част от CRLF."""
    return data.replace(b"\r\n", b"").count(b"\n")


def main():
    print("Стартерите (.bat)")
    print("-" * 17)

    bats = sorted(glob.glob(os.path.join(ROOT, "*.bat")))
    check("стартерите са налице", len(bats) >= 8, "%d намерени" % len(bats))

    for path in bats:
        name = os.path.basename(path)
        data = open(path, "rb").read()

        # cmd.exe се спъва в блокове със скоби, ако редовете са само с LF.
        check("%s е с CRLF" % name, lone_lf(data) == 0,
              "%d реда само с LF" % lone_lf(data))

        # BOM в .bat се изпълнява като команда и дава грешка на първия ред.
        check("%s е без BOM" % name, not data.startswith(BOM))

        try:
            data.decode("utf-8")
            ok, why = True, ""
        except UnicodeDecodeError as exc:
            ok, why = False, str(exc)
        check("%s се чете като UTF-8" % name, ok, why)

    print("\nОбновяването (.ps1)")
    print("-" * 19)

    for path in sorted(glob.glob(os.path.join(ROOT, "tools", "*.ps1"))):
        name = os.path.basename(path)
        data = open(path, "rb").read()

        # Тук BOM-ът е задължителен, обратно на .bat: Windows PowerShell 5.1
        # чете скрипт без BOM като ANSI. Кирилицата се разпада на боклук и
        # развалените кавички чупят скрипта още при разчитането.
        check("%s започва с UTF-8 BOM" % name, data.startswith(BOM),
              "първи байтове: %r" % data[:4])
        check("%s е с CRLF" % name, lone_lf(data) == 0,
              "%d реда само с LF" % lone_lf(data))

        try:
            text = data.decode("utf-8-sig")
            ok, why = True, ""
        except UnicodeDecodeError as exc:
            text, ok, why = "", False, str(exc)
        check("%s се чете като UTF-8" % name, ok, why)

        if text:
            check("%s има четен брой прости кавички на ред" % name,
                  all(line.count("'") % 2 == 0 for line in text.splitlines()
                      if not line.lstrip().startswith("#")),
                  [line for line in text.splitlines()
                   if not line.lstrip().startswith("#") and line.count("'") % 2][:1])

    print("\n.gitattributes")
    print("-" * 14)

    rules = open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8").read()
    # Архивът от GitHub не преобразува нови редове, но локален клон на
    # Windows би го направил - тогава CRLF-ите горе не значат нищо.
    check("*.bat не се пипа от git", "*.bat -text" in rules)
    check("*.ps1 не се пипа от git", "*.ps1 -text" in rules)

    print("\nОбобщение")
    print("-" * 9)
    print("  минали: %d   паднали: %d" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
