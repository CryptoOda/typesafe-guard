"""Benchmark: run every sample through Guard.scan and report per-check
recall against ground truth, precision against benign text specifically,
and injection/jailbreak co-occurrence as a separate descriptive stat.

Why not one confusion matrix across all four checks: injection and jailbreak
are not mutually exclusive in the underlying phenomenon (a persona-override
attempt like "you are now DAN" is legitimately both an instruction override
AND a content-policy bypass). Scoring cross-category co-occurrence as a
"false positive" would penalize the model for being semantically correct.
The metric that actually matters for a guardrail is: does it fire on real
attacks (recall) and stay quiet on benign text (precision vs. benign)?
Whether attack categories overlap with each other is a separate, descriptive
question — see the co-occurrence section below and benchmarks/RESULTS.md.

Run with:
    python3 benchmarks/run_benchmark.py
"""
from __future__ import annotations

import json
import pathlib
import sys

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

    for sample in samples:
        text, label = sample["text"], sample["label"]
        expected_check = LABEL_TO_CHECK[label]
        result = guard.scan(text)
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


if __name__ == "__main__":
    main()
