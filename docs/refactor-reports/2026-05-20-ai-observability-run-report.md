# AI Observability Run Report

## Scope
- Added persistent `AIWorkflowTrace` metadata for the main AI workflows.
- Kept provider-facing response schemas free of local trace metadata.
- Surfaced the trace in the UI and package markdown export.

## Files Changed
- `app.py`
- `src/application_package.py`
- `src/application_requirements.py`
- `src/apply_url_resolution.py`
- `src/cv_extraction.py`
- `src/llm_client.py`
- `src/llm_job_extraction.py`
- `src/schemas.py`
- `tests/test_application_package.py`
- `tests/test_application_requirements.py`
- `tests/test_apply_url_resolution.py`
- `tests/test_cv_extraction.py`
- `tests/test_llm_client.py`
- `tests/test_llm_job_extraction.py`
- `tests/test_schemas.py`

## Verification
- `PATH="$PWD/.conda/bin:$PATH" pytest tests/test_llm_job_extraction.py tests/test_apply_url_resolution.py tests/test_cv_extraction.py tests/test_llm_client.py tests/test_schemas.py -q`
- `PATH="$PWD/.conda/bin:$PATH" make verify`

## Notes
- The initial patch accidentally exposed trace metadata on one provider-facing schema; that was corrected by introducing a separate LLM response model for apply URL resolution.
- Optional document extraction now also records workflow trace metadata.
