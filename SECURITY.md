# Security policy

## Reporting a vulnerability

Please report vulnerabilities in this runner through [GitHub private vulnerability reporting](https://github.com/vu2lid/local-llm-review-runner/security/advisories/new) for `vu2lid/local-llm-review-runner`.

Use a private report for issues that could leak candidate text, weaken output validation, run a shell, or reach the network during `run` or `doctor`. Include the version or commit, a short description, and a way to reproduce it.

Do not include real exam banks, credentials, access tokens, model weights, or unredacted local paths in a public issue. A public issue is fine for a crash that does not expose candidate text.

This policy covers `local-llm-review-runner`. BitNet, llama.cpp, and `us-hamexam` have their own maintainers.

## Design notes

How the runner treats untrusted candidate text, prompt injection, subprocess argv, and output validation is documented in [docs/SECURITY.md](docs/SECURITY.md). That document is the design, not the reporting channel.
