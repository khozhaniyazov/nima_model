"""Tests for algorithms.i18n locale helpers + template post-processing."""

from algorithms import i18n


def test_current_locale_empty_when_env_unset(monkeypatch):
    monkeypatch.delenv("NIMA_LANGUAGE_LOCK", raising=False)
    assert i18n.current_locale() == ""
    assert i18n.is_locale_active() is False


def test_current_locale_detects_kazakh_tokens(monkeypatch):
    for value in [
        "Kazakh",
        "Kazakh (Қазақ тілі, Cyrillic script)",
        "Қазақ",
        "kk-KZ",
        "kaz",
    ]:
        monkeypatch.setenv("NIMA_LANGUAGE_LOCK", value)
        assert i18n.current_locale() == "kk", value


def test_translate_returns_input_when_locale_unset(monkeypatch):
    monkeypatch.delenv("NIMA_LANGUAGE_LOCK", raising=False)
    assert i18n.translate("Cold Open") == "Cold Open"
    assert i18n.t("Cold Open") == "Cold Open"


def test_translate_returns_kazakh_when_locale_active(monkeypatch):
    monkeypatch.setenv("NIMA_LANGUAGE_LOCK", "Kazakh (Қазақ тілі)")
    assert i18n.translate("Cold Open") == "Күтпеген бастама"
    assert i18n.translate("The Setup") == "Құрылым"
    # Unknown phrase passes through untouched.
    assert i18n.translate("completely unknown phrase") == "completely unknown phrase"


def test_translate_explicit_locale_arg_overrides_env(monkeypatch):
    monkeypatch.delenv("NIMA_LANGUAGE_LOCK", raising=False)
    assert i18n.translate("Cold Open", locale="kk") == "Күтпеген бастама"


def test_localize_scene_code_noop_without_locale(monkeypatch):
    monkeypatch.delenv("NIMA_LANGUAGE_LOCK", raising=False)
    code = 'Text("Cold Open", font_size=34, color=fg)'
    assert i18n.localize_scene_code(code) == code


def test_localize_scene_code_rewrites_text_literals(monkeypatch):
    monkeypatch.setenv("NIMA_LANGUAGE_LOCK", "Kazakh (Қазақ тілі)")
    code = (
        'title = Text("Cold Open", font_size=34, color=fg, weight=BOLD)\n'
        'caption = Text("comparisons", font_size=25, color=accent)\n'
        'value = Text("target", font_size=22, color=good)\n'
    )
    out = i18n.localize_scene_code(code)
    assert 'Text("Күтпеген бастама"' in out
    assert 'Text("салыстырулар"' in out
    assert 'Text("нысан"' in out
    # Structural args (font_size, color identifiers) are untouched.
    assert "font_size=34" in out
    assert "color=fg" in out


def test_localize_scene_code_leaves_unknown_literals_alone(monkeypatch):
    monkeypatch.setenv("NIMA_LANGUAGE_LOCK", "Kazakh (Қазақ тілі)")
    code = 'Text("this exact phrase is not in the table", font_size=24)'
    assert i18n.localize_scene_code(code) == code


def test_localize_scene_code_preserves_quote_style(monkeypatch):
    monkeypatch.setenv("NIMA_LANGUAGE_LOCK", "Kazakh (Қазақ тілі)")
    code = "Text('Cold Open', font_size=34)"
    out = i18n.localize_scene_code(code)
    assert "Text('Күтпеген бастама', font_size=34)" == out


def test_localize_scene_code_ignores_non_text_constructors(monkeypatch):
    monkeypatch.setenv("NIMA_LANGUAGE_LOCK", "Kazakh (Қазақ тілі)")
    # ManimColor / RoundedRectangle / SomeOtherClass with the phrase shouldn't be touched.
    code = 'ManimColor("Cold Open") and SurroundingRectangle("target")'
    assert i18n.localize_scene_code(code) == code


def test_localize_scene_code_handles_mathtex_and_tex(monkeypatch):
    monkeypatch.setenv("NIMA_LANGUAGE_LOCK", "Kazakh (Қазақ тілі)")
    code = 'MathTex("target") ; Tex("Cold Open") ; MarkupText("target")'
    out = i18n.localize_scene_code(code)
    assert 'MathTex("нысан")' in out
    assert 'Tex("Күтпеген бастама")' in out
    assert 'MarkupText("нысан")' in out


def test_standard_fallback_emits_kazakh_when_locked(monkeypatch):
    monkeypatch.setenv("NIMA_LANGUAGE_LOCK", "Kazakh (Қазақ тілі)")
    from algorithms import streaming

    context = streaming.NarrativeContext.from_analysis(
        "Түсіндір", {"domain": "math", "duration": 30}
    )
    context.scene_index = 1
    scene_plan = {
        "title": "Cold Open",
        "description": "surprising failure race side by side",
        "narration": "test",
        "visual_description": "race",
    }
    code = streaming._make_standard_fallback_scene_code(scene_plan, context)
    assert 'Text("сызықтық шолу"' in code
    assert "Cold Open" not in code or 'Text("Cold Open"' not in code


def test_standard_fallback_emits_english_without_lock(monkeypatch):
    monkeypatch.delenv("NIMA_LANGUAGE_LOCK", raising=False)
    from algorithms import streaming

    context = streaming.NarrativeContext.from_analysis(
        "Explain", {"domain": "math", "duration": 30}
    )
    context.scene_index = 1
    scene_plan = {
        "title": "Cold Open",
        "description": "surprising failure race side by side",
        "narration": "test",
        "visual_description": "race",
    }
    code = streaming._make_standard_fallback_scene_code(scene_plan, context)
    # English is preserved when the env var is unset.
    assert 'Text("linear scan"' in code
