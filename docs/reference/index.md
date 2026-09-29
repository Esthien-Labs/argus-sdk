# Argus SDK Documentation

Version 0.7.4. Argus SDK is Esthien's software entry point for profile-bound controller
regression evaluation. It provides a Python API and the `argus` command-line interface for
loading a declared trace, applying a declared fault corpus, and writing evidence records
with explicit boundaries.

## Reference

- [Python API Reference](API_REFERENCE.md)
- [CLI Reference](CLI_REFERENCE.md)
- [C ABI Reference](C_ABI_REFERENCE.md)
- [Examples](examples/README.md)

## Evidence boundary

The SDK records `digital_source_verification` evidence by default. It does not assert
physical hardware, silicon, power, thermal, or safety-certification results. Any public
performance, accuracy, or timing figure must carry its measurement boundary.
