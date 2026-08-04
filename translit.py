#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
translit.py — шльокавица (български, писан на латиница/leet) -> кирилица.

Подходът НЕ е наивна таблица символ->символ. За всяка дума се генерират
кандидат-разчитания (защото много букви са двусмислени: y=й/ъ, c=ц/к, u=у/ю,
w=в/щ, i=и/й) и всеки кандидат се оценява спрямо българска честотна лексика
+ символен n-грам модел. Печели кандидатът с най-висока оценка.

Основни стъпки:
    1. Нормализация (NFC, разтягания "мноооого"->"много", CAPS, интервали).
    2. Токенизация + разпознаване на вида на всеки токен
       (кирилица / латиница / емоджи / URL / число / споменаване / пунктуация).
    3. За латинските токени — beam search над правилата (най-дългото
       съвпадение има предимство, но по-късите сегментации също се пробват,
       защото "ts" е ту "ц", ту "т"+"с": срв. "tsvete"->цвете, "otstrani"->отстрани).
    4. Решение на ниво СЪОБЩЕНИЕ дали е български или английски — една дума
       не стига ("be" е и английско, и българско "бе").
    5. Английските думи минават през фонетичен речник, за да ги изговори
       българският глас смислено ("ok"->"оукей"), а не буква по буква.

CLI:
    python translit.py "kak si be"
    python translit.py --repl
    python translit.py --explain "6te doida"
"""

from __future__ import annotations

import json
import logging
import math
import os
import pickle
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"

# ---------------------------------------------------------------------------
# Правила за транслитерация
# ---------------------------------------------------------------------------
# Всяко правило е: латински низ -> кортеж от (кирилски вариант, приоритет).
# "Приоритет" е бонус в log10 единици, който се добавя към оценката на
# кандидата. 0.0 = основният прочит, отрицателните са алтернативи, които
# печелят само ако лексиконът ги подкрепи силно.
#
# Оценката на позната дума е ~12..19, така че лексиконът винаги надделява
# над приоритетите — те решават само равенствата между непознати думи.

Rule = Tuple[Tuple[str, float], ...]

RULES: Dict[str, Rule] = {
    # --- триграфи -----------------------------------------------------
    "sht": (("щ", 0.0),),
    "sch": (("щ", 0.0),),
    "zht": (("жт", 0.0),),
    # --- диграфи ------------------------------------------------------
    "sh": (("ш", 0.0),),
    "ch": (("ч", 0.0),),
    "zh": (("ж", 0.0),),
    "ts": (("ц", 0.0), ("тс", -0.4)),
    "tz": (("ц", 0.0),),
    "kh": (("х", 0.0),),
    "dj": (("дж", 0.0),),
    "ya": (("я", 0.0),),
    "ja": (("я", -0.2),),
    "ia": (("я", 0.0), ("иа", -0.5)),
    "yu": (("ю", 0.0),),
    "ju": (("ю", -0.2),),
    "iu": (("ю", 0.0), ("иу", -0.6)),
    "yo": (("ьо", 0.0), ("йо", -0.2)),
    "io": (("йо", -0.2), ("ио", -0.3), ("ьо", -0.4)),
    "yi": (("ий", 0.0), ("и", -0.5)),
    "ai": (("ай", 0.0), ("аи", -0.4)),
    "ei": (("ей", 0.0), ("еи", -0.5)),
    "oi": (("ой", 0.0), ("ои", -0.5)),
    "ui": (("уй", -0.1), ("уи", -0.3)),
    "6t": (("щ", 0.0),),
    # --- единични букви ------------------------------------------------
    "a": (("а", 0.0), ("ъ", -1.3)),
    "b": (("б", 0.0),),
    "c": (("ц", 0.0), ("к", -0.3), ("с", -0.9)),
    "d": (("д", 0.0),),
    "e": (("е", 0.0),),
    "f": (("ф", 0.0),),
    "g": (("г", 0.0),),
    "h": (("х", 0.0),),
    "i": (("и", 0.0), ("й", -1.2)),
    "j": (("ж", 0.0), ("й", -0.7), ("дж", -1.0)),
    "k": (("к", 0.0),),
    "l": (("л", 0.0),),
    "m": (("м", 0.0),),
    "n": (("н", 0.0),),
    "o": (("о", 0.0),),
    "p": (("п", 0.0),),
    "q": (("я", 0.0),),
    "r": (("р", 0.0),),
    "s": (("с", 0.0),),
    "t": (("т", 0.0),),
    "u": (("у", 0.0), ("ю", -0.5), ("ъ", -1.0)),
    "v": (("в", 0.0),),
    "w": (("в", 0.0), ("щ", -0.6), ("у", -1.2)),
    "x": (("х", 0.0), ("кс", -0.3)),
    "y": (("й", 0.0), ("ъ", -0.4), ("и", -0.9)),
    "z": (("з", 0.0),),
    "'": (("ъ", 0.0),),
    "`": (("ъ", 0.0),),
    "y'": (("ъ", 0.0),),
}

# Leet цифри. Приоритетът им се изчислява контекстно в _digit_options():
# цифра ВЪТРЕ в дума почти винаги е буква ("ku4e"), а цифра в КРАЯ на дума
# по-често е число ("top10", "player123").
LEET_DIGITS: Dict[str, Rule] = {
    "4": (("ч", 0.0),),
    # "6" е "ш", но мнозина пишат "6astie" вместо "6tastie" — затова и "щ".
    "6": (("ш", 0.0), ("щ", -0.5)),
    "3": (("з", 0.0), ("е", -0.9)),
    "9": (("я", 0.0),),
    "1": (("и", 0.0),),
    "0": (("о", 0.0),),
    "8": (("б", 0.0),),
    "7": (("т", 0.0),),
    "5": (("с", 0.0),),
}

# Максимална дължина на ключ в RULES — за да знаем колко напред да гледаме.
_MAX_RULE_LEN = max(len(k) for k in RULES)

BG_ALPHABET = set("абвгдежзийклмнопрстуфхцчшщъьюя")
LATIN_ALPHABET = set("abcdefghijklmnopqrstuvwxyz")

# ---------------------------------------------------------------------------
# Оценяване: лексикон + символен n-грам модел
# ---------------------------------------------------------------------------

#: Бонус, който получава дума, намерена в лексикона. Достатъчно голям, за да
#: не може непозната дума да победи позната само заради приоритетите.
LEX_BONUS = 12.0
#: Тегло на n-грам оценката за непознати думи.
NGRAM_WEIGHT = 3.0
#: Разлика в оценките, над която токенът сам решава езика си,
#: без да пита останалата част от съобщението.
STRONG_MARGIN = 4.0


class CharModel:
    """Символен n-грам модел с add-k изглаждане."""

    def __init__(self, n: int = 3, k: float = 0.05) -> None:
        self.n = n
        self.k = k
        self.gram: Dict[str, float] = {}
        self.ctx: Dict[str, float] = {}
        self.alphabet: set = set()

    def train(self, word: str, weight: float) -> None:
        self.alphabet.update(word)
        s = "^" * (self.n - 1) + word + "$"
        for i in range(self.n - 1, len(s)):
            g = s[i - self.n + 1 : i + 1]
            c = g[:-1]
            self.gram[g] = self.gram.get(g, 0.0) + weight
            self.ctx[c] = self.ctx.get(c, 0.0) + weight

    @property
    def vocab(self) -> int:
        return max(len(self.alphabet) + 1, 2)

    def avg_logp(self, word: str, closed: bool = True) -> float:
        """Среден log10 на вероятността за символ. ~-1.0 добре, ~-3.0 боклук."""
        if not word:
            return -4.0
        s = "^" * (self.n - 1) + word + ("$" if closed else "")
        total = 0.0
        cnt = 0
        v = self.vocab
        for i in range(self.n - 1, len(s)):
            g = s[i - self.n + 1 : i + 1]
            c = g[:-1]
            num = self.gram.get(g, 0.0) + self.k
            den = self.ctx.get(c, 0.0) + self.k * v
            total += math.log10(num / den)
            cnt += 1
        return total / max(cnt, 1)


@dataclass
class Models:
    bg_lex: Dict[str, float] = field(default_factory=dict)
    en_lex: Dict[str, float] = field(default_factory=dict)
    bg_ngram: CharModel = field(default_factory=CharModel)
    en_ngram: CharModel = field(default_factory=CharModel)
    en_words: Dict[str, str] = field(default_factory=dict)
    en_phrases: Dict[str, str] = field(default_factory=dict)
    en_fallback: List[Tuple[str, str]] = field(default_factory=list)
    emoji_names: Dict[str, str] = field(default_factory=dict)


_MODELS: Optional[Models] = None
_CACHE_VERSION = 4


def _read_freq_file(path: Path) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not path.exists():
        log.warning("Липсва файл с честотен списък: %s", path)
        return out
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            word = parts[0].lower()
            try:
                count = float(parts[1])
            except ValueError:
                continue
            if count <= 0:
                continue
            out[word] = max(out.get(word, 0.0), count)
    return out


def _data_signature() -> tuple:
    sig = [_CACHE_VERSION]
    for name in ("bg_50k.txt", "en_50k.txt", "bg_slang.txt", "en_phonetic.json"):
        p = DATA_DIR / name
        if p.exists():
            st = p.stat()
            sig.append((name, int(st.st_mtime), st.st_size))
        else:
            sig.append((name, 0, 0))
    return tuple(sig)


def _build_models() -> Models:
    m = Models()
    m.bg_lex = _read_freq_file(DATA_DIR / "bg_50k.txt")
    for word, count in _read_freq_file(DATA_DIR / "bg_slang.txt").items():
        m.bg_lex[word] = max(m.bg_lex.get(word, 0.0), count)
    m.en_lex = _read_freq_file(DATA_DIR / "en_50k.txt")

    m.bg_ngram = CharModel()
    for word, count in m.bg_lex.items():
        m.bg_ngram.train(word, 1.0 + math.log10(count))
    m.en_ngram = CharModel()
    for word, count in m.en_lex.items():
        m.en_ngram.train(word, 1.0 + math.log10(count))

    phon_path = DATA_DIR / "en_phonetic.json"
    if phon_path.exists():
        raw = json.loads(phon_path.read_text(encoding="utf-8"))
        m.en_words = {k.lower(): v for k, v in raw.get("words", {}).items()}
        m.en_phrases = {k.lower(): v for k, v in raw.get("phrases", {}).items()}
        m.en_fallback = [(a, b) for a, b in raw.get("fallback_rules", [])]

    emoji_path = DATA_DIR / "emoji_bg.json"
    if emoji_path.exists():
        raw = json.loads(emoji_path.read_text(encoding="utf-8"))
        m.emoji_names = {k: v for k, v in raw.items() if not k.startswith("_")}
    return m


def get_models() -> Models:
    """Зарежда моделите (с дисков кеш, за да не се строят при всеки старт)."""
    global _MODELS
    if _MODELS is not None:
        return _MODELS

    sig = _data_signature()
    cache_file = CACHE_DIR / "translit_model.pkl"
    if cache_file.exists():
        try:
            with cache_file.open("rb") as fh:
                cached_sig, models = pickle.load(fh)
            if cached_sig == sig:
                _MODELS = models
                return _MODELS
        except Exception as exc:  # повреден кеш — просто го строим наново
            log.debug("Кешът на модела не се чете (%s), строя наново", exc)

    models = _build_models()
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        with tmp.open("wb") as fh:
            pickle.dump((sig, models), fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, cache_file)
    except Exception as exc:
        log.debug("Кешът на модела не може да се запише: %s", exc)

    _MODELS = models
    return _MODELS


def bg_score(word: str) -> float:
    m = get_models()
    c = m.bg_lex.get(word)
    if c:
        return LEX_BONUS + math.log10(c)
    return NGRAM_WEIGHT * m.bg_ngram.avg_logp(word)


def en_score(word: str) -> float:
    m = get_models()
    c = m.en_lex.get(word)
    if c:
        return LEX_BONUS + math.log10(c)
    return NGRAM_WEIGHT * m.en_ngram.avg_logp(word)


# ---------------------------------------------------------------------------
# Beam search за най-доброто разчитане на латинска дума
# ---------------------------------------------------------------------------

BEAM_WIDTH = 24


def _digit_options(word: str, pos: int) -> Rule:
    """Варианти за цифра — leet буква или самата цифра, според позицията."""
    ch = word[pos]
    letters = LEET_DIGITS.get(ch)
    if letters is None:
        return ((ch, 0.0),)
    # Опашка от цифри в края на дума ("top10", "gosho2005") — по-скоро число.
    tail_is_digits = all(c.isdigit() for c in word[pos:])
    has_letters_before = any(c.isalpha() for c in word[:pos])
    if tail_is_digits and has_letters_before:
        return ((ch, 0.0),) + tuple((l, p - 1.5) for l, p in letters)
    return letters + ((ch, -1.5),)


def _expand(word: str, pos: int) -> List[Tuple[int, Rule]]:
    """Всички правила, приложими на позиция pos. По-дългите са първи."""
    out: List[Tuple[int, Rule]] = []
    for length in range(min(_MAX_RULE_LEN, len(word) - pos), 0, -1):
        seg = word[pos : pos + length]
        rule = RULES.get(seg)
        if rule:
            out.append((length, rule))
    if not out:
        ch = word[pos]
        if ch.isdigit():
            out.append((1, _digit_options(word, pos)))
        else:
            out.append((1, ((ch, 0.0),)))
    elif word[pos].isdigit():
        out.append((1, _digit_options(word, pos)))
    return out


def candidates(word: str, beam: int = BEAM_WIDTH) -> List[Tuple[str, float]]:
    """Връща [(кирилски кандидат, оценка)] — сортирани, най-добрият пръв."""
    if not word:
        return []
    m = get_models()
    n = len(word)
    # позиция -> списък от (кирилица_дотук, сума_приоритети)
    by_pos: Dict[int, List[Tuple[str, float]]] = {0: [("", 0.0)]}

    for pos in range(n):
        states = by_pos.get(pos)
        if not states:
            continue
        # dedup + подрязване на лъча по частична оценка
        best: Dict[str, float] = {}
        for text, prior in states:
            if text not in best or prior > best[text]:
                best[text] = prior
        scored = [
            (t, p, NGRAM_WEIGHT * m.bg_ngram.avg_logp(t, closed=False) + p)
            for t, p in best.items()
        ]
        scored.sort(key=lambda x: x[2], reverse=True)
        states = [(t, p) for t, p, _ in scored[:beam]]
        by_pos[pos] = states

        for length, rule in _expand(word, pos):
            nxt = pos + length
            bucket = by_pos.setdefault(nxt, [])
            for cyr, prior_bonus in rule:
                for text, prior in states:
                    bucket.append((text + cyr, prior + prior_bonus))

    finals = by_pos.get(n, [])
    if not finals:
        return []
    best_final: Dict[str, float] = {}
    for text, prior in finals:
        if text not in best_final or prior > best_final[text]:
            best_final[text] = prior
    out = [(t, bg_score(t) + p) for t, p in best_final.items()]
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def transliterate_word(word: str) -> Tuple[str, float]:
    """Най-доброто кирилско разчитане на една латинска дума + оценката му."""
    cands = candidates(word)
    if not cands:
        return word, -99.0
    return cands[0]


# ---------------------------------------------------------------------------
# Английски -> кирилица (фонетично, за да го изговори българският глас)
# ---------------------------------------------------------------------------


def english_to_cyrillic(word: str) -> str:
    """Приблизителна фонетична транскрипция на английска дума."""
    m = get_models()
    known = m.en_words.get(word)
    if known:
        return known
    out: List[str] = []
    i = 0
    lower = word.lower()
    while i < len(lower):
        for src, dst in m.en_fallback:
            if lower.startswith(src, i):
                out.append(dst)
                i += len(src)
                break
        else:
            out.append(lower[i])
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Токенизация
# ---------------------------------------------------------------------------


class Kind(str, Enum):
    CYRILLIC = "cyrillic"
    TRANSLIT = "translit"
    ENGLISH = "english"
    EMOJI = "emoji"
    URL = "url"
    NUMBER = "number"
    MENTION = "mention"
    PUNCT = "punct"
    OTHER = "other"


@dataclass
class Token:
    raw: str
    kind: Kind
    out: str = ""
    score_bg: float = 0.0
    score_en: float = 0.0
    alternatives: List[str] = field(default_factory=list)


URL_RE = re.compile(
    r"""(?xi)
    \b(
        (?:https?://|www\.)\S+
        |
        [a-z0-9][a-z0-9\-]*\.(?:com|net|org|bg|io|me|tv|gg|ly|be|co|ru|info|xyz)
        (?:/\S*)?
    )
    """
)
MENTION_RE = re.compile(r"@[\w.\-]+")
_ZERO_WIDTH_RE = re.compile(r"[​-‏‪-‮﻿]")
_WS_RE = re.compile(r"\s+")
_REPEAT_RE = re.compile(r"(\w)\1{2,}", flags=re.UNICODE)

# Емоджи и пиктограми (грубо, но покрива каквото идва в чат).
EMOJI_RE = re.compile(
    "["
    "\U0001f000-\U0001faff"  # емоджи блокове
    "☀-➿"  # разни символи + dingbats
    "⬀-⯿"  # стрелки и фигури
    "←-⇿"  # стрелки
    "︀-️"  # variation selectors
    "‍"  # zero-width joiner (комбинирани емоджи)
    "⃣"  # keycap
    "™ℹ〰〽㊗㊙"
    "]+",
    flags=re.UNICODE,
)

_TOKEN_RE = re.compile(r"[0-9A-Za-zЀ-ӿ'`]+", flags=re.UNICODE)


def _collapse_repeats(text: str) -> str:
    """privetttt -> privet, мноооого -> много. Цифрите не се пипат."""

    def repl(match: re.Match) -> str:
        ch = match.group(1)
        if ch.isdigit():
            return match.group(0)
        return ch

    return _REPEAT_RE.sub(repl, text)


def prenormalize(text: str) -> str:
    """NFC, махане на невидими символи, свиване на интервалите.

    Съзнателно НЕ свива повторените букви — това става по-късно, само върху
    частите извън URL-ите ("www.example.com" не бива да стане "w.example.com").
    """
    text = unicodedata.normalize("NFC", text or "")
    text = _ZERO_WIDTH_RE.sub("", text)
    return _WS_RE.sub(" ", text).strip()


def normalize(text: str, collapse_repeats: bool = True) -> str:
    text = prenormalize(text)
    if collapse_repeats:
        text = _collapse_repeats(text)
    return _WS_RE.sub(" ", text).strip()


def _classify_raw(tok: str) -> Kind:
    has_cyr = any("Ѐ" <= c <= "ӿ" for c in tok)
    has_lat = any(c in LATIN_ALPHABET for c in tok.lower())
    has_digit = any(c.isdigit() for c in tok)
    if has_cyr:
        return Kind.CYRILLIC
    if has_lat:
        return Kind.TRANSLIT  # предварително; езикът се решава по-късно
    if has_digit:
        return Kind.NUMBER
    return Kind.OTHER


def _deshout(tok: str) -> str:
    """ВИКАНЕ -> викане. Оставя единичните главни букви на мира."""
    if len(tok) > 1 and tok.isupper():
        return tok.lower()
    return tok


#: Пунктуация, която пазим — дава на гласа паузи и интонация.
KEEP_PUNCT = ".,!?;:…"
_PUNCT_RE = re.compile(f"[{re.escape(KEEP_PUNCT)}]+")


# ---------------------------------------------------------------------------
# Основен вход
# ---------------------------------------------------------------------------


@dataclass
class TranslitOptions:
    #: "drop" (пропусни), "name" (прочети името), "keep" (остави символа)
    emoji_mode: str = "drop"
    #: с какво да се замени URL
    url_word: str = "линк"
    #: "read" (прочети името след @), "drop"
    mention_mode: str = "read"
    collapse_repeats: bool = True
    #: под тази оценка латинска дума се смята за английска, дори съобщението
    #: да е българско
    bg_floor: float = -14.0

    @classmethod
    def from_config(cls, cfg: dict) -> "TranslitOptions":
        section = (cfg or {}).get("translit", {}) or {}
        opts = cls()
        for key in (
            "emoji_mode",
            "url_word",
            "mention_mode",
            "collapse_repeats",
            "bg_floor",
        ):
            if key in section:
                setattr(opts, key, section[key])
        return opts


@dataclass
class TranslitResult:
    original: str
    text: str
    tokens: List[Token] = field(default_factory=list)
    language: str = "bg"

    def __str__(self) -> str:  # удобно за print()
        return self.text


#: Variation selectors и ZWJ — пречат на търсенето по символ, махаме ги.
_EMOJI_MODIFIERS = "︎️‍\U0001f3fb\U0001f3fc\U0001f3fd\U0001f3fe\U0001f3ff"


def _strip_emoji_modifiers(s: str) -> str:
    return "".join(c for c in s if c not in _EMOJI_MODIFIERS)


def _emoji_out(tok: str, opts: TranslitOptions) -> str:
    if opts.emoji_mode == "keep":
        return tok
    if opts.emoji_mode == "name":
        m = get_models()
        table = getattr(m, "_emoji_stripped", None)
        if table is None:
            table = {_strip_emoji_modifiers(k): v for k, v in m.emoji_names.items()}
            setattr(m, "_emoji_stripped", table)
        # Цялото емоджи (напр. знаме от два символа) има предимство.
        whole = _strip_emoji_modifiers(tok)
        if whole in table:
            return table[whole]
        names = [table.get(ch) for ch in whole]
        return " ".join(n for n in names if n)
    return ""


def analyze(text: str, opts: Optional[TranslitOptions] = None) -> TranslitResult:
    """Пълен анализ: връща изходния текст + разбивка по токени."""
    opts = opts or TranslitOptions()
    original = text or ""
    norm = prenormalize(original)
    if not norm:
        return TranslitResult(original=original, text="", tokens=[], language="bg")

    m = get_models()

    # 1) Изваждаме URL-и и споменавания преди да делим на думи.
    parts: List[Tuple[str, Optional[Kind]]] = []
    pos = 0
    special = sorted(
        [(mm.start(), mm.end(), Kind.URL) for mm in URL_RE.finditer(norm)]
        + [(mm.start(), mm.end(), Kind.MENTION) for mm in MENTION_RE.finditer(norm)]
    )
    taken_end = 0
    for start, end, kind in special:
        if start < taken_end:
            continue
        if start > pos:
            parts.append((norm[pos:start], None))
        parts.append((norm[start:end], kind))
        pos = taken_end = end
    if pos < len(norm):
        parts.append((norm[pos:], None))

    tokens: List[Token] = []

    # 2) Фразов речник преди делене на думи ("brawl stars").
    def apply_phrases(chunk: str) -> str:
        low = chunk.lower()
        for phrase, spoken in m.en_phrases.items():
            if phrase in low:
                idx = low.find(phrase)
                while idx != -1:
                    chunk = chunk[:idx] + spoken + chunk[idx + len(phrase) :]
                    low = chunk.lower()
                    idx = low.find(phrase, idx + len(spoken))
        return chunk

    for chunk, kind in parts:
        if kind is Kind.URL:
            tokens.append(Token(raw=chunk, kind=Kind.URL, out=opts.url_word))
            continue
        if kind is Kind.MENTION:
            if opts.mention_mode == "drop":
                tokens.append(Token(raw=chunk, kind=Kind.MENTION, out=""))
            else:
                name = chunk.lstrip("@")
                out, _ = transliterate_word(name.lower()) if name else ("", 0.0)
                tokens.append(Token(raw=chunk, kind=Kind.MENTION, out=out))
            continue

        # Разтяганията се свиват едва тук — URL-ите вече са извадени настрана.
        if opts.collapse_repeats:
            chunk = _collapse_repeats(chunk)
        chunk = apply_phrases(chunk)

        def emit_gap(gap: str) -> None:
            """Пазим емоджитата и пунктуацията от промеждутъците, по ред."""
            for piece in re.findall(
                f"{EMOJI_RE.pattern}|{_PUNCT_RE.pattern}", gap, flags=re.UNICODE
            ):
                if not piece.strip():
                    continue
                if _PUNCT_RE.fullmatch(piece):
                    # "!!!" -> "!" — гласът не се нуждае от три удивителни
                    tokens.append(
                        Token(raw=piece, kind=Kind.PUNCT, out=piece[0])
                    )
                else:
                    tokens.append(
                        Token(raw=piece, kind=Kind.EMOJI, out=_emoji_out(piece, opts))
                    )

        idx = 0
        for match in _TOKEN_RE.finditer(chunk):
            emit_gap(chunk[idx : match.start()])
            idx = match.end()
            tok = match.group(0)
            kind = _classify_raw(tok)
            t = Token(raw=tok, kind=kind)
            if kind is Kind.CYRILLIC:
                t.out = _deshout(tok)
            elif kind is Kind.NUMBER:
                t.out = tok
            elif kind is Kind.OTHER:
                t.out = tok
            tokens.append(t)
        emit_gap(chunk[idx:])

    # 3) Оценяваме всеки латински токен и в двата езика.
    latin_tokens = [t for t in tokens if t.kind is Kind.TRANSLIT]
    for t in latin_tokens:
        low = t.raw.lower()
        cands = candidates(low)
        if cands:
            t.out = cands[0][0]
            t.score_bg = cands[0][1]
            t.alternatives = [c for c, _ in cands[1:4]]
        else:
            t.out = low
            t.score_bg = -99.0
        t.score_en = en_score(low)

    # 4) Решение на ниво съобщение. Токен с цифри вътре в думата е почти
    #    сигурно шльокавица, а не английски.
    bg_weight = 0.0
    en_weight = 0.0
    for t in latin_tokens:
        low = t.raw.lower()
        w = float(len(low))
        if low in m.en_words or low in m.en_phrases:
            en_weight += w * 1.5
        elif _has_internal_digit(low):
            bg_weight += w * 1.5
        elif t.score_bg > t.score_en:
            bg_weight += w
        elif t.score_en > t.score_bg:
            en_weight += w
    message_is_bg = bg_weight >= en_weight

    # 5) Прилагаме решението per token, с право на вето при силни улики.
    for t in latin_tokens:
        low = t.raw.lower()
        forced_en = low in m.en_words or low in m.en_phrases
        strong_bg = _has_internal_digit(low) or (t.score_bg - t.score_en > STRONG_MARGIN)
        strong_en = t.score_en - t.score_bg > STRONG_MARGIN

        if forced_en or (strong_en and not strong_bg):
            use_bg = False
        elif strong_bg:
            use_bg = True
        else:
            use_bg = message_is_bg

        if use_bg and t.score_bg < opts.bg_floor:
            use_bg = False

        if not use_bg:
            t.kind = Kind.ENGLISH
            t.out = english_to_cyrillic(low)

    out_text = _join_tokens(tokens)
    return TranslitResult(
        original=original,
        text=out_text,
        tokens=tokens,
        language="bg" if message_is_bg else "en",
    )


def _has_internal_digit(word: str) -> bool:
    """Цифра, обградена от букви или в началото пред букви — leet, не число."""
    if not any(c.isdigit() for c in word):
        return False
    if not any(c.isalpha() for c in word):
        return False
    for i, ch in enumerate(word):
        if not ch.isdigit():
            continue
        after = word[i + 1 :]
        if any(c.isalpha() for c in after):
            return True
    return False


def _join_tokens(tokens: Sequence[Token]) -> str:
    parts: List[str] = []
    for t in tokens:
        if not t.out:
            continue
        if t.kind is Kind.PUNCT and parts:
            parts[-1] = parts[-1] + t.out
        else:
            parts.append(t.out)
    return _WS_RE.sub(" ", " ".join(parts)).strip()


def transliterate(text: str, opts: Optional[TranslitOptions] = None) -> str:
    """Кратък вход: текст -> текст за изговаряне."""
    return analyze(text, opts).text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _explain(text: str, opts: TranslitOptions) -> None:
    res = analyze(text, opts)
    print(f"вход : {res.original}")
    print(f"изход: {res.text}")
    print(f"език : {res.language}")
    print("-" * 68)
    print(f"{'токен':<16}{'вид':<11}{'изход':<16}{'bg':>8}{'en':>8}  алтернативи")
    print("-" * 68)
    for t in res.tokens:
        alts = ", ".join(t.alternatives[:3])
        print(
            f"{t.raw:<16}{t.kind.value:<11}{t.out:<16}"
            f"{t.score_bg:>8.2f}{t.score_en:>8.2f}  {alts}"
        )


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    opts = TranslitOptions()
    explain = False
    repl = False
    args: List[str] = []
    for a in argv:
        if a in ("--explain", "-e"):
            explain = True
        elif a in ("--repl", "-r"):
            repl = True
        elif a == "--emoji-name":
            opts.emoji_mode = "name"
        elif a in ("--help", "-h"):
            print(__doc__)
            return 0
        else:
            args.append(a)

    if repl or not args:
        print("Пиши на шльокавица (Ctrl+C за изход):")
        try:
            while True:
                try:
                    line = input("> ")
                except EOFError:
                    break
                if not line.strip():
                    continue
                if explain:
                    _explain(line, opts)
                else:
                    print(transliterate(line, opts))
        except KeyboardInterrupt:
            print()
        return 0

    text = " ".join(args)
    if explain:
        _explain(text, opts)
    else:
        print(transliterate(text, opts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
