# LangSmith Experiment

- Project name: `job-search-automation`
- Dataset name: `job-search-automation-cv-extraction-fixtures`
- Dataset link: https://eu.smith.langchain.com/o/c8a8962b-4b69-4a4c-a6b6-d7d458b6ab57/datasets/93bdf09f-f853-403f-8cae-4075eea9779e
- Baseline experiment name: `cv-extraction-236c2889`
- Baseline experiment link: https://eu.smith.langchain.com/o/c8a8962b-4b69-4a4c-a6b6-d7d458b6ab57/datasets/93bdf09f-f853-403f-8cae-4075eea9779e/compare?selectedSessions=67fa2b7e-21e4-440c-ac65-ce3eaf7b79b1
- Comparison experiment name: `cv-extraction-fe4b9c5d`
- Comparison experiment link: https://eu.smith.langchain.com/o/c8a8962b-4b69-4a4c-a6b6-d7d458b6ab57/datasets/93bdf09f-f853-403f-8cae-4075eea9779e/compare?selectedSessions=0b530587-444c-4c1d-a3ef-3f1b661e40a7
- A/B comparison link: https://eu.smith.langchain.com/o/c8a8962b-4b69-4a4c-a6b6-d7d458b6ab57/datasets/93bdf09f-f853-403f-8cae-4075eea9779e/compare?selectedSessions=67fa2b7e-21e4-440c-ac65-ce3eaf7b79b1%2C0b530587-444c-4c1d-a3ef-3f1b661e40a7
- Models: `gpt-5.4`, `gpt-5.4-mini`
- Processed examples: 10
- Evaluator rows exported per model: 50

## Aggregate Scores

| Model | Correctness | Schema | Supplemental | Grounding | LLM judge | Avg latency | Total cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-5.4` | 0.7184 | 1.0000 | 0.5000 | 0.6264 | 0.6560 | 23568.8260 ms | 0.154025 USD |
| `gpt-5.4-mini` | 0.7743 | 1.0000 | 0.5000 | 0.6923 | 0.6520 | 19342.6280 ms | 0.056878 USD |

## Review Notes

The live runs completed on June 9, 2026, after updating all 10 LangSmith
examples to match the fictional PDF source documents. The evaluator suite
included deterministic correctness, supplemental evidence completeness, schema
validity, reference grounding, and an optional LLM judge enabled only for live
runs.

Both models produced valid `CandidateCVExtracted` JSON. `gpt-5.4-mini` was
faster and cheaper in this run, with higher deterministic correctness and
grounding averages. The LLM judge scored the two models similarly because both
extract supported evidence but also include extra details that are not part of
the normalized reference labels.
