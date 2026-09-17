"""Benchmark: run every sample through Guard.scan and report per-check
precision/recall against the labeled ground truth in samples.json.

This is the thing that actually decides whether typesafe-guard is worth
open-sourcing versus a plausible-looking wrapper. Run with:

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

    # confusion[check_name] = {tp, fp, fn, tn}
    confusion: dict[str, dict[str, int]] = {
        name: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for name in guard._checks
    }
    rows = []

    for sample in samples:
        text, label = sample["text"], sample["label"]
        expected_check = LABEL_TO_CHECK[label]
        result = guard.scan(text)
        row = {"label": label, "text": text[:60]}
        for check_name, check_result in result.results.items():
            row[check_name] = round(check_result.probability, 3)
            is_expected_positive = check_name == expected_check
            triggered = check_result.triggered
            bucket = confusion[check_name]
            if is_expected_positive and triggered:
                bucket["tp"] += 1
            elif is_expected_positive and not triggered:
                bucket["fn"] += 1
            elif not is_expected_positive and triggered:
                bucket["fp"] += 1
            else:
                bucket["tn"] += 1
        rows.append(row)

    print(f"{'label':<10} {'text':<62} " + " ".join(f"{n:<16}" for n in guard._checks))
    for row in rows:
        vals = " ".join(f"{row.get(n, ''):<16}" for n in guard._checks)
        print(f"{row['label']:<10} {row['text']:<62} {vals}")

    print("\nPer-check precision / recall (threshold 0.5):")
    for name, c in confusion.items():
        precision = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else float("nan")
        recall = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else float("nan")
        print(
            f"  {name:<18} tp={c['tp']} fp={c['fp']} fn={c['fn']} tn={c['tn']} "
            f"precision={precision:.2f} recall={recall:.2f}"
        )


if __name__ == "__main__":
    main()
