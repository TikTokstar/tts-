#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пуска всички тестове и казва накрая какво е паднало.

    python3 tools/test_all.py

Ядрото иска node, останалите три искат playwright. Ако нещо липсва,
съответният пакет се прескача с обяснение, вместо да вали всичко.
"""

import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SUITES = [
    ("ядро", ["node", "tools/test_core.js"], "node"),
    ("чат", [sys.executable, "tools/test_chat.py"], "playwright"),
    ("overlay", [sys.executable, "tools/test_overlay.py"], "playwright"),
    ("конфигурация", [sys.executable, "tools/test_config.py"], "playwright"),
    ("викторина", [sys.executable, "tools/test_quiz.py"], "playwright"),
]


def have(requirement):
    if requirement == "node":
        return shutil.which("node") is not None
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def main():
    results = []
    for name, command, requirement in SUITES:
        if not have(requirement):
            print("~ %-14s прескочен (липсва %s)" % (name, requirement))
            results.append((name, None, 0))
            continue

        print("→ %s ..." % name, flush=True)
        started = time.time()
        finished = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        seconds = time.time() - started
        ok = finished.returncode == 0
        results.append((name, ok, seconds))

        if ok:
            print("  ✓ %s за %.0f s" % (name, seconds))
        else:
            print("  ✗ %s за %.0f s" % (name, seconds))
            for line in finished.stdout.splitlines():
                if line.strip().startswith("✗") or "паднали" in line:
                    print("      " + line.strip())
            if finished.stderr.strip():
                print("      " + finished.stderr.strip().splitlines()[-1])

    print("\n" + "=" * 40)
    failed = [name for name, ok, _ in results if ok is False]
    skipped = [name for name, ok, _ in results if ok is None]

    if failed:
        print("ПАДНАЛИ: " + ", ".join(failed))
    else:
        print("Всичко минава.")
    if skipped:
        print("Прескочени: " + ", ".join(skipped))

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
