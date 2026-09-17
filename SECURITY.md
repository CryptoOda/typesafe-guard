# Security Policy

typesafe-guard is a guardrail library — please report suspected
vulnerabilities (e.g. a bypass that lets known attack patterns evade
detection, or an issue in the ASGI middleware that could leak request bodies
or skip enforcement) privately rather than as a public issue.

## Reporting

Email crypto.oda@gmail.com with:

- A description of the issue and its impact.
- Steps or a sample input to reproduce it.
- Affected version (`typesafe_guard.__version__`).

Please do not open a public GitHub issue for suspected vulnerabilities until
a fix is available.

## Scope note

This library only classifies text and returns a probability plus a code-owned
`allow`/`warn`/`block` decision — it does not redact, rewrite, sandbox, or
execute anything. A missed detection (false negative) is a security-relevant
bug; report it the same way as above.
