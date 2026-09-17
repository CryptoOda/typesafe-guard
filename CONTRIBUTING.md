# Contributing

## Setup

```bash
git clone https://github.com/crypto-oda/typesafe-guard.git
cd typesafe-guard
uv pip install -e ".[test]"
```

(Any `pip install -e ".[test]"` inside a venv works too — `uv` is just what
this repo was developed with.)

## Running tests

```bash
pytest
```

Unit tests mock `TypeSafeClient`, so no API key or network access is needed.

## Running the benchmark

```bash
cp .env.example .env   # then fill in TYPESAFE_API_KEY
export $(cat .env | xargs)
python3 benchmarks/run_benchmark.py
```

This hits the live TypeSafe API and costs real requests — get a key at
https://console.typesafe.ai/settings/keys. See `benchmarks/RESULTS.md` for
the design history behind the current check wording before proposing changes
to `DEFAULT_CHECKS` in `typesafe_guard/core.py` — several rewrites were tried
and rejected for lowering recall or precision; changes there should come with
a benchmark re-run showing the effect.

## Running the cost benchmark

```bash
cp .env.example .env   # then fill in OPENROUTER_API_KEY
python3 benchmarks/run_cost_benchmark.py
```

Compares Jev's cost/latency against a few general-purpose LLMs as judge, via
OpenRouter (get a key at https://openrouter.ai/keys). Costs real money on
your OpenRouter account (well under $0.50 for a full run). If you change the
model list in `benchmarks/run_cost_benchmark.py`, update the tables in
`README.md` and `benchmarks/RESULTS.md` to match.

## Pull requests

- Keep changes focused; unrelated cleanup belongs in its own PR.
- Add or update tests for behavior changes in `typesafe_guard/core.py` or
  `typesafe_guard/asgi.py`.
- If you change `DEFAULT_CHECKS` wording or thresholds, re-run the benchmark
  and update `benchmarks/RESULTS.md` and the README's summary table.
