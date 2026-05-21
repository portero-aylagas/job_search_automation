"""Validation helpers for user-provided job source URLs."""

from __future__ import annotations


def validate_source_url(source_url: str) -> str:
    """Return a trimmed HTTP(S) job URL or raise a user-facing error.

    Args:
        source_url: URL entered by the user or passed into an intake workflow.

    Raises:
        ValueError: If the URL is blank or does not include an HTTP(S) scheme.
    """

    normalized_url = source_url.strip()

    if not normalized_url:
        raise ValueError("Enter a job URL.")

    if not normalized_url.startswith(("http://", "https://")):
        raise ValueError("Enter a full job URL, including https://.")

    return normalized_url
