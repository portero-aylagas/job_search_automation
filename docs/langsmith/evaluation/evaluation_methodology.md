# Evaluation Methodology

The target function reuses the production CV extraction path in
`src/cv_extraction.py` and merges optional-document evidence with
`src.candidate_profile.merge_supplemental_extracted_data`. The output is
serialized as `CandidateCVExtracted.model_dump(mode="json")`.

The evaluation checks whether extracted structured data matches expected
fictional references. It uses:

- `cv_extraction_correctness`: deterministic identity and evidence matching.
- `supplemental_evidence_completeness`: deterministic certificate/reference
  preservation from optional documents.
- `cv_schema_validity`: deterministic `CandidateCVExtracted` validation.
- `reference_grounding`: deterministic unsupported-claim check against the
  normalized reference fixture.
- `llm_reference_judge`: optional LLM judge enabled only when
  `CV_EVAL_ENABLE_LLM_JUDGE=true`.

The deterministic evaluators are suitable for CI because they do not require a
judge model. The LLM judge is for live LangSmith runs only.

Live LangSmith runs require:

```bash
python -m evaluation.cv_eval.create_dataset
python -m evaluation.cv_eval.run_evaluation
```

The scripts import without credentials. Credentials are needed only when the
dataset or experiment is created remotely.
