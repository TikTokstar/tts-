#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Прави звуците за играта.

Пуска се веднъж; после файловете в game/audio/ се сменят с каквито искаш,
стига имената да са същите. Играта не знае какво свири - само пуска файла.

    python3 tools/make_sounds.py

Без външни библиотеки. Три начина на звучене:

  дърпане   - струна по Karplus-Strong: шум, който се обикаля и се загасва.
              Звучи топло и живо, за разлика от гола синусоида.
  камбана   - честотна модулация: носеща вълна, разклатена от втора.
              Дава метален призвук, какъвто имат истинските звънчета.
  шум       - за разбъркването на стойката.

Всичко минава през проста реверберация - няколко закъснели и затихващи
копия. Без нея звуците са сухи като от телефон от 2003-та.
"""

import math
import os
import random
import struct
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "game", "audio")
RATE = 44100


# --- Обвивки ----------------------------------------------------------------

def envelope(length, attack=0.006, release=0.35):
    """Плавно вдигане и спадане - иначе щрака в началото и края."""
    out = []
    for i in range(length):
        t = i / length
        if t < attack:
            out.append(t / attack)
        elif t > 1 - release:
            out.append(max(0.0, (1 - t) / release) ** 1.4)
        else:
            out.append(1.0)
    return out


# --- Начини на звучене ------------------------------------------------------

def pluck(freq, seconds, volume=0.5, damping=0.016, seed=1):
    """
    Дърпана струна (Karplus-Strong).

    Кръгов буфер с шум, който при всяко обикаляне се осреднява със съседа
    си. Високите честоти изчезват първи - точно както при истинска струна.
    """
    rng = random.Random(seed)
    period = max(2, int(RATE / freq))
    buf = [rng.uniform(-1.0, 1.0) for _ in range(period)]

    # Заглаждаме началния шум, за да не почва с драскане.
    for _ in range(2):
        buf = [(buf[i] + buf[(i + 1) % period]) * 0.5 for i in range(period)]

    total = int(RATE * seconds)
    env = envelope(total, 0.002, 0.5)
    out = []
    idx = 0
    for i in range(total):
        value = buf[idx]
        out.append(value * env[i] * volume)
        nxt = (idx + 1) % period
        buf[idx] = (value + buf[nxt]) * 0.5 * (1.0 - damping)
        idx = nxt
    return out


def bell(freq, seconds, volume=0.5, ratio=2.76, index=3.2, decay=4.5):
    """
    Камбана през честотна модулация.

    Съотношението 2.76 не е кръгло нарочно - кръглите съотношения дават
    органна тръба, некръглите дават метал.
    """
    total = int(RATE * seconds)
    env = envelope(total, 0.004, 0.55)
    out = []
    for i in range(total):
        t = i / RATE
        fall = math.exp(-decay * t)
        modulator = math.sin(2 * math.pi * freq * ratio * t) * index * fall
        value = math.sin(2 * math.pi * freq * t + modulator)
        out.append(value * fall * env[i] * volume)
    return out


def noise_sweep(seconds, volume=0.25, seed=7):
    """Шум със спадаща яркост - за разбъркването."""
    rng = random.Random(seed)
    total = int(RATE * seconds)
    env = envelope(total, 0.02, 0.6)
    out = []
    state = 0.0
    for i in range(total):
        white = rng.uniform(-1.0, 1.0)
        cutoff = 0.5 - 0.44 * (i / total)   # започва ярко, потъмнява
        state += cutoff * (white - state)
        out.append(state * env[i] * volume)
    return out


# --- Обработка --------------------------------------------------------------

def reverb(samples, amount=0.3, tail=0.7):
    """
    Проста реверберация: няколко закъснели и затихващи копия.

    Закъсненията са прости числа в милисекунди, за да не се наслагват в
    ритъм и да не звучи като ехо в тунел.
    """
    length = len(samples)
    out = list(samples) + [0.0] * int(RATE * tail)

    for delay_ms, gain in ((23, 0.62), (37, 0.48), (53, 0.36), (71, 0.27), (97, 0.19)):
        step = int(RATE * delay_ms / 1000.0)
        for rep in range(1, 6):
            offset = step * rep
            weight = gain * amount * (0.52 ** (rep - 1))
            if weight < 0.004:
                break
            for i in range(length):
                j = i + offset
                if j < len(out):
                    out[j] += samples[i] * weight
    return out


def mix(*tracks):
    length = max(len(t) for t in tracks)
    out = [0.0] * length
    for track in tracks:
        for i, value in enumerate(track):
            out[i] += value
    return out


def delay(samples, seconds):
    return [0.0] * int(RATE * seconds) + samples


def soft_clip(samples):
    """Меко ограничаване вместо рязане - при пик звучи топло, не пращи."""
    return [math.tanh(s * 1.2) for s in samples]


def write(name, samples):
    path = os.path.join(OUT_DIR, name)
    samples = soft_clip(samples)
    peak = max(abs(s) for s in samples) or 1.0
    scale = 0.89 / peak

    with wave.open(path, "w") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(RATE)
        fh.writeframes(b"".join(
            struct.pack("<h", int(max(-1.0, min(1.0, s * scale)) * 32767))
            for s in samples
        ))
    print("  %-16s %5.2f s" % (name, len(samples) / RATE))


# Ла мажор - приветлив е и не се кара с музиката, която върви на стрийма.
A3, E4, A4, CS5, E5, A5, CS6, E6, A6 = (
    220.0, 329.63, 440.0, 554.37, 659.25, 880.0, 1108.73, 1318.51, 1760.0)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Правя звуците в %s:" % OUT_DIR)

    # Позната дума. Играта го пуска все по-високо с всяка следваща дума от
    # поредицата, затова е нисък и къс - има накъде да се качва. Дърпане
    # плюс камбанка отгоре: тялото идва от струната, блясъкът от камбаната.
    write("word.wav", reverb(mix(
        pluck(A5, 0.34, 0.60, damping=0.010, seed=3),
        delay(bell(CS6, 0.28, 0.20, ratio=3.1, index=2.4, decay=11), 0.012),
    ), amount=0.26, tail=0.5))

    # Намек - меко и въпросително, две ноти нагоре, без блясък.
    write("hint.wav", reverb(mix(
        bell(E4, 0.34, 0.30, ratio=1.41, index=1.5, decay=6),
        delay(bell(A4, 0.40, 0.26, ratio=1.41, index=1.4, decay=5.5), 0.13),
    ), amount=0.34, tail=0.6))

    # Разбъркване на стойката.
    write("shuffle.wav", reverb(noise_sweep(0.38, 0.34), amount=0.22, tail=0.4))

    # Край на ниво - най-дългият звук в играта. Разложен акорд нагоре,
    # струни отдолу за тяло, камбани отгоре за празничност.
    write("level-up.wav", reverb(mix(
        pluck(A3, 1.30, 0.42, damping=0.004, seed=11),
        delay(pluck(E4, 1.20, 0.38, damping=0.005, seed=12), 0.09),
        delay(pluck(A4, 1.15, 0.36, damping=0.006, seed=13), 0.18),
        delay(pluck(CS5, 1.10, 0.34, damping=0.007, seed=14), 0.27),
        delay(bell(A5, 1.00, 0.26, ratio=2.4, index=2.8, decay=3.2), 0.36),
        delay(bell(E6, 0.90, 0.18, ratio=2.9, index=2.2, decay=3.6), 0.46),
    ), amount=0.4, tail=1.0))

    # Край на рунд - две ноти надолу, без драма.
    write("round-end.wav", reverb(mix(
        pluck(E5, 0.45, 0.34, damping=0.014, seed=21),
        delay(pluck(A4, 0.60, 0.32, damping=0.010, seed=22), 0.17),
    ), amount=0.3, tail=0.6))

    # Всички думи намерени - по-ярко от обикновена дума, но по-кратко от ниво.
    write("round-clear.wav", reverb(mix(
        pluck(A5, 0.55, 0.40, damping=0.008, seed=31),
        delay(pluck(CS6, 0.50, 0.34, damping=0.009, seed=32), 0.08),
        delay(bell(A6, 0.55, 0.22, ratio=2.6, index=2.5, decay=5), 0.16),
    ), amount=0.34, tail=0.7))

    # Отброяване в паузата - тихо чукване, почти без опашка.
    write("countdown.wav", reverb(
        bell(E5, 0.12, 0.24, ratio=1.7, index=0.9, decay=26),
        amount=0.16, tail=0.2))

    print("\nГотово. За да смениш някой - сложи свой файл със същото име.")


if __name__ == "__main__":
    main()
