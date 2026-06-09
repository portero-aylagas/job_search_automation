from __future__ import annotations

import importlib
from pathlib import Path

from evaluation.cv_eval.create_dataset import (
    DEFAULT_EXAMPLES_PATH,
    _case_ids_from_langsmith_examples,
    _changed_langsmith_examples,
    _missing_examples,
    load_examples,
)
from evaluation.cv_eval.evaluators import (
    correctness_evaluator,
    evaluation_suite,
    evidence_completeness_evaluator,
    grounding_evaluator,
    llm_judge_evaluator,
    schema_validation_evaluator,
)
from evaluation.cv_eval.run_evaluation import (
    _coerce_project_feedback_rows,
    _coerce_result_rows,
)
from evaluation.cv_eval.target_function import run_target_function
from src.cv_extraction import CVDocumentSnapshot
from src.schemas import (
    CandidateCVExtracted,
    CandidateCVIdentity,
    CandidateSupplementalExtracted,
)


def test_evaluation_examples_load_and_validate_against_schema() -> None:
    examples = load_examples(DEFAULT_EXAMPLES_PATH)

    assert len(examples) == 10
    case_ids = {example["inputs"]["case_id"] for example in examples}
    assert len(case_ids) == 10
    for example in examples:
        assert Path(example["inputs"]["cv_path"]).name == "cv.pdf"
        assert "recommendation_letter" in example["inputs"]["document_types"]
        assert "certificate" in example["inputs"]["document_types"]
        CandidateCVExtracted.model_validate(example["outputs"])


def test_dataset_upload_selects_only_missing_case_ids() -> None:
    examples = load_examples(DEFAULT_EXAMPLES_PATH)
    existing_case_ids = {
        example["inputs"]["case_id"]
        for example in examples[:8]
    }

    missing = _missing_examples(examples, existing_case_ids)

    assert [example["inputs"]["case_id"] for example in missing] == [
        "cv-eval-009",
        "cv-eval-010",
    ]


def test_dataset_upload_treats_complete_case_ids_as_complete() -> None:
    examples = load_examples(DEFAULT_EXAMPLES_PATH)
    langsmith_examples = [
        {"inputs": example["inputs"]}
        for example in examples
    ]

    existing_case_ids = _case_ids_from_langsmith_examples(langsmith_examples)
    missing = _missing_examples(examples, existing_case_ids)

    assert len(existing_case_ids) == 10
    assert missing == []


def test_dataset_updater_detects_changed_examples_by_case_id() -> None:
    examples = load_examples(DEFAULT_EXAMPLES_PATH)
    stale_remote_example = {
        "id": "example-id",
        "inputs": examples[0]["inputs"],
        "outputs": {"identity": {"full_name": "Old Name"}},
        "metadata": examples[0]["metadata"],
    }

    changed = _changed_langsmith_examples(examples, [stale_remote_example])

    assert changed == [(stale_remote_example, examples[0])]


def test_evaluation_exporter_reads_langsmith_dict_result_rows(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-mini")
    experiment = [
        {
            "example": {"inputs": {"case_id": "cv-eval-001"}},
            "run": {"latency_ms": 1234, "total_cost": 0.0123},
            "evaluation_results": {
                "results": [
                    {
                        "key": "cv_extraction_correctness",
                        "score": 0.75,
                        "comment": "partial",
                    }
                ]
            },
        }
    ]

    rows = _coerce_result_rows(experiment)

    assert rows[0]["model"] == "gpt-5.4-mini"
    assert rows[0]["case_id"] == "cv-eval-001"
    assert rows[0]["score_key"] == "cv_extraction_correctness"
    assert rows[0]["score"] == 0.75
    assert rows[0]["comment"] == "partial"
    assert rows[0]["latency_ms"] == "1234"
    assert rows[0]["total_cost_usd"] == "0.0123"


def test_evaluation_exporter_reads_remote_feedback_stats(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4")

    class FakeRun:
        inputs = {"inputs": {"case_id": "cv-eval-001"}}
        total_time = 1.5
        total_cost = 0.02
        feedback_stats = {
            "cv_extraction_correctness": {
                "avg": 0.5,
                "comments": ["identity=0.50; evidence_fields=0.50; score=0.50"],
            }
        }

    class FakeClient:
        def list_runs(self, *, project_id: str, is_root: bool) -> list[FakeRun]:
            assert project_id == "experiment-id"
            assert is_root is True
            return [FakeRun()]

    rows = _coerce_project_feedback_rows(
        FakeClient(),
        project_id="experiment-id",
        experiment_id="experiment-id",
        experiment_name="cv-extraction-test",
    )

    assert rows[0]["model"] == "gpt-5.4"
    assert rows[0]["experiment_id"] == "experiment-id"
    assert rows[0]["experiment_name"] == "cv-extraction-test"
    assert rows[0]["case_id"] == "cv-eval-001"
    assert rows[0]["score_key"] == "cv_extraction_correctness"
    assert rows[0]["score"] == 0.5
    assert rows[0]["latency_ms"] == "1500.0"
    assert rows[0]["total_cost_usd"] == "0.02"


def test_target_function_merges_fake_cv_and_supplemental_extractors() -> None:
    examples = load_examples(DEFAULT_EXAMPLES_PATH)
    inputs = examples[0]["inputs"]

    def fake_inspector(path: Path) -> CVDocumentSnapshot:
        return CVDocumentSnapshot(
            file_path=str(path),
            file_name=path.name,
            file_id=f"file-{path.name}",
            mime_type="application/pdf",
        )

    def fake_cv_extractor(_: CVDocumentSnapshot) -> CandidateCVExtracted:
        return CandidateCVExtracted(
            identity=CandidateCVIdentity(
                full_name="Alice Placeholder",
                first_name="Alice",
                last_name="Placeholder",
                email="alice.placeholder@example.test",
            ),
            skills=["Python"],
        )

    def fake_supplemental_extractor(
        snapshot: CVDocumentSnapshot,
    ) -> CandidateSupplementalExtracted:
        if snapshot.file_name == "certificate.pdf":
            return CandidateSupplementalExtracted(certifications=["Google Data Analytics"])
        return CandidateSupplementalExtracted(references=["Reference from Mira Hoffmann"])

    output = run_target_function(
        inputs,
        inspector=fake_inspector,
        cv_extractor=fake_cv_extractor,
        supplemental_extractor=fake_supplemental_extractor,
    )

    assert output["identity"]["first_name"] == "Alice"
    assert output["skills"] == ["Python"]
    assert output["certifications"] == ["Google Data Analytics"]
    assert output["references"] == ["Reference from Mira Hoffmann"]


def test_correctness_evaluator_scores_correct_partial_and_poor_outputs() -> None:
    reference = load_examples(DEFAULT_EXAMPLES_PATH)[0]["outputs"]
    correct = correctness_evaluator(inputs={}, outputs=reference, reference_outputs=reference)
    partial_output = {
        **reference,
        "identity": {**reference["identity"], "email": "wrong@example.test"},
        "skills": reference["skills"][:1],
        "references": [],
    }
    partial = correctness_evaluator(
        inputs={},
        outputs=partial_output,
        reference_outputs=reference,
    )
    poor = correctness_evaluator(
        inputs={},
        outputs={"identity": {}, "skills": []},
        reference_outputs=reference,
    )

    assert correct["score"] == 1.0
    assert 0 < partial["score"] < 1.0
    assert poor["score"] == 0.0


def test_supplemental_evidence_evaluator_focuses_on_optional_documents() -> None:
    reference = load_examples(DEFAULT_EXAMPLES_PATH)[0]["outputs"]
    missing_optional = {**reference, "certifications": [], "references": []}

    score = evidence_completeness_evaluator(
        inputs={"document_types": ["cv", "recommendation_letter", "certificate"]},
        outputs=missing_optional,
        reference_outputs=reference,
    )

    assert score["key"] == "supplemental_evidence_completeness"
    assert score["score"] == 0.0


def test_schema_and_grounding_evaluators_return_stable_scores() -> None:
    reference = load_examples(DEFAULT_EXAMPLES_PATH)[0]["outputs"]

    schema_score = schema_validation_evaluator(
        inputs={},
        outputs=reference,
        reference_outputs=reference,
    )
    grounded_score = grounding_evaluator(
        inputs={},
        outputs=reference,
        reference_outputs=reference,
    )
    unsupported_score = grounding_evaluator(
        inputs={},
        outputs={**reference, "skills": [*reference["skills"], "invented skill"]},
        reference_outputs=reference,
    )

    assert schema_score["key"] == "cv_schema_validity"
    assert schema_score["score"] == 1.0
    assert grounded_score["key"] == "reference_grounding"
    assert grounded_score["score"] == 1.0
    assert unsupported_score["score"] < 1.0
    assert "invented skill" in unsupported_score["comment"]


def test_optional_llm_judge_is_skipped_when_disabled_or_without_credentials(
    monkeypatch,
) -> None:
    reference = load_examples(DEFAULT_EXAMPLES_PATH)[0]["outputs"]

    monkeypatch.delenv("CV_EVAL_ENABLE_LLM_JUDGE", raising=False)
    disabled = llm_judge_evaluator(
        inputs={},
        outputs=reference,
        reference_outputs=reference,
    )
    assert disabled["key"] == "llm_reference_judge"
    assert disabled["score"] is None
    assert "skipped" in disabled["comment"]
    assert llm_judge_evaluator not in evaluation_suite()

    monkeypatch.setenv("CV_EVAL_ENABLE_LLM_JUDGE", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    missing_credentials = llm_judge_evaluator(
        inputs={},
        outputs=reference,
        reference_outputs=reference,
    )
    assert missing_credentials["score"] is None
    assert "OPENAI_API_KEY" in missing_credentials["comment"]
    assert llm_judge_evaluator in evaluation_suite()


def test_evaluation_modules_import_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    for module_name in (
        "evaluation.cv_eval.create_dataset",
        "evaluation.cv_eval.target_function",
        "evaluation.cv_eval.evaluators",
        "evaluation.cv_eval.run_evaluation",
    ):
        importlib.reload(importlib.import_module(module_name))
