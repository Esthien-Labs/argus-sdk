# Argus SDK

Argus SDK is Esthien's software entry point for profile-bound controller
regression evaluation. It provides a Python API and the `argus` command-line
interface for loading a declared trace, applying a declared fault corpus, and
writing evidence records with explicit boundaries.

## v0.7.4 status

`0.7.4` is the first public release of the Argus SDK. It is published on PyPI as
`esthien-argus-sdk` and on GitHub as release `v0.7.4`. The Python wheel is signed
with Sigstore, and the resolved dependency SBOM is released with it. The released
command-line surface is `runtime-info` and `regression-eval`.

The release validates these host tuples:

| Operating system | Architectures |
|---|---|
| Windows | x64, arm64 |
| macOS | x64, arm64 |
| Linux | x64, arm64 |

Each tuple has a recorded installation, CLI, Python API, and regression-evaluation
result from the release workflow. The Windows installer is distributed unsigned;
Authenticode signing is an open item and requires no change to the Python package.

Host validation in continuous integration is a supported-host record, not a hardware
support claim. No physical board, sensor, or instrument is part of the programme
inventory, and a passing tuple does not establish measured hardware or field
performance.

## Current evidence boundary

- The default evaluation path writes `digital_source_verification` evidence.
- Output source hashes provide integrity traceability. They are not release
  signatures or a safety certification.
- The SDK does not establish hardware timing, thermal, power, functional-safety
  certification, production silicon, or customer-system qualification.
- Measured-evidence classes require a separately controlled measurement record
  and are not asserted by v0.7.4.

## Distribution boundary

The product distribution path exposes a deliberately narrow command surface.
It does not claim source-code secrecy, package encryption, hardware binding,
release signing, security certification, or production key custody. Those
controls require separately approved technical and operational evidence.

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

`runtime-info` reports the detected host, the planned validation matrix, the
Windows x64 installer-candidate scope, and the release-approval boundary.

## Candidate-release build

The internal candidate builder creates a controlled wheel, dependency
inventory, and a machine-readable release manifest. It does not create a
public source archive, sign an artifact, or approve distribution. Native
packages are built and validated per host tuple. Windows candidates use an
application installer; macOS and Linux packages require their own native
package and signing paths before they can be offered.

```powershell
python -m pip install build==1.6.1
python scripts\build_release.py --out C:\temp\argus-sdk-release-candidate
```

Any distribution remains blocked until the required host tuple passes, the
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

## License and contact

This repository is proprietary. Access does not grant a redistribution or
commercial-use license. Contact Esthien Labs for evaluation or licensing
discussion.
