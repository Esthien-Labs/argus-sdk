# Argus SDK CLI Reference

Version: 0.7.4
Status: Public release.
Note: The `argus` command exposes a deliberately narrow, controlled surface.

---

## 1. Invocation

```text
argus [--version] <command> [options]
```

| Option | Description |
|---|---|
| `--version` | Print the SDK version and exit |

The released command surface is two commands:

| Command | Purpose |
|---|---|
| `runtime-info` | Show package and detected-host facts as JSON |
| `regression-eval` | Run the supported software evaluation workflow |

Commands outside this surface are development tooling and are not part of the release.

## 2. `runtime-info`

Prints machine-readable release-contract facts for the active host.

```text
argus runtime-info
```

Output is a JSON object. Fields include `sdk_version`, `release_status`, `interfaces`,
`detected_host`, `planned_host_targets`, `installer_candidate_targets`, and an
`evidence_boundary` note.

Exit code `0` on success.

## 3. `regression-eval`

Runs a controller regression evaluation against a declared profile and inputs, and writes
evidence records with explicit boundaries.

```text
argus regression-eval (--sample | --trace <path>) [--profile <path>] [--out <dir>]
```

| Option | Required | Description |
|---|---|---|
| `--sample` | one of `--sample` / `--trace` | Use the packaged synthetic example trace |
| `--trace <path>` | one of `--sample` / `--trace` | Path to a declared JSON, ROS 2, or MCAP trace |
| `--profile <path>` | no | Evaluation profile; defaults to the packaged profile |
| `--out <dir>` | no | Output directory; default `out/regression-eval` |

With `--sample`, the command writes a generated trace at
`<out>/sample_trace.argus-trace.json` and evaluates it. The evaluation records evidence
under the class `digital_source_verification`.

The command prints a status line, the profile id, the pass count for fault cases, and the
written output paths. Exit code is `0` when all fault cases pass and `1` otherwise.

### Example

```text
argus regression-eval --sample --out out/regression-eval
```

## 4. Exit codes

| Code | Meaning |
|---|---|
| 0 | Success; for `regression-eval`, all fault cases passed |
| 1 | `regression-eval` ran and at least one fault case failed |
| 2 | Argument or input error (for example, a missing trace) |

## 5. Evidence boundary

`regression-eval` produces `digital_source_verification` evidence. It does not assert
hardware timing, power, thermal, or field performance. The sample workflow uses generated
inputs, not customer or field data.
