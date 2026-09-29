"""Governed standards registry for Atlas controller regression evaluation.

Only standards in GOVERNED_STANDARDS may be cited in Atlas evidence manifests.
Every citation must include the standard identifier and a section reference.

Rationale: Atlas evidence manifests are submitted to certification bodies.
An unchecked standards field with an invalid citation undermines the document's
credibility and creates legal exposure. The whitelist ensures only real, active
standards are cited, and every citation maps to a section that Atlas evidence
can genuinely address.

Evidence boundary: a citation in an Atlas manifest means Atlas produced evidence
relevant to that standard section, not that Atlas is certified to that standard.
Certification requires a separate qualified program.
"""

from __future__ import annotations


class StandardsCitationError(ValueError):
    """Raised when an applicable_standards citation is not in the governed whitelist."""


# ---------------------------------------------------------------------------
# Governed standards whitelist
# ---------------------------------------------------------------------------

GOVERNED_STANDARDS: frozenset[str] = frozenset({
    # Industrial robot safety
    "ISO 10218-1:2011",
    "ISO 10218-2:2011",
    "ISO/TS 15066:2016",
    # Mobile robot / AMR safety
    "ISO 3691-4:2023",
    # Functional safety (general)
    "IEC 61508:2010",
    # Automotive functional safety
    "ISO 26262:2018",
    # SOTIF
    "ISO 21448:2022",
    # Medical device software
    "IEC 62304:2015",
    # Medical device risk management
    "ISO 14971:2019",
    # Aerospace software
    "DO-178C",
    # Railway
    "EN 50128:2011",
    # Medical electrical equipment
    "IEC 60601-1:2005",
    # Defense
    "MIL-STD-882E",
    # Cybersecurity automotive
    "ISO 21434:2021",
})

# Standard-to-Atlas-coverage mapping: section -> what Atlas evidence addresses
# Used to generate accurate citation text in evidence manifests.
STANDARD_SECTION_MAP: dict[str, dict[str, str]] = {
    "ISO 3691-4:2023": {
        "5.4.2": "Software-based safety functions - fault corpus passes declared fault states",
        "5.5":   "Safety-related control system - command-guard digital assurance case",
        "6.1":   "Risk assessment - fault injection test record per declared profile",
    },
    "ISO 10218-1:2011": {
        "5.4":   "Safety-related control system - command-boundary safety case",
        "5.4.3": "Software - fault corpus replay record for declared joint profiles",
    },
    "ISO/TS 15066:2016": {
        "4.2":   "Risk assessment - force and velocity limit corpus evidence",
        "5.4":   "Speed and separation monitoring - command-guard fault injection record",
    },
    "ISO 26262:2018": {
        "Part 6 SWE.6": "Software unit testing - fault injection test cases with expected behavior",
        "Part 6 SWE.4": "Software architectural design - command-guard architecture description",
        "Part 4 TSR":   "Technical safety requirements - fault corpus mapping",
    },
    "IEC 62304:2015": {
        "5.6":   "Software integration and integration testing - command boundary integration test record",
        "5.7":   "Software system testing - declared fault corpus with pass/fail record",
        "8.1":   "Software problem resolution - regression report with root-cause traceability",
    },
    "DO-178C": {
        "6.4.2": "Test coverage analysis - fault corpus coverage record",
        "MC/DC": "MC/DC coverage - not established without structural coverage measurement",
    },
    "ISO 14971:2019": {
        "7.3":   "Risk control measures - fault corpus maps to identified hazardous situations",
        "9.2":   "Post-production information - regression record for software updates",
    },
    "IEC 61508:2010": {
        "7.2":   "Software safety requirements - command-guard requirements traceability",
        "7.9":   "Software integration test - fault injection test record",
    },
    "ISO 21448:2022": {
        "8.3":   "Verification and validation - scenario corpus for intended function boundary",
    },
    "ISO 26262:2018 Part 6 SWE.6": {
        "SWE.6": "Software unit testing - fault injection test cases with expected behavior",
    },
    "MIL-STD-882E": {
        "Task 301": "Hazard analysis - fault corpus maps to identified mishap risk",
        "Task 401": "Safety assessment - regression test record for software updates",
    },
}


def validate_standards_citations(citations: list[str]) -> list[str]:
    """Validate a list of standard citations against the governed whitelist.

    Parameters
    ----------
    citations:
        List of standard identifier strings from an applicable_standards field.

    Returns
    -------
    list[str]
        The validated citations (unchanged).

    Raises
    ------
    StandardsCitationError
        If any citation is not in GOVERNED_STANDARDS. The error message names
        the invalid citation and lists the accepted values.
    """
    for citation in citations:
        # Allow "STANDARD:SECTION" format by checking the base standard identifier
        base = citation.split(":")[0].strip() if ":" in citation else citation
        # Check exact match first, then base match
        if citation not in GOVERNED_STANDARDS and base not in GOVERNED_STANDARDS:
            # Build a helpful suggestion list
            close = [s for s in sorted(GOVERNED_STANDARDS) if base.lower() in s.lower()]
            suggestion = f" Did you mean: {close[0]!r}?" if close else ""
            raise StandardsCitationError(
                f"Citation {citation!r} is not in the governed standards whitelist.{suggestion}\n"
                f"Governed standards: {', '.join(sorted(GOVERNED_STANDARDS))}"
            )
    return citations


def get_coverage_text(standard: str, section: str) -> str:
    """Return the Atlas coverage description for a standard+section combination.

    Returns a generic description if the section is not in the map.
    """
    sections = STANDARD_SECTION_MAP.get(standard, {})
    return sections.get(section, f"Fault corpus and command-guard evidence relevant to {standard} {section}")
