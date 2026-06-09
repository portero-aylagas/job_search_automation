# Cost And Performance Comparison

The evaluation scripts support model comparison by running the same dataset with
different `OPENAI_MODEL` values:

```env
OPENAI_MODEL=gpt-5.4
CV_EVAL_MAX_CONCURRENCY=1
CV_EVAL_ENABLE_LLM_JUDGE=true
```

For live runs, export LangSmith experiment data to
`docs/langsmith/evaluation/results/cost_performance_comparison.csv` with one row
per model and score key. Track:

- average score
- average latency
- estimated cost per example
- total cost
- example count

## Live A/B Result

| Model | Correctness | Grounding | LLM judge | Avg latency | Cost/example |
| --- | ---: | ---: | ---: | ---: | ---: |
| `gpt-5.4` | 0.7184 | 0.6264 | 0.6560 | 23568.8260 ms | 0.0154 USD |
| `gpt-5.4-mini` | 0.7743 | 0.6923 | 0.6520 | 19342.6280 ms | 0.0057 USD |

In this June 9, 2026 run, `gpt-5.4-mini` was cheaper and faster while matching
or exceeding the deterministic quality metrics. The judge scores remained close,
so the next optimization step is to reduce unsupported extra details rather than
switch to a larger model.
