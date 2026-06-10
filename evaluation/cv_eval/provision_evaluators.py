"""Compatibility wrapper for LangSmith evaluator provisioning."""

from docs.langsmith.evaluation.src.provision_evaluators import *  # noqa: F403
from docs.langsmith.evaluation.src.provision_evaluators import main

if __name__ == "__main__":
    main()
