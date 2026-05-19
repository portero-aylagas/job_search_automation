from __future__ import annotations

from src.llm_job_extraction import build_job_page_snapshot


def test_job_page_snapshot_extracts_visible_page_evidence() -> None:
    html = """
    <html>
      <head><title>Automation Engineer - Example Co</title></head>
      <body>
        <h1>Automation Engineer</h1>
        <h2>Berlin Hybrid</h2>
        <p>Build internal automation tools.</p>
        <a href="/jobs/automation-engineer/apply" data-job-id="REQ-123">Apply now</a>
        <button data-url="/jobs/automation-engineer/apply">Jetzt bewerben</button>
        <form action="/apply" method="post">
          <label for="email">Email</label>
          <input id="email" name="email" type="email" required>
          <button type="submit">Submit application</button>
        </form>
        <script type="application/json" id="job-data">
          {"title":"Automation Engineer","identifier":"REQ-123"}
        </script>
      </body>
    </html>
    """

    snapshot = build_job_page_snapshot(
        requested_url="https://example.com/jobs/automation-engineer",
        final_url="https://example.com/jobs/automation-engineer",
        html=html,
        fetch_status=200,
        content_type="text/html",
    )

    assert snapshot.page_title == "Automation Engineer - Example Co"
    assert "Automation Engineer" in snapshot.headings
    assert "Build internal automation tools." in snapshot.visible_text_excerpt
    assert any(link.text == "Apply now" for link in snapshot.links)
    assert any(button.text == "Jetzt bewerben" for button in snapshot.buttons)
    assert any(control.name == "email" and control.required for control in snapshot.controls)
    assert snapshot.embedded_json_summaries
    assert len(snapshot.apply_link_candidates) == 3


def test_job_page_snapshot_clips_and_redacts_sensitive_values() -> None:
    html = (
        "<html><body>"
        "<input type='hidden' name='csrf_token' value='supersecretvalue123'>"
        + ("Automation Engineer. " * 10000)
        + "</body></html>"
    )

    snapshot = build_job_page_snapshot(
        requested_url="https://example.com/jobs/automation-engineer",
        final_url="https://example.com/jobs/automation-engineer",
        html=html,
        fetch_status=200,
        content_type="text/html",
    )

    assert "supersecretvalue123" not in snapshot.raw_html_excerpt
    assert "[REDACTED]" in snapshot.raw_html_excerpt
    assert "[TRUNCATED]" in snapshot.raw_html_excerpt


def test_job_page_snapshot_records_structured_fetch_errors() -> None:
    snapshot = build_job_page_snapshot(
        requested_url="https://example.com/jobs/automation-engineer",
        final_url="https://example.com/jobs/automation-engineer",
        html="",
        fetch_status=None,
        content_type="",
        errors=["HTTP fetch failed: Timeout"],
    )

    assert "HTTP fetch failed: Timeout" in snapshot.errors
    assert "No static HTML content was available for inspection." in snapshot.errors
