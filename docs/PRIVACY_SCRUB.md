# Privacy Scrub

[README](../README.md)

Use `scripts/privacy_scrub.py` before committing logs, receipts, command output,
or generated docs. It catches high-confidence secrets, private host/network
fingerprints, local user names, and absolute home/repo paths.

Findings report path, line, column, and rule name. They do not print the matched
value, so hook output is safer to paste into issue threads or review notes.

Run it on staged files:

```sh
scripts/privacy_scrub.py --staged
```

Install the tracked pre-commit hook locally:

```sh
git config core.hooksPath .githooks
```

Audit the whole tracked tree:

```sh
scripts/privacy_scrub.py --all
```

Redact a file or the tracked tree deliberately:

```sh
scripts/privacy_scrub.py --redact path/to/file
scripts/privacy_scrub.py --all --redact
```

Use `privacy-scrub: allow` on a line only for intentional examples that are not
real identifiers or secrets. Do not allowlist real credentials.
