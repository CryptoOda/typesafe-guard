# Changelog

## 0.1.0

Initial release.

- `Guard.scan()`: batches `prompt_injection`, `jailbreak`, `pii_exposure`,
  `secrets_exposure` checks (or a custom `checks=` mapping) into one
  TypeSafe request.
- `decide()`: code-owned `allow`/`warn`/`block` mapping over scan results.
- `typesafe_guard.asgi.GuardrailMiddleware`: framework-agnostic ASGI
  middleware that scans a request body field and blocks or annotates
  `scope["typesafe_guard"]`.
- Benchmark suite (`benchmarks/`) against 50 labeled samples.
