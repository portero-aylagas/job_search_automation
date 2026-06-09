# Evaluation Summary

This evaluation checks the CV extraction workflow on 10 fictional candidate
fixtures with CV, recommendation-letter, and certificate PDFs. The target
returns `CandidateCVExtracted` JSON and is scored for identity correctness,
structured evidence coverage, supplemental-document preservation, schema
validity, reference grounding, and live LLM judge quality.

Live LangSmith runs completed on June 9, 2026:

| Model | Experiment | Correctness | Grounding | LLM judge |
| --- | --- | ---: | ---: | ---: |
| `gpt-5.4` | `cv-extraction-236c2889` | 0.7184 | 0.6264 | 0.6560 |
| `gpt-5.4-mini` | `cv-extraction-fe4b9c5d` | 0.7743 | 0.6923 | 0.6520 |

The gold labels now match the PDF fixtures. The main remaining failure pattern
is over-extraction: models include extra dates, addresses, IDs, and reference
contact details that are source-supported but outside the normalized reference
format.
