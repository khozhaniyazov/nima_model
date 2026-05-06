"""Localization helper for deterministic scene templates.

The streaming LLM path honours a target language via ``NIMA_LANGUAGE_LOCK``
(see ``_build_stream_system_msg`` in ``streaming.py``).  When a scene falls
back to a deterministic template (``_make_*_fallback_scene_code``), the
English literals baked into those templates were previously emitted as-is,
breaking language consistency for non-English renders.

This module provides a small phrase lookup so the deterministic templates can
produce locale-aware ``Text(...)`` labels without a round-trip through the
LLM.  It is intentionally narrow:

* Single env var ``NIMA_LANGUAGE_LOCK`` (same one the streaming system prompt
  reads) drives locale selection.
* A phrase that is not in the lookup returns unchanged — the deterministic
  fallback is a safety net, not a preferred path, so "still partly English"
  is acceptable while "blow up on missing phrase" is not.
* Behaviour when ``NIMA_LANGUAGE_LOCK`` is unset is byte-for-byte identical
  to having no i18n layer at all.
"""

from __future__ import annotations

import os
import re
from typing import Mapping

# --- Locale normalisation -------------------------------------------------

_KAZAKH_TOKENS = ("kazakh", "қазақ", "kaz", "kk")


def _normalize_locale(raw: str) -> str:
    """Map a freeform ``NIMA_LANGUAGE_LOCK`` value to a short locale key.

    The env var can be set to rich strings like ``"Kazakh (Қазақ тілі, Cyrillic
    script)"`` — we only need to decide which translation table to use.
    """
    if not raw:
        return ""
    lowered = raw.lower()
    for token in _KAZAKH_TOKENS:
        if token in lowered:
            return "kk"
    return ""


def current_locale() -> str:
    """Return the short locale key active for this process, or ``""``."""
    return _normalize_locale(os.environ.get("NIMA_LANGUAGE_LOCK", "").strip())


def is_locale_active() -> bool:
    return bool(current_locale())


# --- Phrase tables --------------------------------------------------------

# Kazakh translations for the literal strings baked into deterministic
# scene templates.  Keys are the exact English source strings so lookup is a
# trivial ``TRANSLATIONS[locale].get(phrase, phrase)``.
_KK: Mapping[str, str] = {
    # Standard-mode chapter titles (from algorithms.standard blueprint).
    "Cold Open": "Күтпеген бастама",
    "The Setup": "Құрылым",
    "Naive Attempt": "Аңқау әдіс",
    "Core Mechanism": "Негізгі тетік",
    "Worked Example": "Шешілген мысал",
    "Pattern Break": "Қате үлгі",
    "Payoff": "Пайдасы",
    "Clean Takeaway": "Таза қорытынды",
    # Common fallback labels + payoffs (standard mode).
    "target": "нысан",
    "mid": "орта",
    "comparisons": "салыстырулар",
    "remaining": "қалғаны",
    "keep right half": "оң жартысын қалдыр",
    "keep left half": "сол жартысын қалдыр",
    "One comparison deletes half the map": "Бір салыстыру картаның жартысын жояды",
    "linear search earns certainty one cell at a time": (
        "сызықтық іздеу бір-бірден сенім жинайды"
    ),
    "easy to trust, expensive to repeat": "сенуге оңай, қайталауға қымбат",
    "unsorted: no safe half": "реттелмеген: қауіпсіз жарты жоқ",
    "sorted: halves mean something": "реттелген: жартылардың мәні бар",
    "binary search buys speed with order": "екілік іздеу жылдамдықты реттілікпен сатып алады",
    "without order, the jump is a guess": "реттіліксіз секіру — тек болжам",
    "the gap gets bigger as the list grows": "тізім өскен сайын айырмашылық ұлғаяды",
    "linear checks": "сызықтық тексерулер",
    "binary checks": "екілік тексерулер",
    "cutting beats counting": "бөлу санаудан жеңеді",
    "is the data sorted?": "мәліметтер реттелген бе?",
    "use binary search": "екілік іздеуді қолдан",
    "linear still works": "сызықтық әлі де жұмыс істейді",
    "yes": "иә",
    "no": "жоқ",
    "same problem, different promise": "бір есеп, басқа уәде",
    "same target, different tempo": "бір нысан, басқа қарқын",
    "linear scan": "сызықтық шолу",
    "binary split": "екілік бөлу",
    "binary: 4 jumps": "екілік: 4 секіру",
    "every question halves the uncertainty": "әр сұрақ белгісіздікті екіге бөледі",
    "16 candidates": "16 үміткер",
    "8 remain": "8 қалды",
    "4 remain": "4 қалды",
    "2 remain": "2 қалды",
    "1 answer": "1 жауап",
    "bad version:": "нашар нұсқа:",
    "check one item": "бір элементті тексер",
    "then another": "сосын тағы бірін",
    "then another...": "сосын тағы...",
    "good version:": "жақсы нұсқа:",
    "ask the midpoint": "ортасын сұра",
    "throw away half": "жартысын алып таста",
    "repeat with focus": "фокуспен қайтала",
    "16 items need only 4 clean cuts": "16 элементке небәрі 4 таза бөлу жеткілікті",
    # Course-mode scenelet labels.
    "anchor visual": "негізгі бейне",
    "set up toy case": "қарапайым жағдайды дайында",
    "run the rule": "ережені қолдан",
    "read the result": "нәтижені оқы",
    "practice turns the rule into a move": "жаттығу ережені қимылға айналдырады",
    "name the object": "нысанды атап қой",
    "attach the label": "белгіні жапсыр",
    "test the definition": "анықтаманы тексер",
    "attach a name, then test it": "алдымен атын қой, сосын тексер",
    "build the anchor": "негізгі бейнені құр",
    "change one state": "бір күйді өзгерт",
    "keep the useful rule": "пайдалы ережені сақта",
    "one lesson beat, one durable idea": "бір сабақ, бір тұрақты идея",
    # Lecture-mode labels.
    "thinking pause": "ойлану кідірісі",
    "pause": "кідіріс",
    "statement": "тұжырым",
    "lemma": "лемма",
    "assumption": "шарт",
    "Lecture board": "Дәріс тақтасы",
    "Academic Board": "Академиялық тақта",
    "instantiate symbols": "белгілерді нақтыла",
    "run the calculation": "есепті шығар",
    "interpret the result": "нәтижені талда",
    "given values": "берілген мәндер",
    "theorem rule": "теорема ережесі",
    "computed target": "есептелген нысан",
    "the example follows the proof map": "мысал дәлелдеу картасын ұстанады",
    "test the tempting step": "қызықтырар қадамды тексер",
    "mark the missing assumption": "жетпей тұрған шартты белгіле",
    "repair the route": "жолды жөнде",
    "naive line": "аңқау жол",
    "failure point": "қате нүктесі",
    "valid condition": "дұрыс шарт",
    "the bad proof fails at one visible step": "қате дәлел бір көрінетін қадамда сынады",
    "separate assumptions": "шарттарды бөл",
    "name the conclusion": "қорытындыны атап қой",
    "connect the implication": "логикалық байланысты көрсет",
    "definition": "анықтама",
    "target claim": "мақсатты тұжырым",
    "the statement is a map, not a paragraph": "тұжырым — карта, абзац емес",
    "start from the assumption": "шарттан баста",
    "apply the lemma": "лемманы қолдан",
    "arrive at the target": "нысанға жет",
    "one proof move stays active at a time": "бір уақытта бір дәлелдеу қадамы ғана белсенді",
    "Which assumption is doing the work here?": "Мұнда қандай шарт жұмыс істеп тұр?",
    # Short-mode labels (kept minimal; shorts have their own planner).
    "hook": "ілмек",
    "insight": "түсінік",
    "rule": "ереже",
    "use": "қолдану",
    "takeaway": "қорытынды",
}


TRANSLATIONS: Mapping[str, Mapping[str, str]] = {
    "kk": _KK,
}


# --- Public API -----------------------------------------------------------


def translate(phrase: str, locale: str | None = None) -> str:
    """Return a locale-aware version of ``phrase`` or ``phrase`` unchanged.

    Passing ``locale`` explicitly is intended for tests; the production code
    path (deterministic fallback template builders) should call ``translate``
    with no locale argument and let it read ``NIMA_LANGUAGE_LOCK``.
    """
    if not phrase:
        return phrase
    key = locale if locale is not None else current_locale()
    if not key:
        return phrase
    table = TRANSLATIONS.get(key)
    if not table:
        return phrase
    return table.get(phrase, phrase)


def t(phrase: str) -> str:
    """Shorthand alias used by template builders to keep f-strings readable."""
    return translate(phrase)


# --- Generated-code post-processing --------------------------------------
#
# The deterministic ``_make_*_fallback_*_scene_code`` helpers build Manim
# source code as big f-strings.  Rather than sprinkle ``{t(...)!r}`` calls at
# every literal site (high diff, high risk), we rewrite the emitted source
# code after the fact: find every ``Text("...")`` / ``MathTex("...")`` call
# and translate the first string argument if the locale is active.
#
# This is a narrow, conservative substitution — it intentionally does not
# touch identifiers, f-strings with interpolations, or raw strings, and it
# leaves the phrase untouched when no translation is registered.

_TEXT_LITERAL_RE = re.compile(
    r"""(?P<call>\b(?:Text|MathTex|Tex|MarkupText|Paragraph)\s*\()"""
    r"""(?P<quote>['"])(?P<body>[^'"\\\n]*)(?P=quote)""",
)


def localize_scene_code(code: str, locale: str | None = None) -> str:
    """Translate the first string arg of every ``Text(...)``-style call.

    Safe no-op when no locale is active or the string is not in the lookup
    table.  Leaves everything outside ``Text/MathTex/Tex/MarkupText/Paragraph``
    constructors alone — colour hex strings, font paths, ``font_size=``, etc.
    are untouched.
    """
    key = locale if locale is not None else current_locale()
    if not key:
        return code
    table = TRANSLATIONS.get(key)
    if not table:
        return code

    def _sub(match: "re.Match[str]") -> str:
        body = match.group("body")
        translated = table.get(body, body)
        if translated == body:
            return match.group(0)
        quote = match.group("quote")
        # Re-use the same quote style the template author picked.
        return f"{match.group('call')}{quote}{translated}{quote}"

    return _TEXT_LITERAL_RE.sub(_sub, code)
