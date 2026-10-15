# Argus SDK

Argus SDK is Esthien's developer toolkit for the Argus decision boundary. The
released version, 0.7.4, provides profile-bound controller regression
evaluation: a Python API and the `argus` command-line interface for loading a
declared trace, applying a declared fault corpus, and writing evidence records
with explicit boundaries.

This branch is the development line for 0.8. It adds typed proposals, a
capability system, a sensor health gate, an evidence chain, and a containment
benchmark. None of that is part of a release yet.

## Releases

| Version | Status | Where |
|---|---|---|
| 0.7.4 | Current release | PyPI, package `esthien-argus-sdk` |

The command surface of 0.7.4 is `runtime-info` and `regression-eval`.

0.7.4 was built and validated on these host tuples by the release workflow:

| Operating system | Architectures |
|---|---|
| Windows | x64, arm64 |
| macOS | x64, arm64 |
| Linux | x64, arm64 |

Each tuple has a recorded installation, CLI, Python API, and regression-evaluation
result. Host validation in continuous integration is a supported-host record, not a
hardware support claim. No physical board, sensor, or instrument is part of the
programme inventory, and a passing tuple does not establish measured hardware or
field performance.

The 0.7.4 package on PyPI is not accompanied by a published signature bundle, and
this repository has no GitHub release for it. Release files that carry Sigstore
bundles, with a verification command for each file, are planned for the next patch
release. The Windows installer is distributed unsigned; Authenticode signing is an
open item and requires no change to the Python package.

## Current evidence boundary

- The default evaluation path writes `digital_source_verification` evidence.
- Output source hashes provide integrity traceability. They are not release
  signatures or a safety certification.
- The SDK does not establish hardware timing, thermal, power, functional-safety
  certification, production silicon, or customer-system qualification.
- Measured-evidence classes require a separately controlled measurement record
  and are not asserted by any release.

## Distribution boundary

The product distribution path exposes a deliberately narrow command surface.
It does not claim source-code secrecy, package encryption, hardware binding,
security certification, or production key custody. Those controls require
separately approved technical and operational evidence. Release signing is
described under Releases.

## Local development

Requirements:

- Python 3.11 or later
- A supported Python environment with NumPy, SciPy, and scikit-learn

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install ".[dev]"
argus --version
argus runtime-info
argus regression-eval --sample --out out\smoke
```

The default regression profile is packaged with the SDK, so the sample command
works without relying on a source-tree-relative configuration path.

## Python API

```python
from argus import ConfidenceCoupledSafetyEnvelope, ProfileCompiler

compiler = ProfileCompiler()
envelope = ConfidenceCoupledSafetyEnvelope()
```

The public Python imports are versioned with the package. Product packages do
not expose internal research, hardware-design, or roadmap material.

## CLI

```text
argus --version
argus runtime-info
argus regression-eval --sample --out <directory>
argus --help
```

`runtime-info` reports the detected host, the validation matrix, and the evidence
boundary of the installed release.

## Candidate-release build

The candidate builder creates a controlled wheel, dependency inventory, and a
machine-readable release manifest. It does not create a public source archive,
sign an artifact, or approve distribution. Native packages are built and validated
per host tuple.

```powershell
python -m pip install build==1.6.1
python scripts\build_release.py --out C:\temp\argus-sdk-release-candidate
```

Any distribution remains blocked until the required host tuples pass, the
dependency inventory receives security review, the artifact is signed with an
approved release key, and a release-approval record is complete.

## Repository layout

```text
src/argus/                 Python API and CLI
src/argus/resources/       Packaged reference profiles
tests/                     Unit, integration, conformance, and formal checks
config/                    Source configuration and research inputs
scripts/build_release.py   Controlled candidate artifact builder
packaging/windows/         Windows installer source and command wrapper
.github/workflows/         Host verification and candidate-build workflows
```

## Development line for 0.8

| Component | Description |
|---|---|
| Proposal protocol | Typed ProposedAction schema, canonical binary encoding, provenance chain |
| Authority capabilities | Scoped, expiring, single-use capability tokens checked at the boundary |
| Attestation protocol | Merkle-chained evidence records with signed batch roots |
| Sensor health gate | Declared sensor health and out-of-distribution checks |
| Wedge benchmark | Declared fault corpus with a reproducible containment measurement |

A policy language and a ROS 2 node are planned for the same line. Components in this
table are under development. Each one becomes a release claim only when it has a
recorded evidence class and a release that contains it.

## License and contact

This repository is proprietary. Access does not grant a redistribution or
commercial-use license. Contact Esthien Labs for evaluation or licensing
discussion.
