#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Прави звуците за играта.

Пуска се веднъж; после файловете в game/audio/ се сменят с каквито искаш,
стига имената да са същите. Играта не знае какво свири - само пуска файла.

    python3 tools/make_sounds.py

Без външни библиотеки: чист синтез със стандартния модул wave.
"""

import math
import os
import struct
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "game", "audio")
RATE = 44100


def envelope(i, total, attack=0.01, release=0.35):
    """Плавно вдигане и спадане, за да няма щракане в началото и края."""
    t = i / total
    if t < attack:
        return t / attack
    if t > 1 - release:
        return max(0.0, (1 - t) / release)
    return 1.0


def tone(freq, seconds, volume=0.5, harmonics=(1.0, 0.32, 0.12), decay=3.0):
    """Един тон с няколко обертона - иначе звучи като телефонен сигнал."""
    total = int(RATE * seconds)
    samples = []
    for i in range(total):
        t = i / RATE
        value = 0.0
        for n, weight in enumerate(harmonics, start=1):
            value += weight * math.sin(2 * math.pi * freq * n * t)
        value *= math.exp(-decay * t) * envelope(i, total) * volume
        samples.append(value)
    return samples


def noise_sweep(seconds, volume=0.25):
    """Шум със спадаща височина - за разбъркването на стойката."""
    total = int(RATE * seconds)
    samples = []
    state = 0.0
    seed = 12345
    for i in range(total):
        seed = (1103515245 * seed + 12345) % (1 << 31)
        white = (seed / (1 << 30)) - 1.0
        # Плъзгащ филтър: започва ярко и потъмнява.
        cutoff = 0.55 - 0.45 * (i / total)
        state += cutoff * (white - state)
        samples.append(state * envelope(i, total, 0.02, 0.55) * volume)
    return samples


def mix(*tracks):
    """Наслагва писти с различна дължина."""
    length = max(len(t) for t in tracks)
    out = [0.0] * length
    for track in tracks:
        for i, value in enumerate(track):
            out[i] += value
    return out


def delay(samples, seconds):
    return [0.0] * int(RATE * seconds) + samples


def write(name, samples):
    path = os.path.join(OUT_DIR, name)
    peak = max(abs(s) for s in samples) or 1.0
    scale = min(1.0, 0.89 / peak)  # оставяме малко въздух, за да не пращи

    with wave.open(path, "w") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(RATE)
        fh.writeframes(b"".join(
            struct.pack("<h", int(max(-1.0, min(1.0, s * scale)) * 32767))
            for s in samples
        ))
    print("  %-16s %5.2f s" % (name, len(samples) / RATE))


# Нотите са в ла-мажор - звучат приветливо и не се карат с музиката на стрийма.
A4, CS5, E5, A5, CS6, E6 = 440.0, 554.37, 659.25, 880.0, 1108.73, 1318.51


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Правя звуците в %s:" % OUT_DIR)

    # Позната дума. Играта го пуска все по-високо с всяка следваща дума от
    # поредицата, затова тук е нисък и къс - има накъде да се качва.
    write("word.wav", mix(
        tone(A5, 0.26, 0.55, decay=9),
        delay(tone(CS6, 0.24, 0.34, decay=11), 0.045),
    ))

    # Намек - меко и въпросително, две ноти нагоре.
    write("hint.wav", mix(
        tone(CS5, 0.30, 0.34, decay=6),
        delay(tone(E5, 0.34, 0.30, decay=6), 0.12),
    ))

    # Разбъркване на стойката.
    write("shuffle.wav", noise_sweep(0.42, 0.30))

    # Край на ниво - възходящо разлагане, най-дългият звук в играта.
    write("level-up.wav", mix(
        tone(A4, 1.10, 0.40, decay=2.2),
        delay(tone(CS5, 1.00, 0.38, decay=2.4), 0.10),
        delay(tone(E5, 0.95, 0.36, decay=2.6), 0.20),
        delay(tone(A5, 1.20, 0.42, decay=1.8), 0.32),
        delay(tone(CS6, 1.00, 0.24, decay=2.4), 0.44),
    ))

    # Край на рунд - две ноти надолу, без драма.
    write("round-end.wav", mix(
        tone(E5, 0.40, 0.34, decay=5),
        delay(tone(A4, 0.55, 0.32, decay=4), 0.16),
    ))

    # Отброяване в паузата - тихо чукване.
    write("countdown.wav", tone(E5, 0.10, 0.22, harmonics=(1.0, 0.18), decay=22))

    # Всички думи намерени - по-ярко от обикновена дума.
    write("round-clear.wav", mix(
        tone(A5, 0.55, 0.40, decay=4),
        delay(tone(CS6, 0.50, 0.34, decay=4.5), 0.08),
        delay(tone(E6, 0.60, 0.30, decay=4), 0.16),
    ))

    print("\nГотово. За да смениш някой - сложи свой файл със същото име.")


if __name__ == "__main__":
    main()
