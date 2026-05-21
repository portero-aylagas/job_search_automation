from __future__ import annotations

from src.candidate_profile_ui import adaptive_text_area_height, review_text_from_items


def test_review_text_from_items_formats_editable_bullets() -> None:
    text = review_text_from_items([" Python ", "", "SQL"])

    assert text == "- Python\n- SQL"


def test_adaptive_text_area_height_grows_with_content() -> None:
    short_height = adaptive_text_area_height("- Python", min_rows=4)
    long_text = "\n".join(f"- Experience item {index}" for index in range(12))
    long_height = adaptive_text_area_height(long_text, min_rows=4)

    assert long_height > short_height


def test_adaptive_text_area_height_caps_very_long_content() -> None:
    long_text = "\n".join(f"- Experience item {index}" for index in range(50))

    assert adaptive_text_area_height(long_text, min_rows=4, max_rows=8) == 232
