"""Approved command-line surface for Argus SDK release packages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .adapters.robot_command import generate_synthetic_trace, load_trace
from .packaged_profiles import default_regression_profile_path
from .regression import (
    load_controller_regression_profile,
    run_regression_evaluation,
    write_regression_report,
)
from .release import runtime_info


def _runtime_info(_: argparse.Namespace) -> int:
    print(json.dumps(runtime_info(), indent=2, sort_keys=True))
    return 0


def _regression_evaluation(args: argparse.Namespace) -> int:
    trace_path = Path(args.trace) if args.trace is not None else None
    profile_path = Path(args.profile)

    if args.sample:
        synthetic_trace = generate_synthetic_trace(
            nominal_count=100,
            stale_count=10,
            fault_count=3,
        )
        args.out.mkdir(parents=True, exist_ok=True)
        trace_path = args.out / "sample_trace.argus-trace.json"
        trace_path.write_text(json.dumps(synthetic_trace, indent=2) + "\n", encoding="utf-8")

    if trace_path is None:
        raise ValueError("pass --trace or --sample")

    result = run_regression_evaluation(
        trace=load_trace(trace_path),
        profile=load_controller_regression_profile(profile_path),
        trace_path=trace_path,
        profile_path=profile_path,
        evidence_class="digital_source_verification",
    )
    paths = write_regression_report(result, args.out)
    status = "PASS" if result.all_fault_cases_passed else "FAIL"
    print(f"Argus regression evaluation: {status}")
    print(f"Profile: {result.profile_id}")
    print(f"Fault cases: {result.fault_cases_passed}/{result.fault_cases_total} passed")
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0 if result.all_fault_cases_passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="argus",
        description="Argus SDK controlled software-evaluation command line.",
    )
    parser.add_argument("--version", action="version", version=f"argus {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    runtime = subparsers.add_parser("runtime-info", help="Show package and host information")
    runtime.set_defaults(handler=_runtime_info)

    regression = subparsers.add_parser(
        "regression-eval",
        help="Run the supported software evaluation workflow",
    )
    source = regression.add_mutually_exclusive_group(required=True)
    source.add_argument("--sample", action="store_true", help="Use packaged example inputs")
    source.add_argument("--trace", help="Path to a declared JSON, ROS 2, or MCAP trace")
    regression.add_argument(
        "--profile",
        type=Path,
        default=default_regression_profile_path(),
        help="Path to the evaluation profile",
    )
    regression.add_argument("--out", type=Path, default=Path("out/regression-eval"), help="Output directory")
    regression.set_defaults(handler=_regression_evaluation)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, ValueError) as exc:
        print(f"argus: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
