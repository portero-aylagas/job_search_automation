from __future__ import annotations


def validate_source_url(source_url: str) -> str:
    normalized_url = source_url.strip()

    if not normalized_url:
        raise ValueError("Enter a job URL.")

    if not normalized_url.startswith(("http://", "https://")):
        raise ValueError("Enter a full job URL, including https://.")

    return normalized_url
