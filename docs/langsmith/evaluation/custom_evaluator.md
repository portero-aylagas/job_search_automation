# Custom Evaluator

The custom evaluator is `supplemental_evidence_completeness` in
`docs/langsmith/evaluation/src/evaluators.py`.

It measures whether evidence from optional documents survives the target
function:

- Recommendation letters should contribute reference evidence.
- Certificates should contribute certification evidence.
- Missing optional evidence lowers the score even when the primary CV fields are
  otherwise correct.

The evaluator returns a LangSmith-compatible dictionary with:

- `key`: `supplemental_evidence_completeness`
- `score`: numeric value from 0 to 1
- `comment`: checked fields and score summary

This adds value beyond general correctness because it isolates a product risk:
the CV may extract well while supplemental documents are skipped or not merged.

## Live Comparison

The live `gpt-5.4` and `gpt-5.4-mini` runs exported per-case comparison rows to
`docs/langsmith/evaluation/results/custom_evaluator_comparison.csv`.

| Model | Correctness | Supplemental evidence |
| --- | ---: | ---: |
| `gpt-5.4` | 0.7184 | 0.5000 |
| `gpt-5.4-mini` | 0.7743 | 0.5000 |

The supplemental evaluator now catches a more specific remaining issue: both
models extract optional evidence, but not always in the same normalized
certificate/reference form used by the gold labels.
