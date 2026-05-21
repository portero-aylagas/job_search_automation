from __future__ import annotations

from src.candidate_profile_ui import (
    adaptive_text_area_height,
    review_block_text_from_items,
    review_blocks_from_text,
    review_text_from_items,
)


def test_review_text_from_items_formats_editable_bullets() -> None:
    text = review_text_from_items([" Python ", "", "SQL"])

    assert text == "- Python\n- SQL"


def test_review_block_text_from_items_formats_title_and_bullets() -> None:
    text = review_block_text_from_items(
        [
            "Engineering Specialist - Sample Organization, 2020-2024\n"
            "Built internal workflow systems\n"
            "Improved data validation checks"
        ]
    )

    assert text == (
        "Engineering Specialist - Sample Organization, 2020-2024\n"
        "- Built internal workflow systems\n"
        "- Improved data validation checks"
    )


def test_review_blocks_from_text_preserves_work_experience_blocks() -> None:
    text = (
        "Engineering Specialist - Sample Organization, 2020-2024\n"
        "- Built internal workflow systems\n"
        "- Improved data validation checks\n\n"
        "Research Intern - Sample Lab, 2019\n"
        "- Prepared experiment reports"
    )

    assert review_blocks_from_text(text) == [
        "Engineering Specialist - Sample Organization, 2020-2024\n"
        "Built internal workflow systems\n"
        "Improved data validation checks",
        "Research Intern - Sample Lab, 2019\nPrepared experiment reports",
    ]


def test_adaptive_text_area_height_grows_with_content() -> None:
    short_height = adaptive_text_area_height("- Python", min_rows=4)
    long_text = "\n".join(f"- Experience item {index}" for index in range(12))
    long_height = adaptive_text_area_height(long_text, min_rows=4)

    assert long_height > short_height


def test_adaptive_text_area_height_caps_very_long_content() -> None:
    long_text = "\n".join(f"- Experience item {index}" for index in range(50))

    assert adaptive_text_area_height(long_text, min_rows=4, max_rows=8) == 232


def test_adaptive_text_area_height_allows_field_specific_wrapping() -> None:
    dense_skill_line = "- Python, SQL, workflow automation, data validation, testing"

    default_height = adaptive_text_area_height(dense_skill_line, min_rows=1)
    dense_height = adaptive_text_area_height(dense_skill_line, min_rows=1, wrap_chars=30)

    assert dense_height > default_height
