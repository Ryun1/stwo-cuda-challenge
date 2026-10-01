#!/usr/bin/env python3
"""Exercise the actual Docker boundary on a Linux CPU host before H200 use."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.run_arm import run
from harness.sandbox import docker_command, stage_inputs


PROBE = r"""
import json, os, pathlib, socket, sys, time
sys.path.insert(0, '/judge')
import harness.run_pipeline

def blocked_write(path):
    try:
        pathlib.Path(path).write_text('tampered')
        return False
    except OSError:
        return True

network_blocked = True
try:
    socket.create_connection(('1.1.1.1', 443), timeout=.3).close()
    network_blocked = False
except OSError:
    pass

output = pathlib.Path('/work/probe-output.txt')
output.write_text('published')
time.sleep(.05)
print(json.dumps({
    'uid': os.getuid(),
    'current_input': pathlib.Path('/inputs/current.cpi').read_bytes() == b'current case',
    'sibling_hidden': not pathlib.Path('/inputs/sibling.cpi').exists(),
    'fixture_readonly': blocked_write('/inputs/current.cpi'),
    'asset_readonly': blocked_write('/assets/preprocessed.bin'),
    'network_blocked': network_blocked,
    'token_hidden': 'GH_TOKEN' not in os.environ,
    'docker_socket_hidden': not pathlib.Path('/var/run/docker.sock').exists(),
    'judge_sentinel_hidden': not pathlib.Path(sys.argv[1]).exists(),
    'private_pid_namespace': b'python3' in pathlib.Path('/proc/1/cmdline').read_bytes(),
    'output_published': output.read_text() == 'published',
}))
"""


class FakeNvml:
    def read(self):
        return SimpleNamespace(used=10_000)


def probe(image: str) -> dict:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("the Docker boundary probe requires Linux")
    with tempfile.TemporaryDirectory(prefix="stwo-sandbox-probe-") as temporary:
        root = Path(temporary).resolve()
        runtime = root / "runtime"
        runtime.mkdir()
        fixture_store = root / "judge-fixtures"
        fixture_store.mkdir()
        current = fixture_store / "current.cpi"
        current.write_bytes(b"current case")
        current.chmod(0o666)
        (fixture_store / "sibling.cpi").write_bytes(b"other holdout")
        sentinel = root / "judge-only-sentinel"
        sentinel.write_text("secret")
        import hashlib
        staged = stage_inputs(root / "staged", [
            (current, "current.cpi", hashlib.sha256(current.read_bytes()).hexdigest())])
        case = root / "case"
        case.mkdir(mode=0o777)
        case.chmod(0o777)
        scratch = case / "run"
        scratch.mkdir(mode=0o777)
        scratch.chmod(0o777)
        for name in ("home", "tmp", "cuda-cache"):
            directory = scratch / name
            directory.mkdir(mode=0o777)
            directory.chmod(0o777)
        preprocessed = root / "preprocessed.bin"
        preprocessed.write_bytes(b"asset")
        preprocessed.chmod(0o666)
        artifacts = root / "artifacts"
        artifacts.mkdir()
        command = docker_command(image, runtime, staged, case, preprocessed, artifacts,
                                 ["python3", "-c", PROBE, str(sentinel)],
                                 {"GH_TOKEN": "must-not-enter-container"}, gpu=False)
        run(command, root / "judge-logs", FakeNvml(), {}, timeout=30, container=True)
        lines = (root / "judge-logs/process.log").read_text().splitlines()
        records = [json.loads(line) for line in lines if line.startswith("{")]
        if len(records) != 1:
            raise RuntimeError("sandbox probe did not emit exactly one result")
        result = records[0]
        expected_fields = {"current_input", "sibling_hidden", "fixture_readonly",
                           "asset_readonly", "network_blocked", "token_hidden",
                           "docker_socket_hidden", "judge_sentinel_hidden",
                           "private_pid_namespace", "output_published"}
        if (set(result) != expected_fields | {"uid"} or result.get("uid") != 65532 or
                any(result[key] is not True for key in expected_fields)):
            raise RuntimeError(f"sandbox access policy failed: {result}")
        if current.read_bytes() != b"current case" or preprocessed.read_bytes() != b"asset":
            raise RuntimeError("sandbox modified a read-only input")
        if (case / "probe-output.txt").read_text() != "published":
            raise RuntimeError("sandbox could not publish an output")
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="locally present SHA-256 image ID")
    args = parser.parse_args()
    print(json.dumps(probe(args.image), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
