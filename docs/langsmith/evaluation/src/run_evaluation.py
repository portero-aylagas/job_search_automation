"""Run the LangSmith CV extraction evaluation experiment."""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

from docs.langsmith.evaluation.src.create_dataset import DATASET_NAME
from docs.langsmith.evaluation.src.evaluators import evaluation_suite
from docs.langsmith.evaluation.src.target_function import target_function

PROJECT_ROOT = Path(__file__).resolve().parents[4]
RESULTS_PATH = (
    PROJECT_ROOT
    / "docs"
    / "langsmith"
    / "evaluation"
    / "results"
    / "evaluation_results.csv"
)
COST_PERFORMANCE_PATH = (
    PROJECT_ROOT
    / "docs"
    / "langsmith"
    / "evaluation"
    / "results"
    / "cost_performance_comparison.csv"
)
CUSTOM_EVALUATOR_PATH = (
    PROJECT_ROOT
    / "docs"
    / "langsmith"
    / "evaluation"
    / "results"
    / "custom_evaluator_comparison.csv"
)


def run_evaluation() -> object:
    """Run the configured LangSmith evaluation and export available result rows."""

    from langsmith import Client

    client = Client()
    experiment = client.evaluate(
        target_function,
        data=DATASET_NAME,
        evaluators=evaluation_suite(),
        experiment_prefix=os.getenv("CV_EVAL_EXPERIMENT_PREFIX", "cv-extraction"),
        max_concurrency=int(os.getenv("CV_EVAL_MAX_CONCURRENCY", "1")),
        metadata={"model": _current_model()},
    )
    _export_results(experiment, RESULTS_PATH, client=client)
    return experiment


def export_experiment_results(experiment_name: str, path: Path = RESULTS_PATH) -> None:
    """Export evaluator feedback rows from a completed LangSmith experiment."""

    from langsmith import Client

    client = Client()
    project = client.read_project(project_name=experiment_name)
    rows = _coerce_project_feedback_rows(
        client,
        project_id=project.id,
        experiment_id=getattr(project, "id", ""),
        experiment_name=experiment_name,
    )
    _write_rows(rows, path)
    _write_comparison_files(rows)


def main() -> None:
    """CLI entry point for running the LangSmith evaluation."""

    if experiment_name := os.getenv("CV_EVAL_EXPORT_EXPERIMENT"):
        export_experiment_results(experiment_name)
        return
    run_evaluation()


def _export_results(
    experiment: object,
    path: Path,
    *,
    client: object | None = None,
) -> None:
    """Export best-effort LangSmith result rows to CSV."""

    rows = _coerce_result_rows(experiment)
    experiment_id = getattr(experiment, "experiment_id", None)
    experiment_name = _experiment_name(experiment)
    if not rows and client is not None and experiment_id is not None:
        rows = _coerce_project_feedback_rows(
            client,
            project_id=experiment_id,
            experiment_id=experiment_id,
            experiment_name=experiment_name,
        )
    _write_rows(rows, path)
    _write_comparison_files(rows)


def _write_rows(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "model",
        "experiment_id",
        "experiment_name",
        "case_id",
        "score_key",
        "score",
        "comment",
        "latency_ms",
        "total_cost_usd",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _coerce_result_rows(experiment: object) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    experiment_id = str(getattr(experiment, "experiment_id", "") or "")
    experiment_name = _experiment_name(experiment)
    for item in experiment if hasattr(experiment, "__iter__") else []:
        evaluation_results = _get_value(item, "evaluation_results", {}) or {}
        example = _get_value(item, "example")
        inputs = _get_value(example, "inputs", {}) if example is not None else {}
        case_id = _case_id_from_inputs(inputs)
        run = _get_value(item, "run")
        latency_ms = _latency_ms(run)
        cost = _total_cost(run)
        for result in evaluation_results.get("results", []):
            rows.append(
                {
                    "model": _current_model(),
                    "experiment_id": experiment_id,
                    "experiment_name": experiment_name,
                    "case_id": case_id,
                    "score_key": _get_value(result, "key", ""),
                    "score": _get_value(result, "score", ""),
                    "comment": _get_value(result, "comment", ""),
                    "latency_ms": latency_ms,
                    "total_cost_usd": cost,
                }
            )
    return rows


def _coerce_project_feedback_rows(
    client: object,
    *,
    project_id: object,
    experiment_id: object | None = None,
    experiment_name: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    runs = client.list_runs(project_id=project_id, is_root=True)
    for run in runs:
        case_id = _case_id_from_inputs(_get_value(run, "inputs", {}))
        feedback_stats = _get_value(run, "feedback_stats", {}) or {}
        latency_ms = _latency_ms(run)
        cost = _total_cost(run)
        for score_key, stats in feedback_stats.items():
            comments = stats.get("comments", []) if isinstance(stats, dict) else []
            rows.append(
                {
                    "model": _current_model(),
                    "experiment_id": str(experiment_id or project_id or ""),
                    "experiment_name": experiment_name,
                    "case_id": case_id,
                    "score_key": score_key,
                    "score": stats.get("avg", "") if isinstance(stats, dict) else "",
                    "comment": comments[0] if comments else "",
                    "latency_ms": latency_ms,
                    "total_cost_usd": cost,
                }
            )
    return sorted(rows, key=lambda row: (row["case_id"], row["score_key"]))


def _write_comparison_files(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    _write_cost_performance_summary(rows, COST_PERFORMANCE_PATH)
    _write_custom_evaluator_comparison(rows, CUSTOM_EVALUATOR_PATH)


def _write_cost_performance_summary(rows: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "model",
        "experiment_id",
        "experiment_name",
        "score_key",
        "average_score",
        "average_latency_ms",
        "estimated_cost_per_example",
        "total_cost_usd",
        "examples",
    ]
    summary_rows: list[dict[str, Any]] = []
    grouped = _group_rows(
        rows,
        "model",
        "experiment_id",
        "experiment_name",
        "score_key",
    )
    for key, grouped_rows in grouped.items():
        model, experiment_id, experiment_name, score_key = key
        scores = [_float_value(row.get("score")) for row in grouped_rows]
        latencies = [_float_value(row.get("latency_ms")) for row in grouped_rows]
        costs = [_float_value(row.get("total_cost_usd")) for row in grouped_rows]
        case_ids = {row.get("case_id", "") for row in grouped_rows if row.get("case_id")}
        summary_rows.append(
            {
                "model": model,
                "experiment_id": experiment_id,
                "experiment_name": experiment_name,
                "score_key": score_key,
                "average_score": _format_average(scores),
                "average_latency_ms": _format_average(latencies),
                "estimated_cost_per_example": _format_average(costs),
                "total_cost_usd": _format_sum(costs),
                "examples": len(case_ids),
            }
        )
    _merge_csv_rows(
        path,
        fieldnames,
        summary_rows,
        key_fields=["model", "experiment_id", "score_key"],
    )


def _write_custom_evaluator_comparison(rows: list[dict[str, Any]], path: Path) -> None:
    score_keys = [
        "cv_extraction_correctness",
        "supplemental_evidence_completeness",
        "cv_schema_validity",
        "reference_grounding",
        "llm_reference_judge",
    ]
    fieldnames = [
        "model",
        "experiment_id",
        "experiment_name",
        "case_id",
        *score_keys,
        "notes",
    ]
    case_rows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("model", "")),
            str(row.get("experiment_id", "")),
            str(row.get("experiment_name", "")),
            str(row.get("case_id", "")),
        )
        case_row = case_rows.setdefault(
            key,
            {
                "model": key[0],
                "experiment_id": key[1],
                "experiment_name": key[2],
                "case_id": key[3],
                "notes": "Live LangSmith evaluator export",
            },
        )
        score_key = str(row.get("score_key", ""))
        if score_key in score_keys:
            case_row[score_key] = row.get("score", "")
    _merge_csv_rows(
        path,
        fieldnames,
        list(case_rows.values()),
        key_fields=["model", "experiment_id", "case_id"],
    )


def _case_id_from_inputs(inputs: object) -> str:
    if not isinstance(inputs, dict):
        return ""
    nested_inputs = inputs.get("inputs")
    if isinstance(nested_inputs, dict) and "case_id" in nested_inputs:
        return str(nested_inputs["case_id"])
    case_id = inputs.get("case_id", "")
    return str(case_id) if case_id else ""


def _get_value(source: object, key: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _current_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5.4")


def _experiment_name(experiment: object) -> str:
    for key in ("experiment_name", "project_name", "name"):
        value = getattr(experiment, key, "")
        if value:
            return str(value)
    return ""


def _latency_ms(run: object) -> str:
    if run is None:
        return ""
    for key in ("latency_ms", "total_time_ms"):
        value = _get_value(run, key, None)
        if value not in (None, ""):
            return str(value)
    total_time = _get_value(run, "total_time", None)
    if total_time not in (None, ""):
        return str(round(float(total_time) * 1000, 2))
    start_time = _get_value(run, "start_time", None)
    end_time = _get_value(run, "end_time", None)
    if start_time is not None and end_time is not None:
        return str(round((end_time - start_time).total_seconds() * 1000, 2))
    return ""


def _total_cost(run: object) -> str:
    if run is None:
        return ""
    for key in ("total_cost", "total_cost_usd"):
        value = _get_value(run, key, None)
        if value not in (None, ""):
            return str(value)
    return ""


def _group_rows(
    rows: list[dict[str, Any]],
    *fields: str,
) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in fields)
        grouped.setdefault(key, []).append(row)
    return grouped


def _float_value(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_average(values: list[float | None]) -> str:
    clean_values = [value for value in values if value is not None]
    if not clean_values:
        return ""
    return f"{sum(clean_values) / len(clean_values):.4f}"


def _format_sum(values: list[float | None]) -> str:
    clean_values = [value for value in values if value is not None]
    if not clean_values:
        return ""
    return f"{sum(clean_values):.6f}"


def _merge_csv_rows(
    path: Path,
    fieldnames: list[str],
    new_rows: list[dict[str, Any]],
    *,
    key_fields: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged: dict[tuple[str, ...], dict[str, Any]] = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                if not set(fieldnames).issubset(row):
                    continue
                key = tuple(row.get(field, "") for field in key_fields)
                merged[key] = row
    for row in new_rows:
        key = tuple(str(row.get(field, "")) for field in key_fields)
        merged[key] = {field: row.get(field, "") for field in fieldnames}
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(
            merged.values(),
            key=lambda item: tuple(item.get(field, "") for field in key_fields),
        ):
            writer.writerow(row)


if __name__ == "__main__":
    main()
