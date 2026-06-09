"""Compatibility wrapper for the LangSmith evaluation runner."""

from docs.langsmith.evaluation.src import run_evaluation as _impl
from docs.langsmith.evaluation.src.run_evaluation import *  # noqa: F403

_coerce_project_feedback_rows = _impl._coerce_project_feedback_rows
_coerce_result_rows = _impl._coerce_result_rows
main = _impl.main


if __name__ == "__main__":
    main()
