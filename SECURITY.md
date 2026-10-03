# Security policy

## Supported version

Security fixes are applied to the current `main` branch. Older commits and
frozen research artifacts are preserved for reproducibility and should not be
assumed to receive backported fixes.

## Reporting a vulnerability

Please avoid publishing an exploitable security issue, credential, private
submission artifact, or sensitive infrastructure detail in a public issue.

Use GitHub's private vulnerability-reporting / Security Advisory interface for
this repository when it is available. If private reporting is not available,
contact the maintainer through the repository owner's GitHub profile before
posting technical details publicly.

Useful reports include:

- the affected commit and command;
- the smallest reproducible input;
- expected versus observed behavior;
- whether the issue can cause unintended writes, path traversal, arbitrary
  code execution, credential exposure, or incorrect trust/provenance results.

This project is designed to be read-only against remote Vesuvius data. Any path
that causes remote writes, executes data as code, or silently weakens a
fail-closed integrity check should be treated as security-relevant.

## Scope

Data-quality disagreements that cannot affect code execution, confidentiality,
or provenance integrity are normally ordinary bugs rather than security
vulnerabilities. False-clean results caused by malformed or adversarial input
may still be security-relevant when downstream automation relies on the gate.
