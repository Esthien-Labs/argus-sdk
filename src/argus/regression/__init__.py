"""Argus regression - controller regression evaluation module.

Provides the regression evaluation pipeline:
  - schema.py     Controller regression profile schema and validation
  - standards.py  Governed standards registry and citation mapping
  - pipeline.py   Core evaluation pipeline (fault injection, baseline comparison)
  - report.py     Output generators (JSON, Markdown, HTML, evidence manifest)
"""

from .schema import (
    ControllerRegressionProfile,
    ControllerRegressionSchemaError,
    FaultCase,
    FaultKind,
    InterfaceType,
    SafetyFunctionClass,
    load_controller_regression_profile,
)
from .standards import (
    GOVERNED_STANDARDS,
    StandardsCitationError,
    validate_standards_citations,
)
from .pipeline import (
    EvaluationResult,
    FaultCaseResult,
    RegressionEvaluationError,
    run_regression_evaluation,
)
from .report import (
    write_regression_report,
)

__all__ = [
    # schema
    "ControllerRegressionProfile",
    "ControllerRegressionSchemaError",
    "FaultCase",
    "FaultKind",
    "InterfaceType",
    "SafetyFunctionClass",
    "load_controller_regression_profile",
    # standards
    "GOVERNED_STANDARDS",
    "StandardsCitationError",
    "validate_standards_citations",
    # pipeline
    "EvaluationResult",
    "FaultCaseResult",
    "RegressionEvaluationError",
    "run_regression_evaluation",
    # report
    "write_regression_report",
]
