#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Прави звуците за играта.

Пуска се веднъж; после файловете в game/audio/ се сменят с каквито искаш,
стига имената да са същите. Играта не знае какво свири - само пуска файла.

    python3 tools/make_sounds.py

Без външни библиотеки.

Какво се промени спрямо първия опит и защо:

  Дърпаната струна отпадна. Karplus-Strong при 880 Hz работи с буфер от
  петдесетина отчета - твърде малко, за да излезе струна, и звучеше като
  бръмчене. Сега тонът е събран от отделни съставки (адитивен синтез):
  всяка е синусоида със своя честота, сила и скорост на затихване. Така
  се прави звънче, което наистина звъни.

  Ударът отпред е отделен - две-три милисекунди шум. Ухото разпознава
  инструмента по началото; без него всеки тон звучи като от синтезатор.

  Реверберацията беше няколко закъснели копия и правеше метален звън.
  Сега е по Шрьодер: гребеновидни филтри в паралел, после алпас филтри
  в редица. Опашката излиза гладка, а не като ехо в тунел.

  Файловете са стерео. Едно и също нещо в двете уши звучи като телефон;
  малкото разминаване го изважда напред от музиката на стрийма.
"""

import math
import os
import random
import struct
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "game", "audio")
RATE = 44100


# --- Тонове -----------------------------------------------------------------

# Съставките на звънче: (честота спрямо основната, сила, скорост на затихване).
#
# Високите изчезват първи - затова числата в третата колона растат. Ако
# затихваха еднакво, звукът щеше да остане еднакво ярък до края и да звучи
# като орган.
#
# Отклоненията от кръглите числа (3.01, 4.16) са нарочни. Съвсем кръгли
# съотношения дават тръба; малкото разминаване дава метал и стъкло.
CHIME = [
    (1.00, 1.00, 2.6),
    (2.00, 0.46, 4.0),
    (3.01, 0.26, 5.6),
    (4.16, 0.14, 7.4),
    (5.43, 0.08, 9.5),
    (6.79, 0.05, 12.0),
    (8.21, 0.03, 15.0),
]

# По-мек глас, за неща, които не бива да блестят: намек, край на рунд.
WOOD = [
    (1.00, 1.00, 3.4),
    (2.00, 0.30, 5.2),
    (3.00, 0.12, 7.0),
    (4.07, 0.05, 9.0),
]


def tone(freq, seconds, volume=0.5, partials=CHIME, attack=0.003, detune=0.0):
    """Тон, събран от съставките си.

    detune разстройва високите съставки съвсем леко. Истинските звънчета
    никога не са идеално настроени и точно това ги прави живи.
    """
    total = int(RATE * seconds)
    out = [0.0] * total
    strength = sum(p[1] for p in partials)

    for ratio, amp, decay in partials:
        w = 2 * math.pi * freq * ratio * (1.0 + detune * (ratio - 1.0))
        gain = volume * amp / strength
        for i in range(total):
            t = i / RATE
            out[i] += math.sin(w * t) * math.exp(-decay * t) * gain

    # Кратко вдигане отпред: без него първият отчет скача от нулата и щрака.
    ramp = max(1, int(RATE * attack))
    for i in range(min(ramp, total)):
        out[i] *= i / ramp

    return fade_tail(out)


def mallet(seconds=0.004, volume=0.35, seed=1, bright=0.75):
    """Ударът на чукчето - шум, който трае колкото едно мигване.

    Това е разликата между "звънче" и "синусоида". Ухото разпознава
    инструмента по първите милисекунди.
    """
    rng = random.Random(seed)
    total = int(RATE * seconds)
    out = []
    state = 0.0
    for i in range(total):
        white = rng.uniform(-1.0, 1.0)
        state += bright * (white - state)
        out.append(state * (1.0 - i / total) ** 2 * volume)
    return out


def noise_sweep(seconds, volume=0.25, seed=7, start=0.55, end=0.05):
    """Шум със спадаща яркост - за разбъркването на стойката."""
    rng = random.Random(seed)
    total = int(RATE * seconds)
    out = []
    state = 0.0
    for i in range(total):
        white = rng.uniform(-1.0, 1.0)
        cutoff = start + (end - start) * (i / total)
        state += cutoff * (white - state)
        # Плавно отваряне и затваряне, за да няма щракане в двата края.
        shape = math.sin(math.pi * (i / total)) ** 0.7
        out.append(state * shape * volume)
    return out


def sub(freq, seconds, volume=0.2, decay=9.0):
    """Тих нисък тон под основния - дава тежест, без да се чува отделно."""
    total = int(RATE * seconds)
    out = []
    for i in range(total):
        t = i / RATE
        out.append(math.sin(2 * math.pi * freq * t) * math.exp(-decay * t) * volume)
    return fade_tail(out)


# --- Слепване ---------------------------------------------------------------

def fade_tail(samples, seconds=0.02):
    """Гаси последните милисекунди до нула - иначе краят на файла щрака."""
    n = min(len(samples), int(RATE * seconds))
    for i in range(n):
        samples[len(samples) - n + i] *= 1.0 - i / n
    return samples


def mix(*tracks):
    length = max(len(t) for t in tracks)
    out = [0.0] * length
    for track in tracks:
        for i, value in enumerate(track):
            out[i] += value
    return out


def delay(samples, seconds):
    return [0.0] * int(RATE * seconds) + samples


def pad(samples, seconds):
    """Място отзад, в което опашката на реверберацията да се побере."""
    return list(samples) + [0.0] * int(RATE * seconds)


# --- Реверберация по Шрьодер ------------------------------------------------
#
# Четири гребеновидни филтъра в паралел правят плътността, два алпас филтъра
# след тях разбъркват фазата, за да не се чуват отделните повторения.
# Дължините са прости числа, за да не си съвпадат повторенията.

COMBS = (1116, 1188, 1277, 1356)
ALLPASS = (556, 441)


def comb(samples, size, feedback, damp):
    buf = [0.0] * size
    out = [0.0] * len(samples)
    store = 0.0
    idx = 0
    for i, value in enumerate(samples):
        heard = buf[idx]
        out[i] = heard
        # Всяко обикаляне отнема малко от високите - иначе опашката съска.
        store = heard * (1.0 - damp) + store * damp
        buf[idx] = value + store * feedback
        idx += 1
        if idx == size:
            idx = 0
    return out


def allpass(samples, size, gain=0.5):
    buf = [0.0] * size
    out = [0.0] * len(samples)
    idx = 0
    for i, value in enumerate(samples):
        heard = buf[idx]
        out[i] = heard - value
        buf[idx] = value + heard * gain
        idx += 1
        if idx == size:
            idx = 0
    return out


def reverb(samples, amount=0.28, room=0.80, damp=0.35, spread=23):
    """Връща (ляво, дясно).

    spread размества дясната страна с няколко отчета. Толкова е достатъчно
    за усещане за ширина; повече започва да звучи като две различни неща.
    """
    def wet(offset):
        total = [0.0] * len(samples)
        for size in COMBS:
            part = comb(samples, size + offset, room, damp)
            for i, value in enumerate(part):
                total[i] += value * 0.25
        for size in ALLPASS:
            total = allpass(total, size + offset)
        return total

    left_wet = wet(0)
    right_wet = wet(spread)

    left = [samples[i] + left_wet[i] * amount for i in range(len(samples))]
    right = [samples[i] + right_wet[i] * amount for i in range(len(samples))]
    return fade_tail(left), fade_tail(right)


# --- Запис ------------------------------------------------------------------

def soft_clip(samples):
    """Меко ограничаване вместо рязане - при пик звучи топло, не пращи."""
    return [math.tanh(s * 1.1) for s in samples]


def write(name, stereo, loudness=0.16):
    """Изравнява по усетена сила, не по връх.

    Изравняването по връх правеше късите звуци тихи, а дългите - силни:
    един връх не казва нищо за това колко силно се чува нещо. Затова се
    мери средната енергия, а върхът само се пази да не излезе от скалата.
    """
    left, right = stereo
    length = max(len(left), len(right))
    left = left + [0.0] * (length - len(left))
    right = right + [0.0] * (length - len(right))

    energy = sum(s * s for s in left) + sum(s * s for s in right)
    rms = math.sqrt(energy / (2 * length)) or 1.0
    scale = loudness / rms

    peak = max(max(abs(s) for s in left), max(abs(s) for s in right)) * scale
    if peak > 0.92:
        scale *= 0.92 / peak

    frames = bytearray()
    for i in range(length):
        for channel in (left, right):
            value = math.tanh(channel[i] * scale * 1.1)
            frames += struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767))

    with wave.open(os.path.join(OUT_DIR, name), "w") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(RATE)
        fh.writeframes(bytes(frames))

    print("  %-16s %4.2f s" % (name, length / RATE))


# Ла мажор - приветлив е и не се кара с музиката, която върви на стрийма.
A3, E4, A4, CS5, E5, FS5, A5, B5, CS6, E6 = (
    220.0, 329.63, 440.0, 554.37, 659.25, 739.99, 880.0, 987.77, 1108.73, 1318.51)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Правя звуците в %s:" % OUT_DIR)

    # --- Позната дума ------------------------------------------------------
    #
    # Този се чува най-често, значи трябва да е кратък, ясен и да не омръзва.
    # Две звънчета през квинта, второто с 55 ms закъснение: излиза "дзън-дзън"
    # вместо едно "дзън", а това се усеща като награда, не като известие.
    #
    # Основната е E5, а не по-високо, защото играта го транспонира нагоре с
    # всяка следваща дума от поредицата - до 1.9 пъти. От E5 таванът е поносим;
    # от A5 щеше да боде.
    write("word.wav", reverb(pad(mix(
        mallet(0.004, 0.30, seed=3),
        tone(E5, 0.60, 0.55, detune=0.004),
        delay(mallet(0.003, 0.20, seed=4), 0.055),
        delay(tone(B5, 0.50, 0.34, detune=0.005), 0.055),
        sub(E4, 0.18, 0.16, decay=16),
    ), 0.5), amount=0.30, room=0.76))

    # --- Намек -------------------------------------------------------------
    #
    # Меко и въпросително: две ноти нагоре, дървен глас, без блясък. Намекът
    # е помощ, не събитие - не бива да дърпа вниманието от думата.
    write("hint.wav", reverb(pad(mix(
        mallet(0.005, 0.14, seed=9, bright=0.4),
        tone(E4, 0.55, 0.42, partials=WOOD),
        delay(tone(A4, 0.60, 0.38, partials=WOOD), 0.15),
    ), 0.6), amount=0.34, room=0.80, damp=0.5))

    # --- Разбъркване на стойката -------------------------------------------
    #
    # Шум, който тръгва ярък и потъмнява - като разбъркване на плочки.
    write("shuffle.wav", reverb(pad(
        noise_sweep(0.34, 0.30, start=0.6, end=0.04), 0.35),
        amount=0.20, room=0.70, damp=0.55))

    # --- Край на ниво ------------------------------------------------------
    #
    # Най-дългият звук в играта, единственият, на който е позволено да се
    # разлее. Разложен акорд нагоре, с тежест отдолу и звънчета отгоре.
    write("level-up.wav", reverb(pad(mix(
        sub(A3, 0.9, 0.22, decay=3.2),
        mallet(0.005, 0.22, seed=11),
        tone(A4, 1.30, 0.44, detune=0.003),
        delay(tone(CS5, 1.20, 0.40, detune=0.003), 0.10),
        delay(tone(E5, 1.15, 0.38, detune=0.004), 0.20),
        delay(mallet(0.004, 0.18, seed=12), 0.30),
        delay(tone(A5, 1.10, 0.36, detune=0.005), 0.30),
        delay(tone(CS6, 0.95, 0.24, detune=0.006), 0.40),
        delay(tone(E6, 0.85, 0.16, detune=0.007), 0.48),
    ), 1.1), amount=0.42, room=0.85, damp=0.28))

    # --- Край на рунд ------------------------------------------------------
    #
    # Две ноти надолу, дървено и тихо. Рундът свършва често - ако този звук
    # звучи като провал, играта става уморителна.
    write("round-end.wav", reverb(pad(mix(
        mallet(0.005, 0.12, seed=21, bright=0.35),
        tone(A4, 0.60, 0.40, partials=WOOD),
        delay(tone(E4, 0.75, 0.36, partials=WOOD), 0.16),
    ), 0.6), amount=0.30, room=0.78, damp=0.5), loudness=0.13)

    # --- Всички думи намерени ----------------------------------------------
    #
    # По-ярко от обикновена дума, по-късо от ниво. Три звънчета нагоре.
    write("round-clear.wav", reverb(pad(mix(
        mallet(0.004, 0.26, seed=31),
        tone(A5, 0.70, 0.48, detune=0.004),
        delay(tone(CS6, 0.62, 0.36, detune=0.005), 0.08),
        delay(tone(E6, 0.58, 0.26, detune=0.006), 0.16),
        sub(A4, 0.2, 0.14, decay=14),
    ), 0.7), amount=0.34, room=0.80))

    # --- Отброяване --------------------------------------------------------
    #
    # Тихо чукване, почти без опашка. Чува се пет пъти подред - всяко
    # излишно звънтене тук се превръща в дразнене.
    write("countdown.wav", reverb(pad(mix(
        mallet(0.003, 0.22, seed=41, bright=0.5),
        tone(A5, 0.14, 0.30, partials=WOOD),
    ), 0.18), amount=0.14, room=0.60, damp=0.6), loudness=0.11)

    print("\nГотово. За да смениш някой - сложи свой файл със същото име.")


if __name__ == "__main__":
    main()
