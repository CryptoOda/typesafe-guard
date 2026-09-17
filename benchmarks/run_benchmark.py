"""Benchmark: run every sample through Guard.scan and report per-check
recall against ground truth, precision against benign text specifically,
injection/jailbreak co-occurrence as a separate descriptive stat, and
request-level throughput (tokens/sec, latency).

Why not one confusion matrix across all four checks: injection and jailbreak
are not mutually exclusive in the underlying phenomenon (a persona-override
attempt like "you are now DAN" is legitimately both an instruction override
AND a content-policy bypass). Scoring cross-category co-occurrence as a
"false positive" would penalize the model for being semantically correct.
The metric that actually matters for a guardrail is: does it fire on real
attacks (recall) and stay quiet on benign text (precision vs. benign)?
Whether attack categories overlap with each other is a separate, descriptive
question — see the co-occurrence section below and benchmarks/RESULTS.md.

Throughput is measured at the request level (one scan = one batched request
covering all 4 checks at once), since that's the actual unit of latency and
billing — there's no separate network round-trip per check.

Run with:
    python3 benchmarks/run_benchmark.py
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from typesafe_guard import Guard  # noqa: E402

LABEL_TO_CHECK = {
    "injection": "prompt_injection",
    "jailbreak": "jailbreak",
    "pii": "pii_exposure",
    "secret": "secrets_exposure",
    "benign": None,
}


def main() -> None:
    samples_path = pathlib.Path(__file__).parent / "samples.json"
    samples = json.loads(samples_path.read_text())

    guard = Guard()
    check_names = list(guard._checks)

    # Per check: recall against its own labeled positives; precision counted
    # only against benign samples (attack-vs-attack overlap is reported
    # separately, not folded in as a false positive).
    stats: dict[str, dict[str, int]] = {
        name: {"tp": 0, "fn": 0, "fp_on_benign": 0, "tn_on_benign": 0} for name in check_names
    }
    rows = []
    timings = []  # one entry per scan(): wall-clock seconds, input/output tokens

    for sample in samples:
        text, label = sample["text"], sample["label"]
        expected_check = LABEL_TO_CHECK[label]

        start = time.perf_counter()
        result = guard.scan(text)
        elapsed = time.perf_counter() - start
        timings.append(
            {
                "seconds": elapsed,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            }
        )

        row = {"label": label, "text": text[:60]}
        for check_name in check_names:
            triggered = result.get(check_name).triggered
            row[check_name] = round(result.get(check_name).probability, 3)
            bucket = stats[check_name]
            if check_name == expected_check:
                bucket["tp" if triggered else "fn"] += 1
            elif label == "benign":
                bucket["fp_on_benign" if triggered else "tn_on_benign"] += 1
            # else: sample belongs to a different attack category — not
            # counted here, see co-occurrence section below.
        rows.append(row)

    print(f"{'label':<10} {'text':<62} " + " ".join(f"{n:<16}" for n in check_names))
    for row in rows:
        vals = " ".join(f"{row.get(n, ''):<16}" for n in check_names)
        print(f"{row['label']:<10} {row['text']:<62} {vals}")

    print("\nRecall (own labeled positives) / precision vs. benign only (threshold 0.5):")
    for name, s in stats.items():
        recall = s["tp"] / (s["tp"] + s["fn"]) if (s["tp"] + s["fn"]) else float("nan")
        precision = (
            s["tp"] / (s["tp"] + s["fp_on_benign"]) if (s["tp"] + s["fp_on_benign"]) else float("nan")
        )
        print(
            f"  {name:<18} tp={s['tp']} fn={s['fn']} fp_on_benign={s['fp_on_benign']} "
            f"tn_on_benign={s['tn_on_benign']} recall={recall:.2f} precision_vs_benign={precision:.2f}"
        )

    print(
        "\nInjection/jailbreak co-occurrence (descriptive, not a false-positive count —\n"
        "see benchmarks/RESULTS.md for why these two checks legitimately overlap):"
    )
    for label, other_check in (("injection", "jailbreak"), ("jailbreak", "prompt_injection")):
        label_rows = [r for r in rows if r["label"] == label]
        if not label_rows:
            continue
        fired = sum(1 for r in label_rows if r.get(other_check, 0) >= 0.5)
        print(f"  {label} samples also triggering {other_check}: {fired}/{len(label_rows)}")

    print_throughput(timings, num_checks=len(check_names))


def print_throughput(timings: list[dict], *, num_checks: int) -> None:
    """Report latency and tokens/sec for the batched scan() requests.

    Each scan() is one request covering `num_checks` Noul questions at once
    — this is what a real caller pays in latency and tokens, not a per-check
    number (there's no way to isolate one question's cost within a batch).
    """
    total_calls = len(timings)
    total_seconds = sum(t["seconds"] for t in timings)
    total_output_tokens = sum(t["output_tokens"] or 0 for t in timings)
    total_input_tokens = sum(t["input_tokens"] or 0 for t in timings)

    latencies = [t["seconds"] for t in timings]
    per_call_tps = [
        (t["output_tokens"] / t["seconds"])
        for t in timings
        if t["output_tokens"] and t["seconds"] > 0
    ]

    print(f"\nThroughput ({total_calls} batched requests, {num_checks} checks per request):")
    print(f"  total wall time:      {total_seconds:.2f}s")
    print(f"  mean latency/request: {statistics.mean(latencies):.3f}s")
    print(f"  median latency:       {statistics.median(latencies):.3f}s")
    print(f"  p95 latency:          {sorted(latencies)[int(len(latencies) * 0.95)]:.3f}s")
    print(f"  total input tokens:   {total_input_tokens}")
    print(f"  total output tokens:  {total_output_tokens}")
    print(f"  aggregate output tok/s (sum tokens / sum seconds): {total_output_tokens / total_seconds:.1f}")
    if per_call_tps:
        print(f"  mean per-request output tok/s:   {statistics.mean(per_call_tps):.1f}")
        print(f"  median per-request output tok/s: {statistics.median(per_call_tps):.1f}")
    print(
        f"  mean output tokens/request (all {num_checks} checks batched): "
        f"{total_output_tokens / total_calls:.1f}"
    )


if __name__ == "__main__":
    main()
