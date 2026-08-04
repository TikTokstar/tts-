# -*- coding: utf-8 -*-
"""
Тестове за translit.py — шльокавица -> кирилица.

Пусни ги с:
    pytest -q
или без pytest:
    python tests/test_translit.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import translit  # noqa: E402
from translit import Kind, TranslitOptions  # noqa: E402


# ---------------------------------------------------------------------------
# Основен корпус: шльокавица -> кирилица
# ---------------------------------------------------------------------------

CASES = [
    # --- примерите от заданието ---
    ("kak si be", "как си бе"),
    ("6te doida", "ще дойда"),
    ("4ao", "чао"),
    ("6toto", "щото"),
    ("mnogo qko", "много яко"),
    ("ku4e", "куче"),
    ("zdr kvo stava", "здр кво става"),
    # --- диграфи и триграфи ---
    ("shte igraem li", "ще играем ли"),
    ("leka nosht", "лека нощ"),
    ("leka no6t", "лека нощ"),
    ("chestit rojden den", "честит рожден ден"),
    ("jivot", "живот"),
    ("jena", "жена"),
    ("chao", "чао"),
    ("vsichko", "всичко"),
    ("wsi4ko", "всичко"),
    ("kak se kazvash", "как се казваш"),
    ("nishto ne razbiram", "нищо не разбирам"),
    # --- двусмислици, които изискват оценка спрямо речника ---
    # 'ts' е ту "ц", ту "т"+"с"
    ("tsvete", "цвете"),
    ("otstrani", "отстрани"),
    # 'y' е ту "ъ", ту "й"
    ("kyde si", "къде си"),
    ("moyat", "моят"),
    # 'u' е ту "у", ту "ю", ту "ъ"
    ("utre", "утре"),
    ("lubov", "любов"),
    ("az sum tuk", "аз съм тук"),
    # 'a' понякога е "ъ"
    ("kade si bre", "къде си бре"),
    ("otkade si", "откъде си"),
    ("mnogo si dobar", "много си добър"),
    # 'ai' е ту "ай", ту "аи"
    ("naiven", "наивен"),
    ("mai 6te vali", "май ще вали"),
    ("daj mi edna pesen", "дай ми една песен"),
    # 'ia'/'q' -> я
    ("goliam pozdrav", "голям поздрав"),
    ("blagodarq", "благодаря"),
    ("priqtel", "приятел"),
    ("iavno", "явно"),
    ("nqma problem", "няма проблем"),
    # --- leet цифри ---
    ("6astie", "щастие"),
    ("ma4ka", "мачка"),
    ("4erven", "червен"),
    ("6te sum tuk", "ще съм тук"),
    # --- цели изречения ---
    ("ne moga da doida", "не мога да дойда"),
    ("kvo pravish", "кво правиш"),
    ("6te se vidim utre", "ще се видим утре"),
    ("mnogo ti blagodarq", "много ти благодаря"),
    ("dobro utro", "добро утро"),
    ("kolko e chasa", "колко е часа"),
    ("pusni mi pesen", "пусни ми песен"),
    ("ti si lud", "ти си луд"),
    ("vseki den", "всеки ден"),
    ("zdravei priqtel", "здравей приятел"),
    ("sladko", "сладко"),
    ("deca", "деца"),
]


@pytest.mark.parametrize("source,expected", CASES)
def test_transliteration(source, expected):
    assert translit.transliterate(source) == expected


# ---------------------------------------------------------------------------
# Нормализация
# ---------------------------------------------------------------------------

NORMALIZATION_CASES = [
    ("privetttt", "привет"),          # разтягане
    ("mnooooogo", "много"),
    ("MNOGO YAKO", "много яко"),      # ВИКАНЕ
    ("ЗДРАВЕЙ ВСИЧКИ", "здравей всички"),
    ("   kak   si   ", "как си"),     # интервали
    ("здравей как си", "здравей как си"),  # вече на кирилица — не се пипа
]


@pytest.mark.parametrize("source,expected", NORMALIZATION_CASES)
def test_normalization(source, expected):
    assert translit.transliterate(source) == expected


def test_digits_are_kept():
    assert translit.transliterate("1000") == "1000"
    assert "1000" in translit.transliterate("daj 1000 lv")


def test_trailing_digits_are_not_leet():
    # "gosho2005" е ник с година, а не "гошоцоос"
    assert translit.transliterate("gosho2005") == "гошо2005"
    assert translit.transliterate("top10") == "топ10"


def test_punctuation_survives_for_prosody():
    assert translit.transliterate("kak si be?") == "как си бе?"
    # но не и три удивителни
    assert translit.transliterate("mersi!!!") == "мерси!"


# ---------------------------------------------------------------------------
# Английски: НЕ се транслитерира буква по буква
# ---------------------------------------------------------------------------


def test_english_is_not_letter_mapped():
    res = translit.analyze("gg wp")
    kinds = {t.kind for t in res.tokens}
    assert Kind.TRANSLIT not in kinds
    # наивното пресмятане би дало "гг вп" — точно това не искаме
    assert res.text != "гг вп"
    assert res.text == "джиджи дабълю пи"


ENGLISH_CASES = [
    ("ok", "оукей"),
    ("lol", "лол"),
    ("gaming", "гейминг"),
    ("nice", "найс"),
    ("thx", "тенкс"),
    ("brawl stars", "броул старс"),
]


@pytest.mark.parametrize("source,expected", ENGLISH_CASES)
def test_english_phonetic_map(source, expected):
    assert translit.transliterate(source) == expected


def test_mixed_bg_and_english():
    assert translit.transliterate("wsi4ko e ok") == "всичко е оукей"
    assert translit.transliterate("pusni pesen pls") == "пусни песен плийз"
    assert translit.transliterate("brawl stars e qko") == "броул старс е яко"


def test_bulgarian_wins_over_english_lookalike():
    # "be" е честа английска дума, но в български контекст е "бе"
    assert translit.transliterate("kak si be") == "как си бе"
    # "si", "da", "ne" също са двусмислени сами по себе си
    assert translit.transliterate("da si dobre") == "да си добре"


def test_unknown_english_gets_phonetic_fallback():
    # непозната английска дума — не бива да излиза буквен боклук
    out = translit.transliterate("awesome gameplay")
    assert out and all(c not in out for c in "awesomeglpy")


# ---------------------------------------------------------------------------
# URL, споменавания, емоджи
# ---------------------------------------------------------------------------


def test_urls_become_link():
    assert translit.transliterate("pusni https://youtu.be/abc pls") == (
        "пусни линк плийз"
    )
    assert translit.transliterate("vij www.example.com") == "виж линк"


def test_mentions_are_read():
    assert translit.transliterate("@ivan zdr") == "иван здр"


def test_mentions_can_be_dropped():
    opts = TranslitOptions(mention_mode="drop")
    assert translit.transliterate("@ivan zdr", opts) == "здр"


def test_emoji_dropped_by_default():
    assert translit.transliterate("kak si 😂😂") == "как си"


def test_emoji_named_when_configured():
    opts = TranslitOptions(emoji_mode="name")
    assert translit.transliterate("privet 🔥", opts) == "привет огън"
    assert translit.transliterate("super ❤️", opts) == "супер сърце"


def test_pure_emoji_message_is_empty():
    assert translit.transliterate("😂😂😂") == ""


# ---------------------------------------------------------------------------
# Устойчивост — нищо не бива да гърми
# ---------------------------------------------------------------------------

WEIRD_INPUTS = [
    "",
    "   ",
    None,
    "!!!???",
    "\n\n\t",
    "a" * 500,
    "😀" * 50,
    "https://" + "x" * 300,
    "​​",
    "ＫＡＫ ＳＩ",
    "𝓴𝓪𝓴 𝓼𝓲",
    "'''''",
    "4" * 40,
]


@pytest.mark.parametrize("bad", WEIRD_INPUTS)
def test_does_not_crash(bad):
    out = translit.transliterate(bad)
    assert isinstance(out, str)


def test_analyze_returns_tokens():
    res = translit.analyze("kak si be")
    assert res.original == "kak si be"
    assert res.text == "как си бе"
    assert [t.raw for t in res.tokens] == ["kak", "si", "be"]
    assert all(t.kind is Kind.TRANSLIT for t in res.tokens)


def test_candidates_are_ranked():
    cands = translit.candidates("kyde")
    assert cands[0][0] == "къде"
    assert len(cands) > 1
    assert cands[0][1] >= cands[1][1]


def test_performance_is_realtime():
    """Транслитерацията не бива да е тясното място при < 1.5s латентност."""
    import time

    translit.transliterate("zagryava")  # моделът да е зареден
    msgs = ["kak si be", "6te doida sled malko", "mnogo qko igrae4 brat"] * 20
    start = time.perf_counter()
    for m in msgs:
        translit.transliterate(m)
    elapsed = time.perf_counter() - start
    per_msg = elapsed / len(msgs)
    assert per_msg < 0.05, f"{per_msg*1000:.1f} ms на съобщение е твърде бавно"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
