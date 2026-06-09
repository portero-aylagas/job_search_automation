# Evaluation Source Document Manifest

All documents under `docs/langsmith/evaluation/source_documents/` are fictional
test fixtures created for CV extraction evaluation. They are safe to track in
Git because they do not contain real candidate data.

Each candidate directory should contain:

- `cv.pdf`: fictional primary CV source document.
- `recommendation_letter.pdf`: fictional optional reference document.
- `certificate.pdf`: fictional optional certificate source document.

These fixtures are evaluation-only inputs. The normal app runtime, Karen, and
runtime candidate profile storage must not load them automatically.
