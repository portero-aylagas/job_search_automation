# LangSmith CV Extraction Evaluation

This evaluation checks the candidate-profile extraction workflow on fictional
CV, recommendation-letter, and certificate PDFs.

```text
CV PDF + optional document PDFs -> CandidateCVExtracted JSON
```

The dataset contains 10 independent fictional candidate cases. Each case has a
primary CV, optional supporting documents, expected structured output, and
metadata for category and difficulty.

## LangSmith Links

- Dataset: https://eu.smith.langchain.com/o/c8a8962b-4b69-4a4c-a6b6-d7d458b6ab57/datasets/93bdf09f-f853-403f-8cae-4075eea9779e
- Baseline experiment (`gpt-5.4`): https://eu.smith.langchain.com/o/c8a8962b-4b69-4a4c-a6b6-d7d458b6ab57/datasets/93bdf09f-f853-403f-8cae-4075eea9779e/compare?selectedSessions=67fa2b7e-21e4-440c-ac65-ce3eaf7b79b1
- Comparison experiment (`gpt-5.4-mini`): https://eu.smith.langchain.com/o/c8a8962b-4b69-4a4c-a6b6-d7d458b6ab57/datasets/93bdf09f-f853-403f-8cae-4075eea9779e/compare?selectedSessions=0b530587-444c-4c1d-a3ef-3f1b661e40a7
- A/B comparison: https://eu.smith.langchain.com/o/c8a8962b-4b69-4a4c-a6b6-d7d458b6ab57/datasets/93bdf09f-f853-403f-8cae-4075eea9779e/compare?selectedSessions=67fa2b7e-21e4-440c-ac65-ce3eaf7b79b1%2C0b530587-444c-4c1d-a3ef-3f1b661e40a7

## Run Commands

Create or verify the dataset:

```bash
LANGSMITH_PROJECT=job-search-automation \
LANGSMITH_TRACING=true \
python -m evaluation.cv_eval.create_dataset
```

Run the baseline evaluation:

```bash
LANGSMITH_PROJECT=job-search-automation \
LANGSMITH_TRACING=true \
OPENAI_MODEL="${CV_EVAL_BASE_MODEL:-gpt-5.4}" \
CV_EVAL_MAX_CONCURRENCY=1 \
python -m evaluation.cv_eval.run_evaluation
```

Run the comparison evaluation:

```bash
LANGSMITH_PROJECT=job-search-automation \
LANGSMITH_TRACING=true \
OPENAI_MODEL=gpt-5.4-mini \
CV_EVAL_MAX_CONCURRENCY=1 \
CV_EVAL_ENABLE_LLM_JUDGE=true \
python -m evaluation.cv_eval.run_evaluation
```

Export an existing experiment without rerunning model calls:

```bash
CV_EVAL_EXPORT_EXPERIMENT=cv-extraction-826a350e \
LANGSMITH_PROJECT=job-search-automation \
LANGSMITH_TRACING=true \
python -m evaluation.cv_eval.run_evaluation
```

## File Map

| Path | Purpose |
| --- | --- |
| `docs/langsmith/evaluation/data/evaluation_examples.jsonl` | Dataset rows with inputs, reference outputs, and metadata. |
| `docs/langsmith/evaluation/source_documents/` | Fictional CV, recommendation-letter, and certificate PDFs used only for evaluation. |
| `docs/langsmith/evaluation/src/create_dataset.py` | Creates or verifies the LangSmith dataset and updates changed cases by `case_id`. |
| `docs/langsmith/evaluation/src/target_function.py` | Traceable target function that reuses the app CV extraction workflow. |
| `docs/langsmith/evaluation/src/evaluators.py` | Correctness, supplemental-evidence, schema, grounding, and optional LLM judge evaluators. |
| `docs/langsmith/evaluation/src/run_evaluation.py` | Runs LangSmith evaluation and exports evaluator rows. |
| `docs/langsmith/evaluation/results/langsmith_experiment.md` | Dataset and experiment links, aggregate scores, and review notes. |
| `docs/langsmith/evaluation/results/evaluation_results.csv` | Exported evaluator rows. |
| `docs/langsmith/evaluation/results/custom_evaluator_comparison.csv` | Per-case comparison between correctness and supplemental evidence scores. |
| `docs/langsmith/evaluation/results/cost_performance_comparison.csv` | Baseline cost, latency, and score summary. |
| `docs/langsmith/evaluation/dataset_documentation.md` | Dataset structure and upload evidence. |
| `docs/langsmith/evaluation/evaluation_methodology.md` | Target function and evaluator methodology. |
| `docs/langsmith/evaluation/custom_evaluator.md` | Supplemental evidence evaluator criteria and comparison notes. |
| `docs/langsmith/evaluation/cost_performance.md` | Cost/performance comparison method. |
| `docs/langsmith/evaluation/evaluation_summary.md` | Short root-level evaluation summary. |
| `docs/langsmith/evaluation/optimization_summary.md` | Short root-level cost/performance summary. |

## Live Result Summary

The June 9, 2026 live runs processed all 10 examples for both configured
models and exported five evaluator scores per example.

| Model | Correctness | Schema | Supplemental | Grounding | LLM judge | Avg latency | Cost/example |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-5.4` | 0.7184 | 1.0000 | 0.5000 | 0.6264 | 0.6560 | 23568.8260 ms | 0.0154 USD |
| `gpt-5.4-mini` | 0.7743 | 1.0000 | 0.5000 | 0.6923 | 0.6520 | 19342.6280 ms | 0.0057 USD |

The corrected gold labels now match the fictional PDF fixtures. Both models
produce schema-valid outputs; the main remaining quality issue is
over-extraction of supported-but-not-reference-normalized details such as full
addresses, certificate IDs, exact dates, and expanded reference contact text.
