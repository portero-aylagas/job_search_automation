# Optimization Summary

The live A/B evaluation ran in LangSmith on June 9, 2026 against 10 examples.

| Model | Experiment | Correctness | Avg latency | Cost/example | Total cost |
| --- | --- | ---: | ---: | ---: | ---: |
| `gpt-5.4` | `cv-extraction-236c2889` | 0.7184 | 23568.8260 ms | 0.0154 USD | 0.154025 USD |
| `gpt-5.4-mini` | `cv-extraction-fe4b9c5d` | 0.7743 | 19342.6280 ms | 0.0057 USD | 0.056878 USD |

`gpt-5.4-mini` is the better default candidate for this evaluation slice: it was
faster, cheaper, and slightly stronger on deterministic correctness and
grounding. The next quality improvement should focus on prompt/schema guidance
that discourages unsupported normalization extras, because both models still add
details outside the gold-label format.
