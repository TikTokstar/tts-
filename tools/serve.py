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


def open_server(host, port, tries=10):
    """Първият свободен порт от port нататък.

    Стар прозорец на сървъра държи 8080 дълго след затварянето му, а
    съобщението "портът е зает" не помага на никого по време на стрийм.
    """
    socketserver.TCPServer.allow_reuse_address = True
    last = None
    for offset in range(tries):
        try:
            return socketserver.TCPServer((host, port + offset), Handler)
        except OSError as exc:
            last = exc
    sys.exit("Не намирам свободен порт между %d и %d (%s)."
             % (port, port + tries - 1, last))


def check_folder():
    """Вика, ако папката е от стара версия.

    Най-честата грешка: няколко разархивирани папки в Изтегляния и сървърът
    тръгва от грешната. Тогава /quiz.html дава 404 и изглежда като счупен
    код, а всъщност просто липсва файлът.
    """
    missing = [name for name in ("index.html", "quiz.html")
               if not os.path.exists(os.path.join(GAME_DIR, name))]
    if not missing:
        return
    print()
    print("!" * 62)
    print("  ТАЗИ ПАПКА Е ОТ СТАРА ВЕРСИЯ - липсва %s" % ", ".join(missing))
    print()
    print("  Пуснал си сървъра от папка, в която този файл още го няма.")
    print("  Натисни 0-ОБНОВИ.bat, или свали архива наново и пусни")
    print("  5-ПУСНИ-СЪРВЪРА.bat от НОВАТА папка.")
    print("!" * 62)
    print()


def main():
    parser = argparse.ArgumentParser(description="Дава играта по HTTP.")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1",
                        help="127.0.0.1 значи само тази машина")
    args = parser.parse_args()

    check_folder()

    server = open_server(args.host, args.port)
    port = server.server_address[1]
    base = "http://%s:%d" % (args.host, port)

    if port != args.port:
        print("Портът %d е зает от друг прозорец - тръгвам на %d."
              % (args.port, port))
        print()

    print("Играта се дава от:")
    print("  %s" % GAME_DIR)
    print()
    print("  Адреси за browser източника:")
    print()
    print("    Думички        %s/index.html" % base)
    print("    Стани богат    %s/quiz.html" % base)
    print()
    print("  За проба, с измислени зрители:")
    print("    Думички        %s/index.html?source=mock" % base)
    print("    Стани богат    %s/quiz.html?source=mock" % base)
    print()
    print("  Проверка на връзката с чата:")
    print("    %s/chat-test.html" % base)
    print()
    print("Остави този прозорец отворен. Ctrl+C за спиране.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСпряно.")
        server.shutdown()


if __name__ == "__main__":
    main()
