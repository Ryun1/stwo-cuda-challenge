#!/usr/bin/env python3
"""Describe historical and public PIE sizes without mixing input formats or clocks."""

import csv
import hashlib
import json
from pathlib import Path
import statistics
import struct


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "data/reports"
COLUMNS = (
    "cohort", "pie", "os_steps", "blocks", "steps_per_block", "step_index_vs_historical_median",
    "source_archive_bytes", "adapted_cpi_bytes", "component_count", "padded_component_rows",
    "executed_ec_op", "executed_pedersen", "executed_poseidon", "executed_bitwise",
    "executed_range_check", "reserved_ec_op", "reserved_pedersen", "reserved_poseidon",
    "reserved_bitwise", "reserved_range_check", "reserved_range_check96",
    "reserved_add_mod", "reserved_mul_mod",
    "opcode_state_count", "memory_address_count", "large_felt_count", "small_felt_count",
    "blake_opcode_count", "complexity_signal", "source",
)
BUILTINS = (
    ("add_mod_builtin", 7), ("bitwise_builtin", 5), ("output", 1),
    ("mul_mod_builtin", 7), ("pedersen_builtin", 3), ("poseidon_builtin", 6),
    ("range_check96_builtin", 1), ("range_check_builtin", 1), ("ec_op_builtin", 7),
)


def inspect_cpi(path: Path, expected_bytes: int, expected_sha256: str) -> dict:
    """Read the pinned CPI transport's counts; skip bulky state and memory arrays."""
    if path.stat().st_size != expected_bytes:
        raise ValueError(f"CPI size differs from fixture: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise ValueError(f"CPI hash differs from fixture: {path}")

    with path.open("rb") as source:
        def read(fmt: str):
            size = struct.calcsize(fmt)
            raw = source.read(size)
            if len(raw) != size:
                raise ValueError(f"truncated CPI: {path}")
            return struct.unpack(fmt, raw)

        def skip(size: int) -> None:
            if size < 0 or source.tell() + size > expected_bytes:
                raise ValueError(f"invalid CPI count: {path}")
            source.seek(size, 1)

        if source.read(8) != b"STWZCPI\0" or read("<II") != (1, 0):
            raise ValueError(f"unexpected CPI header: {path}")
        skip(24)  # Initial and final Cairo machine state.
        (pc_count,) = read("<Q")
        public_mask, reserved16, reserved32, opcode_count, reserved_opcode = read("<HHIII")
        if (public_mask >> 11 or reserved16 or reserved32 or reserved_opcode or
                opcode_count != 20):
            raise ValueError(f"unexpected CPI geometry header: {path}")
        opcode_counts = []
        for _ in range(opcode_count):
            (count,) = read("<Q")
            opcode_counts.append(count)
            skip(count * 12)
        skip(16)  # Small-value cutoff.
        log_small_capacity, reserved = read("<II")
        if reserved or log_small_capacity > 32 or pc_count > expected_bytes:
            raise ValueError(f"unexpected CPI memory header: {path}")
        address_count, large_count, small_count = read("<QQQ")
        skip(address_count * 4 + large_count * 32 + small_count * 16)
        (public_count,) = read("<Q")
        skip(public_count * 4)
        builtins = {}
        for name, stride in BUILTINS:
            present, padding, begin, end = read("<B7sQQ")
            if (padding != bytes(7) or present not in (0, 1) or end < begin or
                    (present == 0 and (begin != 0 or end != 0))):
                raise ValueError(f"invalid CPI builtin segment: {path}")
            length = end - begin if present else 0
            if length % stride:
                raise ValueError(f"misaligned CPI builtin segment: {path}")
            builtins[name] = length // stride
    return {
        "reserved_ec_op": builtins["ec_op_builtin"],
        "reserved_pedersen": builtins["pedersen_builtin"],
        "reserved_poseidon": builtins["poseidon_builtin"],
        "reserved_bitwise": builtins["bitwise_builtin"],
        "reserved_range_check": builtins["range_check_builtin"],
        "reserved_range_check96": builtins["range_check96_builtin"],
        "reserved_add_mod": builtins["add_mod_builtin"],
        "reserved_mul_mod": builtins["mul_mod_builtin"],
        "executed_ec_op": "", "executed_pedersen": "", "executed_poseidon": "",
        "executed_bitwise": "", "executed_range_check": "",
        "opcode_state_count": sum(opcode_counts),
        "memory_address_count": address_count,
        "large_felt_count": large_count,
        "small_felt_count": small_count,
        "blake_opcode_count": opcode_counts[18],
    }


def main() -> None:
    with (REPORTS / "historical-cairo-cuda-milestones.tsv").open(newline="") as source:
        historical = [row for row in csv.DictReader(source, delimiter="\t")
                      if row["revision"] == "v39"]
    if len(historical) != 4 or len({row["benchmark"] for row in historical}) != 4:
        raise ValueError("expected four distinct historical PIEs")
    median_steps = statistics.median(int(row["os_steps"]) for row in historical)
    rows = []
    for item in historical:
        rows.append({
            "cohort": "historical_sn_pie", "pie": item["benchmark"],
            "os_steps": item["os_steps"], "blocks": "", "steps_per_block": "",
            "step_index_vs_historical_median": f"{int(item['os_steps']) / median_steps:.3f}",
            "source_archive_bytes": item["source_archive_bytes"], "adapted_cpi_bytes": "",
            "component_count": item["component_count"],
            "padded_component_rows": item["padded_component_rows"],
            "executed_ec_op": item["ec_op_instances"],
            "executed_pedersen": item["pedersen_instances"],
            "executed_poseidon": item["poseidon_instances"],
            "executed_bitwise": item["bitwise_instances"],
            "executed_range_check": item["range_check_instances"],
            "reserved_ec_op": "", "reserved_pedersen": "", "reserved_poseidon": "",
            "reserved_bitwise": "", "reserved_range_check": "", "reserved_range_check96": "",
            "reserved_add_mod": "", "reserved_mul_mod": "",
            "opcode_state_count": "", "memory_address_count": "",
            "large_felt_count": "", "small_felt_count": "",
            "blake_opcode_count": "",
            "complexity_signal": "measured_builtin_census",
            "source": "stwo-zig/vectors/cairo/source_semantics/four_pie_coverage_v1.json",
        })
    fixture = json.loads((ROOT / "fixtures/public-v1.json").read_text())
    public = [case for case in fixture["cases"] if case["family"] == "pie"]
    if len(public) != 6:
        raise ValueError("expected six public PIEs")
    for case in public:
        blocks = case["blocks"][1] - case["blocks"][0] + 1
        steps = case["os_steps"]
        input_meta = case["input"]
        cpi = inspect_cpi(ROOT / "data/inputs" / input_meta["path"],
                          input_meta["bytes"], input_meta["sha256"])
        rows.append({
            "cohort": "public_h200_v1", "pie": case["id"],
            "os_steps": steps, "blocks": blocks,
            "steps_per_block": f"{steps / blocks:.1f}",
            "step_index_vs_historical_median": f"{steps / median_steps:.3f}",
            "source_archive_bytes": "", "adapted_cpi_bytes": input_meta["bytes"],
            "component_count": "", "padded_component_rows": "",
            **cpi,
            "complexity_signal": case["description"],
            "source": "fixtures/public-v1.json",
        })
    with (REPORTS / "pie-workload-shapes.tsv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
