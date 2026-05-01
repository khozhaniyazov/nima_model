"""Request payload parsing checks."""

from api_routes.payload import bool_payload, dict_payload, parse_video_mode_payload


def test_bool_payload_parser():
    assert bool_payload(True, False) is True
    assert bool_payload(False, True) is False
    assert bool_payload("false", True) is False
    assert bool_payload("0", True) is False
    assert bool_payload("yes", False) is True
    assert bool_payload(None, True) is True
    print("[OK] payload utils — string false/true parsed explicitly")


def test_dict_payload_parser():
    assert dict_payload({"a": 1}) == {"a": 1}
    assert dict_payload(None) == {}
    assert dict_payload(["not", "a", "dict"]) == {}
    print("[OK] payload utils — malformed dict payloads default to empty")


def test_video_mode_payload_parser():
    result = parse_video_mode_payload(
        {"mode": "SHORT"},
        default_video_mode="standard",
        video_modes={"standard": {}, "short": {}},
        normalize_video_mode=lambda value: value.lower(),
    )
    assert result == "short"

    alias_result = parse_video_mode_payload(
        {"video_mode": "lecture"},
        default_video_mode="standard",
        video_modes={"standard": {}, "short": {}, "lecture": {}},
        normalize_video_mode=lambda value: value.lower(),
    )
    assert alias_result == "lecture"

    camel_alias_result = parse_video_mode_payload(
        {"videoMode": "short"},
        default_video_mode="standard",
        video_modes={"standard": {}, "short": {}, "lecture": {}},
        normalize_video_mode=lambda value: value.lower(),
    )
    assert camel_alias_result == "short"

    try:
        parse_video_mode_payload(
            {"mode": "bad"},
            default_video_mode="standard",
            video_modes={"standard": {}, "short": {}},
            normalize_video_mode=lambda value: value,
        )
    except ValueError as exc:
        assert "Expected one of: standard, short" in str(exc)
    else:
        raise AssertionError("Invalid video mode should raise ValueError")
    print("[OK] payload utils — video mode parser validates options")


if __name__ == "__main__":
    test_bool_payload_parser()
    test_dict_payload_parser()
    test_video_mode_payload_parser()
    print("\nALL PAYLOAD UTILS CHECKS PASSED")
