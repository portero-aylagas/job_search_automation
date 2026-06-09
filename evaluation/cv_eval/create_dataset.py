"""Compatibility wrapper for the LangSmith dataset creation script."""

from docs.langsmith.evaluation.src import create_dataset as _impl
from docs.langsmith.evaluation.src.create_dataset import *  # noqa: F403

_case_ids_from_langsmith_examples = _impl._case_ids_from_langsmith_examples
_changed_langsmith_examples = _impl._changed_langsmith_examples
_missing_examples = _impl._missing_examples
main = _impl.main


if __name__ == "__main__":
    main()
