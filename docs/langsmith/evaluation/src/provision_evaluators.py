"""Provision LangSmith platform evaluators for CV extraction experiments."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from docs.langsmith.evaluation.src.platform_evaluator_code import (
    correctness_code,
    reference_grounding_code,
    schema_validity_code,
    supplemental_evidence_code,
)

DATASET_ID = "93bdf09f-f853-403f-8cae-4075eea9779e"
EXPERIMENT_IDS = (
    "67fa2b7e-21e4-440c-ac65-ce3eaf7b79b1",
    "0b530587-444c-4c1d-a3ef-3f1b661e40a7",
)
FEEDBACK_KEYS = (
    "cv_extraction_correctness",
    "supplemental_evidence_completeness",
    "cv_schema_validity",
    "reference_grounding",
    "llm_reference_judge",
)
CODE_EVALUATOR_KEYS = FEEDBACK_KEYS[:4]
DEFAULT_TIMEOUT = 20
DEFAULT_LLM_PROMPT_REPO_HANDLE = "cv-extraction-reference-judge"


class LangSmithEvaluatorProvisioningError(RuntimeError):
    """Raised when LangSmith evaluator provisioning cannot complete."""


@dataclass(frozen=True)
class EvaluatorSpec:
    """Definition for one LangSmith platform evaluator."""

    name: str
    feedback_key: str
    evaluator_type: str
    code: str = ""
    prompt_repo_handle_env: str = "CV_EVAL_LLM_PROMPT_REPO_HANDLE"
    prompt_tag_env: str = "CV_EVAL_LLM_PROMPT_TAG"


def provision_evaluators(
    *,
    dataset_id: str = DATASET_ID,
    http_client: Any = requests,
) -> dict[str, Any]:
    """Create or update evaluator resources and attach them to the dataset."""

    api_base, headers = _api_settings()
    evaluators: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    for spec in evaluator_specs():
        evaluator = _upsert_evaluator(
            api_base,
            headers,
            spec,
            http_client=http_client,
        )
        evaluator_id = _require_id(evaluator, f"evaluator {spec.feedback_key}")
        rule = _upsert_rule(
            api_base,
            headers,
            dataset_id=dataset_id,
            spec=spec,
            evaluator_id=evaluator_id,
            http_client=http_client,
        )
        evaluators.append(_summarize_evaluator(evaluator, spec))
        rules.append(_summarize_rule(rule, spec))

    return {
        "dataset_id": dataset_id,
        "evaluators": evaluators,
        "rules": rules,
    }


def backfill_experiments(
    *,
    dataset_id: str = DATASET_ID,
    experiment_ids: tuple[str, ...] = EXPERIMENT_IDS,
    poll: bool = True,
    http_client: Any = requests,
    client_factory: Any | None = None,
) -> dict[str, Any]:
    """Replace old feedback rows and backfill evaluator rules on experiments."""

    api_base, headers = _api_settings()
    client = _langsmith_client(client_factory)
    rules = _rules_by_feedback_key(api_base, headers, dataset_id, http_client=http_client)
    missing_rules = [key for key in FEEDBACK_KEYS if key not in rules]
    if missing_rules:
        raise LangSmithEvaluatorProvisioningError(
            "Missing LangSmith rules for feedback keys: " + ", ".join(missing_rules)
        )

    run_ids_by_experiment = {
        experiment_id: _root_run_ids(client, experiment_id)
        for experiment_id in experiment_ids
    }
    feedback_rows = _matching_feedback_rows(
        client,
        run_ids=[
            run_id
            for run_ids in run_ids_by_experiment.values()
            for run_id in run_ids
        ],
    )
    backup_path = _backup_feedback_rows(feedback_rows)
    for row in feedback_rows:
        client.delete_feedback(_feedback_id(row))

    evaluations: list[dict[str, str]] = []
    for experiment_id in experiment_ids:
        for key in FEEDBACK_KEYS:
            rule_id = _require_id(rules[key], f"rule {key}")
            response = _request(
                http_client.post,
                f"{api_base}/api/v1/runs/experiments/{experiment_id}/evaluate",
                headers=headers,
                json={"rule_id": rule_id},
            )
            evaluations.append(
                {
                    "experiment_id": experiment_id,
                    "feedback_key": key,
                    "rule_id": rule_id,
                    "status": "triggered",
                    "response": _json_summary(response),
                }
            )

    verification = {}
    if poll:
        verification = _poll_feedback(
            client,
            run_ids_by_experiment,
            timeout_seconds=int(os.getenv("CV_EVAL_BACKFILL_TIMEOUT_SECONDS", "900")),
            interval_seconds=int(os.getenv("CV_EVAL_BACKFILL_POLL_SECONDS", "15")),
        )

    return {
        "backup_path": str(backup_path),
        "deleted_feedback_rows": len(feedback_rows),
        "evaluations": evaluations,
        "verification": verification,
    }


def verify_evaluator_setup(
    *,
    dataset_id: str = DATASET_ID,
    experiment_ids: tuple[str, ...] = EXPERIMENT_IDS,
    http_client: Any = requests,
    client_factory: Any | None = None,
) -> dict[str, Any]:
    """Verify evaluator resources, dataset rules, and experiment feedback keys."""

    api_base, headers = _api_settings()
    evaluators = _list_evaluators(api_base, headers, http_client=http_client)
    evaluator_keys = {
        key
        for evaluator in evaluators
        for key in _feedback_keys_for_evaluator(evaluator)
    }
    rules = _rules_by_feedback_key(api_base, headers, dataset_id, http_client=http_client)
    client = _langsmith_client(client_factory)
    experiments = {
        experiment_id: _feedback_key_counts(client, _root_run_ids(client, experiment_id))
        for experiment_id in experiment_ids
    }
    return {
        "platform_evaluators": {
            "expected": list(FEEDBACK_KEYS),
            "found": sorted(evaluator_keys.intersection(FEEDBACK_KEYS)),
            "missing": [key for key in FEEDBACK_KEYS if key not in evaluator_keys],
        },
        "dataset_rules": {
            "dataset_id": dataset_id,
            "expected": list(FEEDBACK_KEYS),
            "found": sorted(rules),
            "missing": [key for key in FEEDBACK_KEYS if key not in rules],
            "disabled": [
                key for key, rule in rules.items() if rule.get("is_enabled") is not True
            ],
        },
        "experiments": experiments,
    }


def evaluator_specs() -> tuple[EvaluatorSpec, ...]:
    """Return the canonical CV extraction platform evaluator specs."""

    return (
        EvaluatorSpec(
            name="CV extraction correctness",
            feedback_key="cv_extraction_correctness",
            evaluator_type="code",
            code=correctness_code(),
        ),
        EvaluatorSpec(
            name="Supplemental evidence completeness",
            feedback_key="supplemental_evidence_completeness",
            evaluator_type="code",
            code=supplemental_evidence_code(),
        ),
        EvaluatorSpec(
            name="CV schema validity",
            feedback_key="cv_schema_validity",
            evaluator_type="code",
            code=schema_validity_code(),
        ),
        EvaluatorSpec(
            name="Reference grounding",
            feedback_key="reference_grounding",
            evaluator_type="code",
            code=reference_grounding_code(),
        ),
        EvaluatorSpec(
            name="LLM reference judge",
            feedback_key="llm_reference_judge",
            evaluator_type="llm",
        ),
    )


def main() -> None:
    """CLI entry point for provisioning and backfilling LangSmith evaluators."""

    parser = argparse.ArgumentParser(
        description="Provision LangSmith CV extraction evaluator resources.",
    )
    parser.add_argument(
        "action",
        choices=("provision", "backfill", "verify", "all"),
        help="Operation to run.",
    )
    parser.add_argument("--dataset-id", default=DATASET_ID)
    parser.add_argument(
        "--experiment-id",
        action="append",
        dest="experiment_ids",
        help="Experiment/session ID to backfill or verify. May be repeated.",
    )
    parser.add_argument(
        "--no-poll",
        action="store_true",
        help="Trigger backfills without waiting for feedback completion.",
    )
    args = parser.parse_args()

    experiment_ids = tuple(args.experiment_ids or EXPERIMENT_IDS)
    results: dict[str, Any] = {}
    if args.action in {"provision", "all"}:
        results["provision"] = provision_evaluators(dataset_id=args.dataset_id)
    if args.action in {"backfill", "all"}:
        results["backfill"] = backfill_experiments(
            dataset_id=args.dataset_id,
            experiment_ids=experiment_ids,
            poll=not args.no_poll,
        )
    if args.action in {"verify", "all"}:
        results["verify"] = verify_evaluator_setup(
            dataset_id=args.dataset_id,
            experiment_ids=experiment_ids,
        )
    print(json.dumps(results, indent=2, sort_keys=True))


def _api_settings() -> tuple[str, dict[str, str]]:
    api_key = os.getenv("LANGSMITH_API_KEY", "").strip()
    if not api_key:
        raise LangSmithEvaluatorProvisioningError(
            "Set LANGSMITH_API_KEY before provisioning LangSmith evaluators."
        )
    api_base = os.getenv(
        "LANGSMITH_ENDPOINT",
        "https://api.smith.langchain.com",
    ).strip().rstrip("/")
    return api_base, {"x-api-key": api_key, "content-type": "application/json"}


def _upsert_evaluator(
    api_base: str,
    headers: dict[str, str],
    spec: EvaluatorSpec,
    *,
    http_client: Any,
) -> dict[str, Any]:
    existing = _find_evaluator(
        api_base,
        headers,
        spec.feedback_key,
        http_client=http_client,
    )
    payload = _evaluator_payload(spec)
    if existing:
        evaluator_id = _require_id(existing, f"evaluator {spec.feedback_key}")
        update_payload = {
            key: value
            for key, value in payload.items()
            if key in {"name", "code_evaluator", "llm_evaluator"}
        }
        response = _request(
            http_client.patch,
            f"{api_base}/v1/platform/evaluators/{evaluator_id}",
            headers=headers,
            json=update_payload,
        )
    else:
        response = _request(
            http_client.post,
            f"{api_base}/v1/platform/evaluators",
            headers=headers,
            json=payload,
        )
    return _extract_evaluator(response.json())


def _upsert_rule(
    api_base: str,
    headers: dict[str, str],
    *,
    dataset_id: str,
    spec: EvaluatorSpec,
    evaluator_id: str,
    http_client: Any,
) -> dict[str, Any]:
    existing_rules = _list_rules(
        api_base,
        headers,
        dataset_id=dataset_id,
        http_client=http_client,
    )
    existing_rules = [
        rule
        for rule in existing_rules
        if str(rule.get("evaluator_id") or "").strip() == evaluator_id
    ]
    payload = {
        "display_name": spec.name,
        "dataset_id": dataset_id,
        "sampling_rate": 1.0,
        "is_enabled": True,
        "evaluator_id": evaluator_id,
    }
    if existing_rules:
        rule_id = _require_id(existing_rules[0], f"rule {spec.feedback_key}")
        update_payload = {
            key: value for key, value in payload.items() if key != "evaluator_id"
        }
        response = _request(
            http_client.patch,
            f"{api_base}/api/v1/runs/rules/{rule_id}",
            headers=headers,
            json=update_payload,
        )
    else:
        response = _request(
            http_client.post,
            f"{api_base}/api/v1/runs/rules",
            headers=headers,
            json=payload,
        )
    return _as_dict(response.json())


def _evaluator_payload(spec: EvaluatorSpec) -> dict[str, Any]:
    if spec.evaluator_type == "code":
        return {
            "name": spec.name,
            "type": "code",
            "code_evaluator": {
                "code": spec.code,
                "language": "python",
            },
        }
    prompt_repo_handle = os.getenv(
        spec.prompt_repo_handle_env,
        DEFAULT_LLM_PROMPT_REPO_HANDLE,
    ).strip()
    if not prompt_repo_handle:
        raise LangSmithEvaluatorProvisioningError(
            f"Set {spec.prompt_repo_handle_env} to the LangSmith prompt repo handle "
            "for the llm_reference_judge evaluator."
        )
    prompt_tag = os.getenv(spec.prompt_tag_env, "latest").strip() or "latest"
    return {
        "name": spec.name,
        "type": "llm",
        "llm_evaluator": {
            "prompt_repo_handle": prompt_repo_handle,
            "commit_hash_or_tag": prompt_tag,
            "variable_mapping": {
                "output": "run.outputs",
                "reference": "example.outputs",
            },
        },
    }


def _find_evaluator(
    api_base: str,
    headers: dict[str, str],
    feedback_key: str,
    *,
    http_client: Any,
) -> dict[str, Any] | None:
    response = _request(
        http_client.get,
        f"{api_base}/v1/platform/evaluators",
        headers=headers,
        params={"feedback_key": feedback_key, "limit": 100},
    )
    for evaluator in _evaluator_items(response.json()):
        if feedback_key in evaluator.get("feedback_keys", []):
            return evaluator
    return None


def _list_evaluators(
    api_base: str,
    headers: dict[str, str],
    *,
    http_client: Any,
) -> list[dict[str, Any]]:
    response = _request(
        http_client.get,
        f"{api_base}/v1/platform/evaluators",
        headers=headers,
        params={"limit": 100},
    )
    return _evaluator_items(response.json())


def _list_rules(
    api_base: str,
    headers: dict[str, str],
    *,
    dataset_id: str,
    http_client: Any,
    evaluator_id: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"dataset_id": dataset_id, "include_backfill_progress": True}
    if evaluator_id:
        params["evaluator_id"] = evaluator_id
    response = _request(
        http_client.get,
        f"{api_base}/api/v1/runs/rules",
        headers=headers,
        params=params,
    )
    payload = response.json()
    if not isinstance(payload, list):
        raise LangSmithEvaluatorProvisioningError("LangSmith rules response was not a list.")
    return [_as_dict(rule) for rule in payload]


def _rules_by_feedback_key(
    api_base: str,
    headers: dict[str, str],
    dataset_id: str,
    *,
    http_client: Any,
) -> dict[str, dict[str, Any]]:
    rules = _list_rules(api_base, headers, dataset_id=dataset_id, http_client=http_client)
    by_key: dict[str, dict[str, Any]] = {}
    evaluator_ids = {
        str(rule.get("evaluator_id") or "").strip()
        for rule in rules
        if str(rule.get("evaluator_id") or "").strip()
    }
    evaluators = _list_evaluators(api_base, headers, http_client=http_client)
    evaluator_keys_by_id = {
        str(evaluator.get("id")): set(_feedback_keys_for_evaluator(evaluator))
        for evaluator in evaluators
        if str(evaluator.get("id")) in evaluator_ids
    }
    for rule in rules:
        evaluator_id = str(rule.get("evaluator_id") or "").strip()
        for key in evaluator_keys_by_id.get(evaluator_id, set()):
            if key in FEEDBACK_KEYS:
                by_key[key] = rule
    return by_key


def _langsmith_client(client_factory: Any | None) -> Any:
    if client_factory is not None:
        return client_factory()
    from langsmith import Client

    return Client()


def _root_run_ids(client: Any, experiment_id: str) -> list[str]:
    runs = client.list_runs(project_id=experiment_id, is_root=True)
    return [str(_get_attr(run, "id")) for run in runs if _get_attr(run, "id")]


def _matching_feedback_rows(client: Any, *, run_ids: list[str]) -> list[Any]:
    if not run_ids:
        return []
    rows = client.list_feedback(run_ids=run_ids, feedback_key=list(FEEDBACK_KEYS))
    return list(rows)


def _backup_feedback_rows(rows: list[Any]) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = Path("/tmp") / f"cv_eval_langsmith_feedback_backup_{timestamp}.json"
    payload = [_jsonable_feedback(row) for row in rows]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _poll_feedback(
    client: Any,
    run_ids_by_experiment: dict[str, list[str]],
    *,
    timeout_seconds: int,
    interval_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        status = {
            experiment_id: _feedback_key_counts(client, run_ids)
            for experiment_id, run_ids in run_ids_by_experiment.items()
        }
        if _all_feedback_complete(status):
            return {"complete": True, "experiments": status}
        if time.monotonic() >= deadline:
            return {"complete": False, "experiments": status}
        time.sleep(interval_seconds)


def _feedback_key_counts(client: Any, run_ids: list[str]) -> dict[str, Any]:
    rows = _matching_feedback_rows(client, run_ids=run_ids)
    run_keys: dict[str, set[str]] = {run_id: set() for run_id in run_ids}
    duplicates: dict[str, int] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for row in rows:
        run_id = str(_get_attr(row, "run_id", "") or "")
        key = str(_get_attr(row, "key", "") or "")
        if run_id not in run_keys or key not in FEEDBACK_KEYS:
            continue
        pair = (run_id, key)
        if pair in seen_pairs:
            duplicates[f"{run_id}:{key}"] = duplicates.get(f"{run_id}:{key}", 1) + 1
        seen_pairs.add(pair)
        run_keys[run_id].add(key)
    missing = {
        run_id: [key for key in FEEDBACK_KEYS if key not in keys]
        for run_id, keys in run_keys.items()
        if len(keys) < len(FEEDBACK_KEYS)
    }
    return {
        "root_runs": len(run_ids),
        "expected_feedback_rows": len(run_ids) * len(FEEDBACK_KEYS),
        "found_feedback_rows": len(seen_pairs),
        "missing": missing,
        "duplicates": duplicates,
    }


def _all_feedback_complete(status: dict[str, Any]) -> bool:
    return all(
        not experiment_status["missing"] and not experiment_status["duplicates"]
        for experiment_status in status.values()
    )


def _request(request_fn: Any, url: str, **kwargs: Any) -> Any:
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    response = request_fn(url, **kwargs)
    try:
        response.raise_for_status()
    except Exception as exc:
        body = getattr(response, "text", "") or ""
        raise LangSmithEvaluatorProvisioningError(
            f"LangSmith API request failed for {url}: {body[:500]}"
        ) from exc
    return response


def _evaluator_items(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("evaluators", [])
    else:
        items = payload
    if not isinstance(items, list):
        raise LangSmithEvaluatorProvisioningError(
            "LangSmith evaluator response did not include an evaluator list."
        )
    return [_extract_evaluator(item) for item in items]


def _extract_evaluator(payload: object) -> dict[str, Any]:
    item = _as_dict(payload)
    if isinstance(item.get("evaluator"), dict):
        item = item["evaluator"]
    return item


def _as_dict(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LangSmithEvaluatorProvisioningError("LangSmith response was not an object.")
    return payload


def _require_id(payload: dict[str, Any], label: str) -> str:
    value = str(payload.get("id") or "").strip()
    if not value:
        raise LangSmithEvaluatorProvisioningError(f"LangSmith {label} did not include an id.")
    return value


def _feedback_id(row: Any) -> str:
    value = str(_get_attr(row, "id", "") or "")
    if not value:
        raise LangSmithEvaluatorProvisioningError("Feedback row did not include an id.")
    return value


def _get_attr(source: object, key: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _jsonable_feedback(row: Any) -> dict[str, Any]:
    if hasattr(row, "model_dump"):
        data = row.model_dump(mode="json")
    elif isinstance(row, dict):
        data = dict(row)
    else:
        data = {
            key: _get_attr(row, key)
            for key in ("id", "run_id", "key", "score", "value", "comment")
        }
    return {key: value for key, value in data.items() if key != "api_key"}


def _json_summary(response: Any) -> str:
    try:
        payload = response.json()
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("status") or payload.get("message") or payload.get("id") or "")


def _summarize_evaluator(evaluator: dict[str, Any], spec: EvaluatorSpec) -> dict[str, Any]:
    return {
        "id": evaluator.get("id", ""),
        "name": evaluator.get("name", spec.name),
        "type": evaluator.get("type", spec.evaluator_type),
        "feedback_key": spec.feedback_key,
    }


def _summarize_rule(rule: dict[str, Any], spec: EvaluatorSpec) -> dict[str, Any]:
    return {
        "id": rule.get("id", ""),
        "display_name": rule.get("display_name", spec.name),
        "feedback_key": spec.feedback_key,
        "is_enabled": rule.get("is_enabled"),
        "sampling_rate": rule.get("sampling_rate"),
    }


def _feedback_keys_for_evaluator(evaluator: dict[str, Any]) -> list[str]:
    keys = evaluator.get("feedback_keys", [])
    if isinstance(keys, list) and keys:
        return [str(key) for key in keys]
    evaluator_name = str(evaluator.get("name") or "").strip()
    evaluator_type = str(evaluator.get("type") or "").strip()
    for spec in evaluator_specs():
        if spec.evaluator_type == evaluator_type and spec.name == evaluator_name:
            return [spec.feedback_key]
    return []


if __name__ == "__main__":
    main()
