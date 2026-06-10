from __future__ import annotations

import importlib
from pathlib import Path

import pytest

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
from evaluation.cv_eval.provision_evaluators import (
    DATASET_ID,
    EXPERIMENT_IDS,
    FEEDBACK_KEYS,
    LangSmithEvaluatorProvisioningError,
    backfill_experiments,
    evaluator_specs,
    provision_evaluators,
    verify_evaluator_setup,
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
        "evaluation.cv_eval.provision_evaluators",
    ):
        importlib.reload(importlib.import_module(module_name))


def test_platform_evaluator_specs_use_canonical_feedback_keys() -> None:
    specs = evaluator_specs()

    assert tuple(spec.feedback_key for spec in specs) == FEEDBACK_KEYS
    assert [spec.evaluator_type for spec in specs] == [
        "code",
        "code",
        "code",
        "code",
        "llm",
    ]
    assert all("perform_eval" in spec.code for spec in specs[:4])


def test_provision_evaluators_creates_platform_resources_and_rules(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://eu.api.smith.langchain.com")
    monkeypatch.setenv("CV_EVAL_LLM_PROMPT_REPO_HANDLE", "owner/cv-reference-judge")
    http_client = FakeEvaluatorProvisionHttpClient()

    result = provision_evaluators(http_client=http_client)

    assert result["dataset_id"] == DATASET_ID
    assert [item["feedback_key"] for item in result["evaluators"]] == list(FEEDBACK_KEYS)
    assert [item["feedback_key"] for item in result["rules"]] == list(FEEDBACK_KEYS)
    assert len(http_client.created_evaluators) == 5
    assert len(http_client.created_rules) == 5
    llm_payload = http_client.created_evaluators[-1]
    assert llm_payload["type"] == "llm"
    assert llm_payload["llm_evaluator"]["prompt_repo_handle"] == "owner/cv-reference-judge"
    assert llm_payload["llm_evaluator"]["variable_mapping"] == {
        "output": "run.outputs",
        "reference": "example.outputs",
    }
    assert all(payload["sampling_rate"] == 1.0 for payload in http_client.created_rules)


def test_provision_evaluators_requires_llm_prompt_handle(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("CV_EVAL_LLM_PROMPT_REPO_HANDLE", "")

    with pytest.raises(
        LangSmithEvaluatorProvisioningError,
        match="CV_EVAL_LLM_PROMPT_REPO_HANDLE",
    ):
        provision_evaluators(http_client=FakeEvaluatorProvisionHttpClient())


def test_backfill_backs_up_deletes_and_triggers_rules(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://eu.api.smith.langchain.com")
    monkeypatch.chdir(tmp_path)
    http_client = FakeEvaluatorProvisionHttpClient(with_existing=True)
    langsmith_client = FakeBackfillLangSmithClient()

    result = backfill_experiments(
        http_client=http_client,
        client_factory=lambda: langsmith_client,
        poll=False,
    )

    assert result["deleted_feedback_rows"] == len(FEEDBACK_KEYS)
    assert len(langsmith_client.deleted_feedback_ids) == len(FEEDBACK_KEYS)
    assert len(http_client.triggered_evaluations) == len(EXPERIMENT_IDS) * len(FEEDBACK_KEYS)
    backup = Path(result["backup_path"])
    assert backup.exists()
    backup_rows = backup.read_text(encoding="utf-8")
    assert "cv_extraction_correctness" in backup_rows
    assert "irrelevant_feedback" not in backup_rows


def test_verify_evaluator_setup_reports_missing_feedback(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    http_client = FakeEvaluatorProvisionHttpClient(with_existing=True)
    langsmith_client = FakeBackfillLangSmithClient()

    result = verify_evaluator_setup(
        http_client=http_client,
        client_factory=lambda: langsmith_client,
    )

    assert result["platform_evaluators"]["missing"] == []
    assert result["dataset_rules"]["missing"] == []
    first_experiment = result["experiments"][EXPERIMENT_IDS[0]]
    assert first_experiment["root_runs"] == 1
    assert first_experiment["found_feedback_rows"] == len(FEEDBACK_KEYS)


class FakeEvaluatorResponse:
    def __init__(self, payload: object, *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> object:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} error")


class FakeEvaluatorProvisionHttpClient:
    def __init__(self, *, with_existing: bool = False) -> None:
        self.created_evaluators: list[dict[str, object]] = []
        self.created_rules: list[dict[str, object]] = []
        self.triggered_evaluations: list[tuple[str, str]] = []
        self.evaluators = []
        self.rules = []
        if with_existing:
            for index, key in enumerate(FEEDBACK_KEYS, start=1):
                evaluator_id = f"00000000-0000-0000-0000-0000000000{index:02d}"
                self.evaluators.append(
                    {
                        "id": evaluator_id,
                        "name": key,
                        "type": "code" if key != "llm_reference_judge" else "llm",
                        "feedback_keys": [key],
                    }
                )
                self.rules.append(
                    {
                        "id": f"10000000-0000-0000-0000-0000000000{index:02d}",
                        "evaluator_id": evaluator_id,
                        "display_name": key,
                        "dataset_id": DATASET_ID,
                        "is_enabled": True,
                        "sampling_rate": 1.0,
                    }
                )

    def get(self, url: str, **kwargs: object) -> FakeEvaluatorResponse:
        params = kwargs.get("params", {})
        if not isinstance(params, dict):
            params = {}
        if url.endswith("/v1/platform/evaluators"):
            feedback_key = params.get("feedback_key")
            evaluators = self.evaluators
            if feedback_key:
                evaluators = [
                    item for item in evaluators if feedback_key in item["feedback_keys"]
                ]
            return FakeEvaluatorResponse(
                {"evaluators": evaluators, "total": len(evaluators)}
            )
        if url.endswith("/api/v1/runs/rules"):
            evaluator_id = params.get("evaluator_id")
            rules = self.rules
            if evaluator_id:
                rules = [item for item in rules if item["evaluator_id"] == evaluator_id]
            return FakeEvaluatorResponse(rules)
        raise AssertionError(url)

    def post(self, url: str, **kwargs: object) -> FakeEvaluatorResponse:
        payload = kwargs.get("json", {})
        assert isinstance(payload, dict)
        if url.endswith("/v1/platform/evaluators"):
            feedback_key = _feedback_key_from_evaluator_payload(payload)
            evaluator = {
                "id": f"evaluator-{len(self.evaluators) + 1}",
                "name": payload["name"],
                "type": payload["type"],
                "feedback_keys": [feedback_key],
            }
            self.created_evaluators.append(payload)
            self.evaluators.append(evaluator)
            return FakeEvaluatorResponse({"evaluator": evaluator})
        if url.endswith("/api/v1/runs/rules"):
            rule = {
                "id": f"rule-{len(self.rules) + 1}",
                "evaluator_id": payload["evaluator_id"],
                "display_name": payload["display_name"],
                "dataset_id": payload["dataset_id"],
                "is_enabled": payload["is_enabled"],
                "sampling_rate": payload["sampling_rate"],
            }
            self.created_rules.append(payload)
            self.rules.append(rule)
            return FakeEvaluatorResponse(rule)
        if "/api/v1/runs/experiments/" in url and url.endswith("/evaluate"):
            experiment_id = url.split("/api/v1/runs/experiments/")[1].split("/")[0]
            self.triggered_evaluations.append((experiment_id, str(payload["rule_id"])))
            return FakeEvaluatorResponse({"status": "ok"})
        raise AssertionError(url)

    def patch(self, url: str, **kwargs: object) -> FakeEvaluatorResponse:
        payload = kwargs.get("json", {})
        assert isinstance(payload, dict)
        if "/v1/platform/evaluators/" in url:
            evaluator_id = url.rsplit("/", 1)[1]
            evaluator = next(item for item in self.evaluators if item["id"] == evaluator_id)
            evaluator["name"] = payload["name"]
            return FakeEvaluatorResponse({"evaluator": evaluator})
        if "/api/v1/runs/rules/" in url:
            rule_id = url.rsplit("/", 1)[1]
            rule = next(item for item in self.rules if item["id"] == rule_id)
            rule.update(payload)
            return FakeEvaluatorResponse(rule)
        raise AssertionError(url)


def _feedback_key_from_evaluator_payload(payload: dict[str, object]) -> str:
    if payload["type"] == "llm":
        return "llm_reference_judge"
    code_evaluator = payload["code_evaluator"]
    assert isinstance(code_evaluator, dict)
    code = str(code_evaluator["code"])
    return next(key for key in CODE_KEYS_FOR_TESTS if key in code)


CODE_KEYS_FOR_TESTS = FEEDBACK_KEYS[:4]


class FakeRun:
    def __init__(self, run_id: str) -> None:
        self.id = run_id


class FakeFeedback:
    def __init__(self, feedback_id: str, run_id: str, key: str) -> None:
        self.id = feedback_id
        self.run_id = run_id
        self.key = key
        self.score = 1.0
        self.comment = key

    def model_dump(self, mode: str = "python") -> dict[str, object]:
        assert mode in {"python", "json"}
        return {
            "id": self.id,
            "run_id": self.run_id,
            "key": self.key,
            "score": self.score,
            "comment": self.comment,
        }


class FakeBackfillLangSmithClient:
    def __init__(self) -> None:
        self.deleted_feedback_ids: list[str] = []
        self.runs = {
            EXPERIMENT_IDS[0]: [FakeRun("run-baseline")],
            EXPERIMENT_IDS[1]: [FakeRun("run-comparison")],
        }
        self.feedback = [
            *[
                FakeFeedback(f"feedback-{index}", "run-baseline", key)
                for index, key in enumerate(FEEDBACK_KEYS, start=1)
            ],
            FakeFeedback("feedback-other", "run-baseline", "irrelevant_feedback"),
        ]

    def list_runs(self, *, project_id: str, is_root: bool) -> list[FakeRun]:
        assert is_root is True
        return self.runs[project_id]

    def list_feedback(
        self,
        *,
        run_ids: list[str],
        feedback_key: list[str],
    ) -> list[FakeFeedback]:
        return [
            item
            for item in self.feedback
            if item.run_id in run_ids
            and item.key in feedback_key
            and item.id not in self.deleted_feedback_ids
        ]

    def delete_feedback(self, feedback_id: str) -> None:
        self.deleted_feedback_ids.append(feedback_id)
