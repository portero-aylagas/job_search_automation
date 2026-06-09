"""Create or update the LangSmith CV extraction evaluation dataset."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langsmith.utils import LangSmithNotFoundError

DATASET_NAME = "job-search-automation-cv-extraction-fixtures"
DATASET_DESCRIPTION = (
    "Fictional CV, recommendation-letter, and certificate fixtures for evaluating "
    "CandidateCVExtracted structured extraction."
)
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_EXAMPLES_PATH = (
    PROJECT_ROOT
    / "docs"
    / "langsmith"
    / "evaluation"
    / "data"
    / "evaluation_examples.jsonl"
)


def load_examples(path: Path = DEFAULT_EXAMPLES_PATH) -> list[dict[str, Any]]:
    """Load and validate JSONL examples for LangSmith upload."""

    examples: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            example = json.loads(line)
            _validate_example(example, line_number)
            examples.append(example)
    if len(examples) < 10:
        raise ValueError("evaluation_examples.jsonl must contain at least 10 examples.")
    return examples


def create_or_update_dataset(
    *,
    examples_path: Path = DEFAULT_EXAMPLES_PATH,
    dataset_name: str = DATASET_NAME,
) -> object:
    """Create a LangSmith dataset and sync examples by case ID.

    Existing examples are updated when their inputs, reference outputs, or
    metadata differ from the local JSONL fixture. This keeps LangSmith usable
    after correcting gold labels without manually deleting remote examples.
    """

    from langsmith import Client

    client = Client()
    examples = load_examples(examples_path)
    expected_case_ids = _case_ids_from_examples(examples)
    dataset = _get_or_create_dataset(client, dataset_name)
    existing_examples = list(client.list_examples(dataset_id=dataset.id))
    existing_case_ids = _case_ids_from_langsmith_examples(existing_examples)
    missing_case_ids = expected_case_ids - existing_case_ids
    changed_examples = _changed_langsmith_examples(examples, existing_examples)
    if not missing_case_ids and not changed_examples:
        print(
            f"Dataset {dataset_name!r} already has all {len(expected_case_ids)} "
            "expected case IDs and matching payloads."
        )
        return dataset

    examples_to_upload = _missing_examples(examples, existing_case_ids)
    if examples_to_upload:
        client.create_examples(
            dataset_id=dataset.id,
            examples=[_example_payload(example) for example in examples_to_upload],
        )
    for langsmith_example, local_example in changed_examples:
        client.update_example(
            _example_id(langsmith_example),
            **_example_payload(local_example),
        )
    uploaded_examples = list(client.list_examples(dataset_id=dataset.id))
    uploaded_case_ids = _case_ids_from_langsmith_examples(uploaded_examples)
    still_missing = expected_case_ids - uploaded_case_ids
    if still_missing:
        raise RuntimeError(
            "LangSmith dataset is missing expected case IDs after upload: "
            f"{sorted(still_missing)}"
        )
    print(
        f"Uploaded {len(examples_to_upload)} missing examples and updated "
        f"{len(changed_examples)} changed examples in LangSmith dataset "
        f"{dataset_name!r}; dataset now has {len(uploaded_case_ids)} expected case IDs."
    )
    return dataset


def main() -> None:
    """CLI entry point for dataset creation."""

    create_or_update_dataset()


def _get_or_create_dataset(client: object, dataset_name: str) -> object:
    try:
        return client.read_dataset(dataset_name=dataset_name)
    except LangSmithNotFoundError:
        return client.create_dataset(
            dataset_name=dataset_name,
            description=DATASET_DESCRIPTION,
        )


def _case_ids_from_examples(examples: list[dict[str, Any]]) -> set[str]:
    case_ids = {example["inputs"]["case_id"] for example in examples}
    if len(case_ids) != len(examples):
        raise ValueError("Evaluation examples must have unique inputs.case_id values.")
    return case_ids


def _missing_examples(
    examples: list[dict[str, Any]],
    existing_case_ids: set[str],
) -> list[dict[str, Any]]:
    return [
        example
        for example in examples
        if example["inputs"]["case_id"] not in existing_case_ids
    ]


def _changed_langsmith_examples(
    local_examples: list[dict[str, Any]],
    langsmith_examples: list[object],
) -> list[tuple[object, dict[str, Any]]]:
    local_by_case_id = {
        example["inputs"]["case_id"]: example
        for example in local_examples
    }
    changed: list[tuple[object, dict[str, Any]]] = []
    for langsmith_example in langsmith_examples:
        case_id = _example_inputs(langsmith_example).get("case_id")
        if case_id not in local_by_case_id:
            continue
        local_example = local_by_case_id[str(case_id)]
        if _normalized_example_payload(langsmith_example) != _example_payload(local_example):
            changed.append((langsmith_example, local_example))
    return changed


def _case_ids_from_langsmith_examples(examples: list[object]) -> set[str]:
    case_ids: set[str] = set()
    for example in examples:
        inputs = _example_inputs(example)
        case_id = inputs.get("case_id")
        if case_id:
            case_ids.add(str(case_id))
    return case_ids


def _example_inputs(example: object) -> dict[str, Any]:
    if isinstance(example, dict):
        inputs = example.get("inputs", {})
    else:
        inputs = getattr(example, "inputs", {})
    return inputs if isinstance(inputs, dict) else {}


def _example_outputs(example: object) -> dict[str, Any]:
    if isinstance(example, dict):
        outputs = example.get("outputs", {})
    else:
        outputs = getattr(example, "outputs", {})
    return outputs if isinstance(outputs, dict) else {}


def _example_metadata(example: object) -> dict[str, Any]:
    if isinstance(example, dict):
        metadata = example.get("metadata", {})
    else:
        metadata = getattr(example, "metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def _example_id(example: object) -> object:
    if isinstance(example, dict):
        return example.get("id")
    return example.id


def _example_payload(example: dict[str, Any]) -> dict[str, Any]:
    return {
        "inputs": example["inputs"],
        "outputs": example["outputs"],
        "metadata": example.get("metadata", {}),
    }


def _normalized_example_payload(example: object) -> dict[str, Any]:
    return {
        "inputs": _example_inputs(example),
        "outputs": _example_outputs(example),
        "metadata": _example_metadata(example),
    }


def _validate_example(example: dict[str, Any], line_number: int) -> None:
    required_top_level = {"inputs", "outputs"}
    missing = required_top_level - set(example)
    if missing:
        raise ValueError(f"Line {line_number} is missing required keys: {sorted(missing)}")
    inputs = example["inputs"]
    for key in ("case_id", "cv_path", "optional_document_paths", "document_types"):
        if key not in inputs:
            raise ValueError(f"Line {line_number} inputs are missing {key!r}.")
    cv_path = PROJECT_ROOT / inputs["cv_path"]
    if not cv_path.exists():
        raise ValueError(f"Line {line_number} CV path does not exist: {cv_path}")
    for document_path in inputs["optional_document_paths"]:
        path = PROJECT_ROOT / document_path
        if not path.exists():
            raise ValueError(f"Line {line_number} optional path does not exist: {path}")
    outputs = example["outputs"]
    if "identity" not in outputs:
        raise ValueError(f"Line {line_number} outputs are missing identity.")


if __name__ == "__main__":
    main()
