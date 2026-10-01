#!/usr/bin/env python3
"""Run one H200 arm against hash-pinned fixtures and emit judge measurements."""

import argparse
from collections.abc import Mapping
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ENV = frozenset({
    "PATH", "LD_LIBRARY_PATH", "LANG", "LC_ALL", "TZ",
    "CUDA_VISIBLE_DEVICES", "CUDA_MODULE_LOADING", "CUDA_CACHE_DISABLE",
    "CUDA_CACHE_MAXSIZE", "CUDA_DEVICE_MAX_CONNECTIONS",
    "NVIDIA_VISIBLE_DEVICES", "NVIDIA_DRIVER_CAPABILITIES",
})


def candidate_env(host: Mapping[str, str], preprocessed: Path,
                  artifact_dir: Path) -> dict[str, str]:
    """Keep service credentials out of the submitted prover's environment."""
    env = {key: value for key, value in host.items() if key in RUNTIME_ENV}
    env.update(STWO_CAIRO_CUDA_PREPROCESSED_COEFFICIENTS=str(preprocessed.resolve()),
               STWO_CAIRO_CUDA_ARTIFACT_DIR=str(artifact_dir.resolve()),
               STWO_CAIRO_CUDA_PREPROCESSED_VARIANT="canonical")
    return env


class Memory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong),
                ("used", ctypes.c_ulonglong)]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_file(root: Path, item: dict, key: str = "path") -> Path:
    relative = Path(item[key])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe fixture path: {relative}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"fixture missing: {relative}")
    if sha(path) != item["sha256"]:
        raise ValueError(f"fixture digest mismatch: {relative}")
    if "bytes" in item and path.stat().st_size != item["bytes"]:
        raise ValueError(f"fixture size mismatch: {relative}")
    return path


class Nvml:
    def __init__(self, expected_bytes: int):
        self.api = ctypes.CDLL("libnvidia-ml.so.1")
        if self.api.nvmlInit_v2() != 0:
            raise RuntimeError("NVML initialization failed")
        count = ctypes.c_uint()
        if self.api.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0 or count.value != 1:
            raise RuntimeError("exactly one NVIDIA device must be visible")
        self.device = ctypes.c_void_p()
        if self.api.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self.device)) != 0:
            raise RuntimeError("NVML could not open H200")
        memory = self.read()
        if memory.total != expected_bytes:
            raise RuntimeError(f"H200 capacity differs from contract: {memory.total} != {expected_bytes}")
        if memory.used > 2_000_000_000:
            raise RuntimeError(f"GPU is not idle/exclusive: {memory.used} bytes already used")

    def read(self) -> Memory:
        memory = Memory()
        if self.api.nvmlDeviceGetMemoryInfo(self.device, ctypes.byref(memory)) != 0:
            raise RuntimeError("NVML memory query failed")
        return memory

    def close(self) -> None:
        self.api.nvmlShutdown()


def run(command: list[str], out: Path, nvml: Nvml, env: dict, *, timeout: int = 900) -> dict:
    out = out.resolve()
    out.mkdir(parents=True)
    home, temp, cache = (out / name for name in ("home", "tmp", "cuda-cache"))
    for directory in (home, temp, cache):
        directory.mkdir()
    runtime_env = {**env, "HOME": str(home), "TMPDIR": str(temp),
                   "CUDA_CACHE_PATH": str(cache)}
    initial = nvml.read().used
    if initial > 2_000_000_000:
        raise RuntimeError("GPU became busy before run")
    stop = threading.Event()
    peak = initial
    samples = 0
    sample_error = None

    def sample() -> None:
        nonlocal peak, samples, sample_error
        while not stop.is_set():
            try:
                peak = max(peak, nvml.read().used)
                samples += 1
            except RuntimeError as error:
                sample_error = str(error)
                return
            stop.wait(0.01)

    watcher = threading.Thread(target=sample, daemon=True)
    watcher.start()
    started = time.monotonic_ns()
    timed_out = False
    with (out / "process.log").open("wb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   cwd=out, env=runtime_env, start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    elapsed = (time.monotonic_ns() - started) / 1e9
    stop.set()
    watcher.join()
    if sample_error or samples < 2:
        raise RuntimeError(f"invalid NVML sample: {sample_error}, count={samples}")
    result = {"time_s": elapsed, "peak_device_bytes": peak, "idle_device_bytes": initial,
              "nvml_samples": samples, "nvml_period_s": 0.01, "exit_code": process.returncode,
              "timed_out": timed_out, "command": command}
    (out / "measurement.json").write_text(json.dumps(result, indent=2) + "\n")
    if process.returncode or timed_out:
        raise RuntimeError(f"candidate failed; inspect {out / 'process.log'}")
    return result


def proof_verifier(verifier: Path, proof: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    verdict = out / "official-verdict.json"
    result = subprocess.run([str(verifier), "verify", "--proof", str(proof),
                             "--channel", "blake2s", "--proof-format", "json",
                             "--result", str(verdict)], capture_output=True, text=True,
                            timeout=120)
    if result.returncode != 0 or json.loads(verdict.read_text()).get("verified") is not True:
        raise RuntimeError("pinned official Rust Cairo verifier rejected proof")


def registry_proof_verifier(verifier: Path, proof: Path, out: Path) -> None:
    """Verify a production-registry Blake2s-M31 leaf with verify_cairo_ex."""
    out.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(verifier), str(proof)], capture_output=True,
                            text=True, timeout=120)
    (out / "registry-verdict.log").write_text(result.stdout + result.stderr)
    if result.returncode != 0 or not result.stdout.startswith("RUST_CAIRO_VERIFIER=accepted "):
        raise RuntimeError("pinned Rust production-registry Cairo verifier rejected proof")


def flags(plan: int) -> dict:
    return dict(verified=True, protocol_ok=True, gpu_resident=True,
                statement_ok=True, input_hash_ok=True, planned_arena_bytes=plan)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="built pinned source tree")
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--preprocessed", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--cairo-verifier", type=Path, required=True)
    parser.add_argument("--registry-cairo-verifier", type=Path,
                        help="pinned verify_cairo_cuda_json for production-registry leaves")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "fixtures/public-v1.json")
    parser.add_argument("--config", type=Path, default=ROOT / "benchmark.json")
    parser.add_argument("--case-id", action="append", help="run only selected public cases for smoke")
    parser.add_argument("--preflight", action="store_true", help="hash all selected fixtures without opening CUDA")
    args = parser.parse_args()
    args.out = args.out.resolve()
    config = json.loads(args.config.read_text())
    manifest = json.loads(args.manifest.read_text())
    if (manifest.get("contract_epoch") != config["contractEpoch"] or
            manifest.get("source_commit") != config["sourceCommit"]):
        parser.error("fixture manifest is not bound to source and epoch")
    cases = [case for case in manifest["cases"] if
             args.case_id is None or case["id"] in args.case_id]
    if not cases or (args.case_id and len(cases) != len(set(args.case_id))):
        parser.error("unknown or duplicate case ID")
    if not args.preflight and any(case["family"] == "pipeline" for case in cases):
        if not args.registry_cairo_verifier or not args.registry_cairo_verifier.is_file():
            parser.error("pipeline cases require --registry-cairo-verifier")
    source = args.source.resolve()
    fixture_root = args.fixtures.resolve()
    if not fixture_root.is_dir() or args.round < 0:
        parser.error("fixture directory and nonnegative round are required")
    if not args.preflight and subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() != config["sourceCommit"]:
        parser.error("candidate source does not descend from pinned commit")
    cairo = source / "zig-out/bin/stwo-cairo-cuda"
    circuit = source / "zig-out/bin/stwo-circuit-recursion-cuda"
    if not args.preflight:
        for path in (cairo, circuit, args.preprocessed, args.cairo_verifier):
            if not path.is_file():
                parser.error(f"required asset missing: {path}")
    for case in cases:
        if case["family"] == "pie":
            checked_file(fixture_root, case["input"])
        else:
            for item in case["inputs"]:
                checked_file(fixture_root, item)
                if "preimage_path" in item:
                    checked_file(fixture_root, {"path": item["preimage_path"],
                                                "sha256": item["preimage_sha256"]})
    if args.preflight:
        print(f"Preflight OK: {len(cases)} hash-pinned cases")
        return
    nvml = Nvml(config["hardware"]["deviceBytes"])
    rows = []
    env = candidate_env(os.environ, args.preprocessed, args.artifact_dir)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        for case in cases:
            case_dir = args.out / case["id"].replace(":", "_")
            if case["family"] == "pie":
                case_dir.mkdir()
                input_path = checked_file(fixture_root, case["input"])
                proof = case_dir / "proof.json"
                report = case_dir / "backend.json"
                measured = run([str(cairo), "prove", "--backend", "cuda", "--input", str(input_path),
                                "--output", str(proof), "--report-out", str(report), "--repeat", "1"],
                               case_dir / "run", nvml, env)
                proof_verifier(args.cairo_verifier, proof, case_dir)
                if sha(proof) != case["expected_proof_sha256"]:
                    raise RuntimeError(f"canonical Cairo proof differs: {case['id']}")
                backend = json.loads(report.read_text())
                trials = backend.get("completed_trials", [])
                if len(trials) != 1 or sha(input_path) != bytes(trials[0]["input_sha256"]).hex():
                    raise RuntimeError("Cairo backend receipt is not bound to fixture")
                trial = trials[0]
                if trial["verdict"]["provider"] != "nvidia_cuda" or any(
                        trial["verdict"]["counters"][key] != 0 for key in
                        ("cpu_fallback_attempts", "cpu_fallbacks_completed")):
                    raise RuntimeError("Cairo prover used non-CUDA proving")
                if any(trial["protocol"].get(key) != value for key, value in
                       {"query_count": 70, "query_pow_bits": 26, "interaction_pow_bits": 24,
                        "log_blowup_factor": 1, "fri_fold_step": 1,
                        "log_last_layer_degree_bound": 0, "channel_salt": 0,
                        "preprocessed_variant": "canonical"}.items()):
                    raise RuntimeError("Cairo security profile differs")
                plan = trial["planned_arena_bytes"]
            elif case["family"] == "recursion":
                case_dir.mkdir()
                manifest_file = case_dir / "leaves.json"
                manifest_file.write_text(json.dumps({"leaves": [str(checked_file(fixture_root, x))
                                                              for x in case["inputs"]]}))
                proof, outputs, packed = [case_dir / name for name in
                                          ("root.proof", "root_outputs.json", "root_packed.json")]
                measured = run([str(circuit), "fold-tree", "--registry",
                                str(source / "vectors/circuit/official/registries/production.json"),
                                "--manifest", str(manifest_file), "--proof", str(proof),
                                "--outputs", str(outputs), "--packed", str(packed)],
                               case_dir / "run", nvml, env)
                for key, path in (("proof_sha256", proof), ("outputs_sha256", outputs),
                                  ("packed_sha256", packed)):
                    if sha(path) != case["expected_root"][key]:
                        raise RuntimeError(f"recursive root {key} differs")
                import re
                fold_log = (case_dir / "run/process.log").read_text(errors="replace")
                arenas = [int(value) for value in re.findall(r"circuit-proof .*arena_bytes=(\d+)", fold_log)]
                if not arenas:
                    raise RuntimeError("fold has no resident circuit proof telemetry")
                plan = max(arenas)
            else:
                case_dir.mkdir()
                if case.get("mode") in ("serial", "batch_integrated",
                                        "serial_external", "batch_integrated_external"):
                    case_file = case_dir / "case.json"
                    case_file.write_text(json.dumps(case))
                    command = ["python3", str(ROOT / "harness/run_pipeline.py"),
                               "--source", str(source), "--fixtures", str(fixture_root),
                               "--case", str(case_file), "--out", str(case_dir / "result")]
                    measured = run(command, case_dir / "run", nvml, env)
                    receipt = json.loads((case_dir / "result/receipt.json").read_text())
                    if (receipt.get("schema") != "stwo-cuda-external-pipeline-v1" or
                            receipt.get("backend") != "cuda-resident" or
                            receipt.get("mode") != case["mode"] or
                            len(receipt.get("leaves", [])) != len(case["inputs"])):
                        raise RuntimeError("invalid external pipeline receipt")
                    if receipt.get("registry_sha256") != sha(source / "vectors/circuit/official/registries/production.json"):
                        raise RuntimeError("pipeline registry digest differs")
                    for key in ("proof_sha256", "outputs_sha256", "packed_sha256"):
                        if receipt["root"][key] != case["expected_root"][key]:
                            raise RuntimeError(f"external pipeline root {key} differs")
                    arenas = []
                    for index, item in enumerate(case["inputs"]):
                        registry_proof_verifier(args.registry_cairo_verifier,
                                                case_dir / "result" / f"leaf-{index}.cairo_proof.json",
                                                case_dir / f"cairo-verification-{index}")
                        report = json.loads((case_dir / "result" / f"leaf-{index}.cairo_report.json").read_text())
                        trials = report.get("completed_trials", [])
                        if len(trials) != 1 or bytes(trials[0]["input_sha256"]).hex() != item["sha256"]:
                            raise RuntimeError("external pipeline Cairo proof is not bound to fixture")
                        trial = trials[0]
                        if trial["verdict"]["provider"] != "nvidia_cuda" or any(
                                trial["verdict"]["counters"][key] != 0 for key in
                                ("cpu_fallback_attempts", "cpu_fallbacks_completed")):
                            raise RuntimeError("external pipeline used non-CUDA proving")
                        if any(trial["protocol"].get(key) != value for key, value in
                               {"query_count": 70, "query_pow_bits": 26,
                                "interaction_pow_bits": 24, "log_blowup_factor": 1,
                                "fri_fold_step": 1, "log_last_layer_degree_bound": 0,
                                "channel_salt": 0, "preprocessed_variant": "canonical"}.items()):
                            raise RuntimeError("external pipeline security profile differs")
                        arenas.append(trial["planned_arena_bytes"])
                    import re
                    profiles = []
                    for log in receipt["logs"]:
                        content = Path(log).read_text(errors="replace")
                        matches = re.findall(r"circuit-cuda circuit-proof profile=(internal|root) resident_ns=\d+ "
                                             r"verify_ns=\d+ convert_ns=\d+ arena_bytes=(\d+)", content)
                        profiles.extend(profile for profile, _ in matches)
                        arenas.extend(int(arena) for _, arena in matches)
                    if profiles != ["internal"] * len(case["inputs"]) + ["root"] * (len(case["inputs"]) - 1):
                        raise RuntimeError("external pipeline circuit proof telemetry differs")
                    plan = max(arenas)
                else:
                    raise RuntimeError(f"unknown pipeline mode: {case.get('mode')}")
            row = {"case_id": case["id"], "round": args.round, "time_s": measured["time_s"],
                   "peak_device_bytes": measured["peak_device_bytes"], **flags(plan)}
            rows.append(row)
            (args.out / "arm.json").write_text(json.dumps(rows, indent=2) + "\n")
            print(f"{case['id']}: {row['time_s']:.3f}s, {row['peak_device_bytes']} bytes", flush=True)
    finally:
        nvml.close()


if __name__ == "__main__":
    main()
