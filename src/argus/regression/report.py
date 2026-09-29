"""Regression evaluation report generators (Stage 0C).

Produces four output files from an EvaluationResult:
  regression_report.json        machine-readable full results
  regression_report.md          human-readable with evidence boundary header
  regression_report.html        formatted for customer delivery
  evidence_manifest.json        source/build hashes, tool versions, standard section citations

All outputs include an evidence boundary statement as the FIRST section.
This is not skippable. The evidence class limitations are stated explicitly.

Evidence boundary rule: these reports are digital_source_verification evidence.
They do not constitute physical safety certification or customer validation.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .pipeline import EvaluationResult, FaultCaseResult
from .standards import STANDARD_SECTION_MAP, get_coverage_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _us_to_ms(us: float | None) -> str:
    if us is None:
        return "N/A"
    return f"{us / 1000:.3f} ms"


def _pct(rate: float) -> str:
    return f"{rate * 100:.2f}%"


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------

def _build_json_report(result: EvaluationResult) -> dict[str, Any]:
    """Build the machine-readable full results dict."""
    return {
        "schema_version": "1.0",
        "product": "Atlas Controller Regression Evaluation",
        "evaluation_id": result.evaluation_id,
        "generated_utc": result.generated_utc,
        "profile_id": result.profile_id,
        "evidence_class": result.evidence_class,

        # Section 1: Evidence boundary (mandatory first section)
        "evidence_boundary": {
            "what_this_proves": result.what_this_proves,
            "what_this_does_not_prove": result.what_this_does_not_prove,
            "applicable_standards": [
                {
                    "standard": std,
                    "sections": list(STANDARD_SECTION_MAP.get(std, {}).keys()),
                    "coverage": get_coverage_text(std, list(STANDARD_SECTION_MAP.get(std, {}).keys())[0])
                    if STANDARD_SECTION_MAP.get(std)
                    else f"Fault corpus and command-guard evidence relevant to {std}",
                }
                for std in result.applicable_standards
            ],
        },

        # Section 2: Baseline behavior
        "baseline_behavior": {
            "nominal_completion_rate": round(result.baseline_nominal_completion_rate, 6),
            "false_intervention_rate": round(result.baseline_false_intervention_rate, 6),
            "p95_latency_us": result.baseline_p95_latency_us,
            "p99_latency_us": result.baseline_p99_latency_us,
            "max_latency_us": result.baseline_max_latency_us,
            "sample_count": result.baseline_sample_count,
            "latency_label": "host_measured_not_embedded_not_worst_case_bound",
        },

        # Section 3: Fault matrix
        "fault_matrix": {
            "total": result.fault_cases_total,
            "passed": result.fault_cases_passed,
            "failed": result.fault_cases_failed,
            "all_passed": result.all_fault_cases_passed,
            "cases": [
                {
                    "fault_id": fr.fault_id,
                    "fault_kind": fr.fault_kind,
                    "description": fr.description,
                    "expected_state": fr.expected_state,
                    "baseline_observed_state": fr.baseline_observed_state,
                    "baseline_pass": fr.baseline_pass,
                    "baseline_latency_us": fr.baseline_latency_us,
                    "atlas_observed_state": fr.atlas_observed_state,
                    "atlas_pass": fr.atlas_pass,
                    "atlas_latency_us": fr.atlas_latency_us,
                    "notes": fr.notes,
                }
                for fr in result.fault_results
            ],
        },

        # Section 4: Comparison table
        "comparison": {
            "nominal_task_completion_rate": {
                "baseline": round(result.baseline_nominal_completion_rate, 6),
                "atlas_supervised": round(result.atlas_nominal_completion_rate, 6),
            },
            "false_stop_rate": {
                "baseline": round(result.baseline_false_intervention_rate, 6),
                "atlas_supervised": round(result.atlas_false_stop_rate, 6),
            },
            "p95_latency_us": {
                "baseline": result.baseline_p95_latency_us,
                "atlas_supervised": result.atlas_p95_latency_us,
                "label": "host_measured_not_embedded_not_worst_case_bound",
            },
            "p99_latency_us": {
                "baseline": result.baseline_p99_latency_us,
                "atlas_supervised": result.atlas_p99_latency_us,
            },
            "max_latency_us": {
                "baseline": result.baseline_max_latency_us,
                "atlas_supervised": result.atlas_max_latency_us,
                "label": "finite_observed_maximum_not_worst_case",
            },
            "sample_count": result.atlas_sample_count,
        },

        # Section 5: Limitations (mandatory)
        "limitations": result.limitations,
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def _build_markdown_report(result: EvaluationResult) -> str:
    lines: list[str] = []
    a = lines.append

    a("# Atlas Controller Regression Evaluation Report")
    a("")
    a(f"**Evaluation ID:** `{result.evaluation_id}`")
    a(f"**Profile:** `{result.profile_id}`")
    a(f"**Evidence class:** `{result.evidence_class}`")
    a(f"**Generated:** {result.generated_utc}")
    a("")

    # Section 1: Evidence boundary (FIRST - mandatory)
    a("---")
    a("")
    a("## Section 1: Evidence Boundary Statement")
    a("")
    a("> **This section is mandatory and not skippable.**  ")
    a("> All claims in this report are bounded by the evidence class and limitations below.")
    a("")
    a("### What this evaluation proves")
    a("")
    a(result.what_this_proves)
    a("")
    a("### What this evaluation does NOT prove")
    a("")
    for item in result.what_this_does_not_prove:
        a(f"- {item}")
    a("")
    a("### Applicable standards")
    a("")
    a("| Standard | Coverage |")
    a("|---|---|")
    for std in result.applicable_standards:
        sections = STANDARD_SECTION_MAP.get(std, {})
        if sections:
            first_section, coverage = next(iter(sections.items()))
            a(f"| {std} ({first_section}) | {coverage} |")
        else:
            a(f"| {std} | Fault corpus and command-guard evidence |")
    a("")

    # Section 2: Baseline behavior
    a("---")
    a("")
    a("## Section 2: Baseline Behavior Record")
    a("")
    a("| Metric | Value |")
    a("|---|---|")
    a(f"| Nominal completion rate | {_pct(result.baseline_nominal_completion_rate)} |")
    a(f"| False intervention rate | {_pct(result.baseline_false_intervention_rate)} |")
    a(f"| p95 latency (host) | {_us_to_ms(result.baseline_p95_latency_us)} |")
    a(f"| p99 latency (host) | {_us_to_ms(result.baseline_p99_latency_us)} |")
    a(f"| Max latency (host) | {_us_to_ms(result.baseline_max_latency_us)} |")
    a(f"| Sample count | {result.baseline_sample_count} |")
    a("")
    a("> Latency is host-measured. It is not an embedded timing result and is not a worst-case bound.")
    a("")

    # Section 3: Fault matrix
    a("---")
    a("")
    a("## Section 3: Fault Matrix Results")
    a("")
    a(f"**Total fault cases:** {result.fault_cases_total}")
    a(f"**Passed (Atlas):** {result.fault_cases_passed}")
    a(f"**Failed (Atlas):** {result.fault_cases_failed}")
    a(f"**All passed:** {'YES' if result.all_fault_cases_passed else 'NO'}")
    a("")
    a("| Fault ID | Kind | Expected | Baseline | Atlas | Pass |")
    a("|---|---|---|---|---|---|")
    for fr in result.fault_results:
        icon = "PASS" if fr.atlas_pass else "FAIL"
        a(f"| {fr.fault_id} | {fr.fault_kind} | {fr.expected_state} | "
          f"{fr.baseline_observed_state} | {fr.atlas_observed_state} | {icon} |")
    a("")

    # Section 4: Comparison
    a("---")
    a("")
    a("## Section 4: Comparison Table (Baseline vs Atlas-Supervised)")
    a("")
    a("| Metric | Baseline | Atlas Supervised |")
    a("|---|---|---|")
    a(f"| Nominal completion rate | {_pct(result.baseline_nominal_completion_rate)} | {_pct(result.atlas_nominal_completion_rate)} |")
    a(f"| False stop rate | {_pct(result.baseline_false_intervention_rate)} | {_pct(result.atlas_false_stop_rate)} |")
    a(f"| p95 latency (host) | {_us_to_ms(result.baseline_p95_latency_us)} | {_us_to_ms(result.atlas_p95_latency_us)} |")
    a(f"| p99 latency (host) | {_us_to_ms(result.baseline_p99_latency_us)} | {_us_to_ms(result.atlas_p99_latency_us)} |")
    a(f"| Max latency (host, observed) | {_us_to_ms(result.baseline_max_latency_us)} | {_us_to_ms(result.atlas_max_latency_us)} |")
    a(f"| Sample count | {result.baseline_sample_count} | {result.atlas_sample_count} |")
    a("")
    a("> **False stop rate** is the fraction of valid commands (not stale, not duplicate,")
    a("> not out-of-range) that Atlas stopped. A non-zero false stop rate indicates over-sensitivity.")
    a("")

    # Section 5: Limitations
    a("---")
    a("")
    a("## Section 5: Limitations")
    a("")
    for lim in result.limitations:
        a(f"- {lim}")
    a("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Atlas Controller Regression Evaluation - {profile_id}</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 900px; margin: 40px auto; color: #111; }}
  h1 {{ color: #101113; border-bottom: 2px solid #FF6A3D; padding-bottom: 8px; }}
  h2 {{ color: #2F5BFF; margin-top: 2em; }}
  .boundary-box {{ background: #fff8f0; border-left: 4px solid #FF6A3D;
                   padding: 16px 20px; margin: 16px 0; border-radius: 4px; }}
  .pass {{ color: #1a7f37; font-weight: bold; }}
  .fail {{ color: #cf222e; font-weight: bold; }}
  .meta {{ color: #555; font-size: 0.9em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th {{ background: #101113; color: #F4F1EB; padding: 8px 12px; text-align: left; }}
  td {{ border: 1px solid #ddd; padding: 8px 12px; }}
  tr:nth-child(even) td {{ background: #f9f9f9; }}
  ul {{ padding-left: 1.5em; }}
  .evidence-class {{ background: #101113; color: #FF6A3D;
                     padding: 2px 8px; border-radius: 3px; font-family: monospace; }}
</style>
</head>
<body>
<h1>Atlas Controller Regression Evaluation</h1>
<p class="meta"><strong>Evaluation ID:</strong> {evaluation_id}<br>
<strong>Profile:</strong> {profile_id}<br>
<strong>Evidence class:</strong> <span class="evidence-class">{evidence_class}</span><br>
<strong>Generated:</strong> {generated_utc}</p>

<div class="boundary-box">
<h2 style="margin-top:0; color:#FF6A3D;">Section 1: Evidence Boundary Statement</h2>
<p><strong>This section is mandatory. All report claims are bounded by this statement.</strong></p>
<h3>What this evaluation proves</h3>
<p>{what_this_proves}</p>
<h3>What this evaluation does NOT prove</h3>
<ul>{does_not_prove_items}</ul>
<h3>Applicable standards</h3>
<table>
<tr><th>Standard</th><th>Section</th><th>Coverage</th></tr>
{standards_rows}
</table>
</div>

<h2>Section 2: Baseline Behavior Record</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Nominal completion rate</td><td>{baseline_completion}</td></tr>
<tr><td>False intervention rate</td><td>{baseline_false_int}</td></tr>
<tr><td>p95 latency (host-measured)</td><td>{baseline_p95}</td></tr>
<tr><td>p99 latency (host-measured)</td><td>{baseline_p99}</td></tr>
<tr><td>Max latency (host, observed)</td><td>{baseline_max}</td></tr>
<tr><td>Sample count</td><td>{baseline_n}</td></tr>
</table>
<p><em>All latency values are host-process timestamps. They are not embedded timing results
and do not constitute a worst-case latency bound.</em></p>

<h2>Section 3: Fault Matrix Results</h2>
<p><strong>Total:</strong> {fault_total} &nbsp;
<strong>Passed:</strong> <span class="pass">{fault_passed}</span> &nbsp;
<strong>Failed:</strong> <span class="fail">{fault_failed}</span></p>
<table>
<tr><th>Fault ID</th><th>Kind</th><th>Expected</th><th>Baseline</th><th>Atlas</th><th>Result</th></tr>
{fault_rows}
</table>

<h2>Section 4: Comparison Table</h2>
<table>
<tr><th>Metric</th><th>Baseline</th><th>Atlas Supervised</th></tr>
<tr><td>Nominal completion rate</td><td>{baseline_completion}</td><td>{atlas_completion}</td></tr>
<tr><td>False stop rate</td><td>{baseline_false_int}</td><td>{atlas_false_stop}</td></tr>
<tr><td>p95 latency (host)</td><td>{baseline_p95}</td><td>{atlas_p95}</td></tr>
<tr><td>p99 latency (host)</td><td>{baseline_p99}</td><td>{atlas_p99}</td></tr>
<tr><td>Max latency (host, observed)</td><td>{baseline_max}</td><td>{atlas_max}</td></tr>
<tr><td>Sample count</td><td colspan="2">{atlas_n}</td></tr>
</table>

<h2>Section 5: Limitations</h2>
<ul>{limitation_items}</ul>

<hr>
<p class="meta">Atlas Platform v{atlas_version} - Esthien Labs - esthien.com<br>
This report is {evidence_class} evidence. See evidence boundary statement (Section 1).</p>
</body>
</html>
"""


def _build_html_report(result: EvaluationResult) -> str:
    does_not_prove_items = "".join(f"<li>{item}</li>" for item in result.what_this_does_not_prove)
    limitation_items = "".join(f"<li>{lim}</li>" for lim in result.limitations)

    standards_rows_parts = []
    for std in result.applicable_standards:
        sections = STANDARD_SECTION_MAP.get(std, {})
        if sections:
            for section, coverage in sections.items():
                standards_rows_parts.append(
                    f"<tr><td>{std}</td><td>{section}</td><td>{coverage}</td></tr>"
                )
        else:
            standards_rows_parts.append(
                f"<tr><td>{std}</td><td>-</td>"
                f"<td>Fault corpus and command-guard evidence</td></tr>"
            )
    standards_rows = "\n".join(standards_rows_parts)

    fault_rows_parts = []
    for fr in result.fault_results:
        result_cell = (
            '<span class="pass">PASS</span>'
            if fr.atlas_pass
            else '<span class="fail">FAIL</span>'
        )
        fault_rows_parts.append(
            f"<tr><td>{fr.fault_id}</td><td>{fr.fault_kind}</td>"
            f"<td>{fr.expected_state}</td><td>{fr.baseline_observed_state}</td>"
            f"<td>{fr.atlas_observed_state}</td><td>{result_cell}</td></tr>"
        )
    fault_rows = "\n".join(fault_rows_parts)

    return _HTML_TEMPLATE.format(
        profile_id=result.profile_id,
        evaluation_id=result.evaluation_id,
        evidence_class=result.evidence_class,
        generated_utc=result.generated_utc,
        what_this_proves=result.what_this_proves,
        does_not_prove_items=does_not_prove_items,
        standards_rows=standards_rows,
        baseline_completion=_pct(result.baseline_nominal_completion_rate),
        baseline_false_int=_pct(result.baseline_false_intervention_rate),
        baseline_p95=_us_to_ms(result.baseline_p95_latency_us),
        baseline_p99=_us_to_ms(result.baseline_p99_latency_us),
        baseline_max=_us_to_ms(result.baseline_max_latency_us),
        baseline_n=result.baseline_sample_count,
        fault_total=result.fault_cases_total,
        fault_passed=result.fault_cases_passed,
        fault_failed=result.fault_cases_failed,
        fault_rows=fault_rows,
        atlas_completion=_pct(result.atlas_nominal_completion_rate),
        atlas_false_stop=_pct(result.atlas_false_stop_rate),
        atlas_p95=_us_to_ms(result.atlas_p95_latency_us),
        atlas_p99=_us_to_ms(result.atlas_p99_latency_us),
        atlas_max=_us_to_ms(result.atlas_max_latency_us),
        atlas_n=result.atlas_sample_count,
        limitation_items=limitation_items,
        atlas_version=result.atlas_version,
    )


# ---------------------------------------------------------------------------
# Evidence manifest
# ---------------------------------------------------------------------------

def _build_evidence_manifest(
    result: EvaluationResult,
    output_dir: Path,
    json_sha256: str,
    md_sha256: str,
    html_sha256: str,
) -> dict[str, Any]:
    """Build the evidence manifest (evidence_manifest.json)."""
    standards_citations = []
    for std in result.applicable_standards:
        sections = STANDARD_SECTION_MAP.get(std, {})
        for section, coverage in sections.items():
            standards_citations.append({
                "standard": std,
                "section": section,
                "coverage": coverage,
            })
        if not sections:
            standards_citations.append({
                "standard": std,
                "section": "-",
                "coverage": f"Fault corpus and command-guard evidence relevant to {std}",
            })

    return {
        "schema_version": "1.0",
        "product": "Atlas Controller Regression Evaluation",
        "evaluation_id": result.evaluation_id,
        "generated_utc": result.generated_utc,
        "evidence_class": result.evidence_class,
        "applicable_standards": standards_citations,
        "sources": {
            "trace_sha256": result.trace_sha256,
            "profile_sha256": result.profile_sha256,
            "atlas_version": result.atlas_version,
            "tool_versions": {
                "python": sys.version.split()[0],
            },
        },
        "outputs": {
            "regression_report_json_sha256": json_sha256,
            "regression_report_md_sha256": md_sha256,
            "regression_report_html_sha256": html_sha256,
        },
        "summary": {
            "profile_id": result.profile_id,
            "fault_cases_total": result.fault_cases_total,
            "fault_cases_passed": result.fault_cases_passed,
            "fault_cases_failed": result.fault_cases_failed,
            "all_fault_cases_passed": result.all_fault_cases_passed,
            "atlas_nominal_completion_rate": round(result.atlas_nominal_completion_rate, 6),
            "atlas_false_stop_rate": round(result.atlas_false_stop_rate, 6),
        },
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def write_regression_report(
    result: EvaluationResult,
    output_dir: Path,
) -> dict[str, Path]:
    """Write all four regression report files to output_dir.

    Parameters
    ----------
    result:
        EvaluationResult from run_regression_evaluation().
    output_dir:
        Directory to write files into. Created if it does not exist.

    Returns
    -------
    dict[str, Path]
        Keys: "json", "md", "html", "manifest"
        Values: paths to the written files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. JSON
    json_data = _build_json_report(result)
    json_bytes = (json.dumps(json_data, indent=2, sort_keys=True) + "\n").encode("utf-8")
    json_path = output_dir / "regression_report.json"
    json_path.write_bytes(json_bytes)
    json_sha256 = _sha256_bytes(json_bytes)

    # 2. Markdown
    md_text = _build_markdown_report(result)
    md_bytes = md_text.encode("utf-8")
    md_path = output_dir / "regression_report.md"
    md_path.write_bytes(md_bytes)
    md_sha256 = _sha256_bytes(md_bytes)

    # 3. HTML
    html_text = _build_html_report(result)
    html_bytes = html_text.encode("utf-8")
    html_path = output_dir / "regression_report.html"
    html_path.write_bytes(html_bytes)
    html_sha256 = _sha256_bytes(html_bytes)

    # 4. Evidence manifest
    manifest_data = _build_evidence_manifest(
        result, output_dir, json_sha256, md_sha256, html_sha256
    )
    manifest_bytes = (json.dumps(manifest_data, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_path = output_dir / "evidence_manifest.json"
    manifest_path.write_bytes(manifest_bytes)

    return {
        "json": json_path,
        "md": md_path,
        "html": html_path,
        "manifest": manifest_path,
    }
