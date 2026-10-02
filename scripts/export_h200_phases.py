#!/usr/bin/env python3
"""Export measured H200 phases without treating process time as proving time."""

import csv
import json
import statistics
from pathlib import Path


REPORTS = Path(__file__).resolve().parents[1] / "data/reports"
SOURCE = REPORTS / "h200-direct-2026-10-02.json"
PER_RUN = REPORTS / "h200-direct-2026-10-02-runs.tsv"
SUMMARY = REPORTS / "h200-direct-2026-10-02-summary.tsv"
COLUMNS = (
    "case_id", "family", "round", "proof_stage_s", "proof_stage_scope",
    "cairo_leaf_proof_sum_s", "ingress_s", "fold_stage_s", "process_s",
    "peak_device_bytes", "qualification",
)


def write_tsv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            rendered = row.copy()
            for column in ("proof_stage_s", "cairo_leaf_proof_sum_s", "ingress_s",
                           "fold_stage_s", "process_s"):
                if rendered[column] != "":
                    rendered[column] = f"{rendered[column]:.9f}"
            rendered["peak_device_bytes"] = str(round(rendered["peak_device_bytes"]))
            writer.writerow(rendered)


def rows_from_report(report: dict) -> list[dict]:
    rows = []
    for round_data in report["rounds"]:
        for case in round_data["cases"]:
            family = case["family"]
            phases = case.get("phase_seconds", {})
            cairo_proof = phases.get("proof_execute_and_decode_ns")
            leaf_phases = case.get("leaf_cairo_phases_seconds", [])
            leaf_sum = sum(leaf["proof_execute_and_decode_ns"] for leaf in leaf_phases)
            # A fold-stage timer includes circuit construction and other host
            # work. Pipeline receipts omit recursion proof durations entirely.
            # Neither can be substituted for a complete proof-only duration.
            rows.append({
                "case_id": case["case_id"],
                "family": family,
                "round": round_data["number"],
                "proof_stage_s": cairo_proof if family == "pie" else "",
                "proof_stage_scope": "cairo_execute_finish" if family == "pie" else "unavailable",
                "cairo_leaf_proof_sum_s": leaf_sum if leaf_phases else "",
                "ingress_s": phases.get("ingress_ns", ""),
                "fold_stage_s": phases.get("fold", ""),
                "process_s": case["time_s"],
                "peak_device_bytes": case["peak_device_bytes"],
                "qualification": case["qualification"],
            })
    return rows


def summarize(rows: list[dict]) -> list[dict]:
    grouped = {}
    for row in rows:
        grouped.setdefault(row["case_id"], []).append(row)
    summary = []
    for case_id, group in grouped.items():
        item = {"case_id": case_id, "family": group[0]["family"],
                "round": "median", "proof_stage_scope": group[0]["proof_stage_scope"],
                "qualification": group[0]["qualification"]}
        for column in ("proof_stage_s", "cairo_leaf_proof_sum_s", "ingress_s",
                       "fold_stage_s", "process_s", "peak_device_bytes"):
            values = [row[column] for row in group if row[column] != ""]
            item[column] = statistics.median(values) if values else ""
        summary.append(item)
    return summary


def main() -> None:
    report = json.loads(SOURCE.read_text())
    rows = rows_from_report(report)
    write_tsv(PER_RUN, rows)
    write_tsv(SUMMARY, summarize(rows))


if __name__ == "__main__":
    main()
