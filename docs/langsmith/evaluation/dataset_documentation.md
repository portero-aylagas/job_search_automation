# CV Extraction Evaluation Dataset

## Domain

This dataset evaluates the candidate-profile extraction workflow:

```text
fictional CV + optional recommendation/certificate documents -> CandidateCVExtracted
```

The source documents are fictional PDFs stored under
`docs/langsmith/evaluation/source_documents/`. They are isolated from runtime app data and are
not loaded by Karen or the normal candidate-profile workflow.

## LangSmith Dataset

- Dataset name: `job-search-automation-cv-extraction-fixtures`
- Dataset description: Fictional CV, recommendation-letter, and certificate
  fixtures for evaluating `CandidateCVExtracted` structured extraction.
- Upload script: `python -m evaluation.cv_eval.create_dataset`

## Data Structure

Each JSONL row in `docs/langsmith/evaluation/data/evaluation_examples.jsonl` contains:

- `inputs.case_id`: stable evaluation case identifier.
- `inputs.cv_path`: repository-relative path to the primary CV PDF.
- `inputs.optional_document_paths`: repository-relative paths to recommendation
  and certificate PDFs.
- `inputs.document_types`: document labels aligned with the paths.
- `outputs.identity`: expected identity/contact fields.
- `outputs.work_experience`: expected work history evidence.
- `outputs.education`: expected education evidence.
- `outputs.skills`: expected skill evidence.
- `outputs.languages`: expected language evidence.
- `outputs.certifications`: expected certifications, including optional
  certificate evidence.
- `outputs.projects`: expected project evidence.
- `outputs.references`: expected recommendation-letter evidence.
- `metadata`: category, difficulty, and fictional source markers.

## Upload Evidence

The live dataset was verified with 10 examples and all expected `case_id`
values present. On June 9, 2026, the upload script updated all 10 existing
LangSmith examples because the local gold labels were reconciled with the
fictional PDF source documents.

- Dataset link: https://eu.smith.langchain.com/o/c8a8962b-4b69-4a4c-a6b6-d7d458b6ab57/datasets/93bdf09f-f853-403f-8cae-4075eea9779e
- Result notes: `docs/langsmith/evaluation/results/langsmith_experiment.md`
