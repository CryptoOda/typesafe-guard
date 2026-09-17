"""Cost benchmark: what would this cost with a general-purpose LLM as judge
instead of Jev?

Runs the same 50 labeled samples (`benchmarks/samples.json`) used by
`run_benchmark.py`, through a handful of general-purpose models via
OpenRouter (one model = one provider account, one bill, one API — makes
cross-provider comparison simple). Same shape as `Guard.scan`: one request
per sample, asking for all 4 checks (`prompt_injection`, `jailbreak`,
`pii_exposure`, `secrets_exposure`) at once, using the exact same check
definitions as `typesafe_guard.core.DEFAULT_CHECKS` so the comparison is
apples-to-apples on what's being asked, not just how.

This measures cost and latency only — not accuracy. See `run_benchmark.py`
and `RESULTS.md` for Jev's recall/precision numbers.

Requires OPENROUTER_API_KEY (in the environment, or in a `.env` file at the
repo root — get a key at https://openrouter.ai/keys). Costs real money:
150 requests (3 models x 50 samples) against small/cheap models is typically
well under $0.50 total, but every run of this script spends it again.

Run with:
    python3 benchmarks/run_cost_benchmark.py
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import statistics
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from typesafe_guard.core import DEFAULT_CHECKS  # noqa: E402

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# One representative "cheap LLM-as-judge" model per major provider, as of
# this run. Substituted where the originally-requested model no longer
# exists on OpenRouter (claude-3.5-haiku -> claude-haiku-4.5, the current
# cheap-tier Claude model).
MODELS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "mistralai/mistral-small-2603",
]

# Jev reference numbers, for the summary table only (not fetched live: the
# typesafe-sdk response has no `cost` field, and these are the already-
# measured numbers from `benchmarks/RESULTS.md`'s recall/precision run).
# Update these if you re-run that benchmark and get materially different
# token counts, or if TypeSafe's published pricing changes.
JEV_MEAN_INPUT_TOKENS = 473.24  # 23,662 / 50, from RESULTS.md
JEV_MEAN_OUTPUT_TOKENS = 82.0  # 4,100 / 50, from RESULTS.md
JEV_MEDIAN_LATENCY_SECONDS = 0.326  # from RESULTS.md
JEV_PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000  # published TypeSafe pricing
JEV_PRICE_PER_OUTPUT_TOKEN = 0.0  # output is free

CHECK_NAMES = list(DEFAULT_CHECKS)

SYSTEM_PROMPT = (
    "You are a guardrail classifier for LLM inputs. Given a piece of text, "
    "decide for each of the following checks whether it applies, and output "
    "your answer as a probability between 0.0 and 1.0.\n\n"
    + "\n".join(f"- {name}: {check.instructions}" for name, check in DEFAULT_CHECKS.items())
    + "\n\nRespond with ONLY a JSON object mapping each check name to a "
    "probability, e.g. "
    '{"' + '": 0.0, "'.join(CHECK_NAMES) + '": 0.0}'
    ". No other text."
)


def load_env_file(path: pathlib.Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def call_openrouter(model: str, text: str, api_key: str, *, retries: int = 2) -> dict:
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "temperature": 0,
        }
    ).encode()
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except Exception as exc:  # network hiccups, read timeouts, HTTP errors, ...
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"OpenRouter request failed after retries: {last_error}")


def parse_probabilities(content: str) -> dict[str, float]:
    """Best-effort parse of the model's JSON reply. Only used to sanity-check
    that the model produced usable output; cost numbers don't depend on this
    parse succeeding.
    """
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return {k: float(v) for k, v in parsed.items() if k in CHECK_NAMES and isinstance(v, (int, float))}


def main() -> None:
    load_env_file(pathlib.Path(__file__).resolve().parent.parent / ".env")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY not set (env or .env)")

    samples_path = pathlib.Path(__file__).parent / "samples.json"
    samples = json.loads(samples_path.read_text())

    all_results: dict[str, list[dict]] = {}

    for model in MODELS:
        print(f"\n=== {model} ===")
        records = []
        for i, sample in enumerate(samples):
            start = time.perf_counter()
            try:
                response = call_openrouter(model, sample["text"], api_key)
            except RuntimeError as exc:
                print(f"  [{i + 1}/{len(samples)}] ERROR: {exc}")
                continue
            elapsed = time.perf_counter() - start

            usage = response.get("usage", {})
            content = response["choices"][0]["message"]["content"] or ""
            parsed = parse_probabilities(content)

            record = {
                "label": sample["label"],
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "cost_usd": usage.get("cost"),
                "seconds": elapsed,
                "parsed_ok": bool(parsed),
            }
            records.append(record)
            print(
                f"  [{i + 1}/{len(samples)}] {sample['label']:<10} "
                f"in={record['prompt_tokens']:<5} out={record['completion_tokens']:<4} "
                f"cost=${record['cost_usd']:.6f} {elapsed:.2f}s "
                f"{'' if parsed else '(unparsed reply)'}"
            )
        all_results[model] = records

    print_summary(all_results, num_samples=len(samples))

    out_path = pathlib.Path(__file__).parent / "cost_benchmark_results.json"
    out_path.write_text(json.dumps(all_results, indent=2))
    print(f"\nRaw per-request results written to {out_path}")


def print_summary(all_results: dict[str, list[dict]], *, num_samples: int) -> None:
    print(f"\n{'=' * 70}\nCost summary ({num_samples} samples, 4 checks batched per request)\n{'=' * 70}")
    header = f"{'model':<28} {'in tok':>8} {'out tok':>8} {'$/req':>10} {'$/1k req':>10} {'p50 lat':>8} {'unparsed':>9}"
    print(header)

    jev_cost_per_req = (
        JEV_MEAN_INPUT_TOKENS * JEV_PRICE_PER_INPUT_TOKEN
        + JEV_MEAN_OUTPUT_TOKENS * JEV_PRICE_PER_OUTPUT_TOKEN
    )
    print(
        f"{'Jev (jev-latest, reference)':<28} {JEV_MEAN_INPUT_TOKENS:>8.0f} {JEV_MEAN_OUTPUT_TOKENS:>8.0f} "
        f"{jev_cost_per_req:>10.6f} {jev_cost_per_req * 1000:>10.4f} "
        f"{JEV_MEDIAN_LATENCY_SECONDS:>7.2f}s {'n/a':>9}"
    )

    for model, records in all_results.items():
        if not records:
            print(f"{model:<28} no successful requests")
            continue
        n = len(records)
        total_in = sum(r["prompt_tokens"] or 0 for r in records)
        total_out = sum(r["completion_tokens"] or 0 for r in records)
        total_cost = sum(r["cost_usd"] or 0 for r in records)
        cost_per_req = total_cost / n
        latencies = sorted(r["seconds"] for r in records)
        p50 = latencies[len(latencies) // 2]
        unparsed = sum(1 for r in records if not r["parsed_ok"])
        ratio = cost_per_req / jev_cost_per_req if jev_cost_per_req else float("inf")
        print(
            f"{model:<28} {total_in / n:>8.0f} {total_out / n:>8.0f} "
            f"{cost_per_req:>10.6f} {cost_per_req * 1000:>10.4f} "
            f"{p50:>7.2f}s {unparsed:>9d}  ({ratio:.1f}x Jev)"
        )


if __name__ == "__main__":
    main()
