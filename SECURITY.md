# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | :white_check_mark: |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Use GitHub's private vulnerability reporting:
<https://github.com/BingDouhua612/df2ulog/security/advisories/new>

or send a private message to [@BingDouhua612](https://github.com/BingDouhua612).

Please include:

- the version/commit and platform;
- a minimal reproducer (synthetic data preferred; **never attach real flight
  logs or personal data**);
- the impact you believe the issue has.

You can expect an initial response within 7 days. Once the issue is confirmed,
a fix and advisory will be prepared; credit will be given unless you prefer to
stay anonymous.

## Scope

The converter parses untrusted binary/text logs. Reports about crashes,
excessive memory use, path traversal, or unsafe output handling are in scope.
The GUI is Windows-oriented but the CLI should be cross-platform.
