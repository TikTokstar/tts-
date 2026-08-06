#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Дава играта на адрес http://localhost:8080 вместо от файл.

Нужно е само ако браузър източникът на програмата ти не приема път до
локален файл. OBS приема (има отметка "Local file"). TikTok Studio иска
адрес - тогава пусни това и подай адреса вместо пътя.

    python3 tools/serve.py

Не праща нищо навън и не иска интернет - слуша само на твоята машина.
"""

import argparse
import http.server
import os
import socketserver
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_DIR = os.path.join(ROOT, "game")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=GAME_DIR, **kwargs)

    def end_headers(self):
        # Браузър източникът кешира упорито; при промяна в config.js искаме
        # обновяването да се вижда веднага.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "304" not in (args[1] if len(args) > 1 else ""):
            sys.stdout.write("  %s\n" % (fmt % args))


def main():
    parser = argparse.ArgumentParser(description="Дава играта по HTTP.")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1",
                        help="127.0.0.1 значи само тази машина")
    args = parser.parse_args()

    socketserver.TCPServer.allow_reuse_address = True
    try:
        server = socketserver.TCPServer((args.host, args.port), Handler)
    except OSError as exc:
        sys.exit("Портът %d е зает (%s). Пробвай с --port 8081." % (args.port, exc))

    print("Играта се дава от %s" % GAME_DIR)
    print()
    print("  Сложи този адрес в браузър източника:")
    print("    http://%s:%d/index.html" % (args.host, args.port))
    print()
    print("  Проверка на връзката с чата:")
    print("    http://%s:%d/chat-test.html?debug=1" % (args.host, args.port))
    print()
    print("Ctrl+C за спиране.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСпряно.")
        server.shutdown()


if __name__ == "__main__":
    main()
