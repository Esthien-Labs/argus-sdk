# Argus SDK Examples

Runnable examples of the safety-envelope API in each supported language.

| Language | File | Wrapper |
|---|---|---|
| Python | `python/envelope_basic.py` | `argus` package (this release) |
| Node.js | `nodejs/envelope_basic.js` | `@esthien/argus` |
| Rust | `rust/envelope_basic.rs` | `argus` crate |
| Go | `go/envelope_basic.go` | `github.com/esthien/argus-go` |
| Java | `java/EnvelopeBasic.java` | `com.esthien:argus-sdk` |
| C# | `csharp/EnvelopeBasic.cs` | `Esthien.Argus` |
| C | `c/envelope_basic.c` | `argus.h` C ABI |

Each example builds a default safety configuration, evaluates one window with a
high-confidence `knee_flexion` prediction and good signal quality, and prints the
resulting state and command.

The Python example runs against the installed `argus` package. The other examples
require the corresponding wrapper to be built and its native library present. Native
library builds are a v0.8.0 deliverable; the wrapper sources ship with this release.

All examples produce `digital_source_verification` results. They do not demonstrate
hardware, silicon, or field behaviour.
