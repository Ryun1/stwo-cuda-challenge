#!/usr/bin/env python3
"""Check the GitHub-side H200 judge configuration before dispatch."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.intake import IntakeError


REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
RUNNER_LABEL = "h200-stwo-challenge"
REQUIRED_VARIABLES = frozenset({
    "STWO_FIXTURE_ROOT", "STWO_BASELINE_ROOT", "STWO_SUBMISSION_STATE",
    "STWO_PREPROCESSED_ASSET", "STWO_CUDA_ARTIFACT_DIR",
    "STWO_CAIRO_VERIFIER", "STWO_REGISTRY_CAIRO_VERIFIER",
    "STWO_RANKED_MANIFEST",
})


def github_config(repository: str) -> tuple[dict, dict]:
    runner_json = subprocess.check_output(
        ["gh", "api", f"repos/{repository}/actions/runners?per_page=100"], text=True)
    variable_json = subprocess.check_output(
        ["gh", "api", f"repos/{repository}/actions/variables?per_page=100"], text=True)
    return json.loads(runner_json), json.loads(variable_json)


def check_activation(repository: str, *, fetch=github_config) -> dict:
    if not REPOSITORY.fullmatch(repository):
        raise IntakeError("invalid GitHub repository")
    runners, variables = fetch(repository)
    if (runners.get("total_count", 0) > len(runners.get("runners", [])) or
            variables.get("total_count", 0) > len(variables.get("variables", []))):
        raise IntakeError("GitHub configuration exceeds one API page; inspect it before dispatch")
    names = {entry["name"] for entry in variables["variables"]
             if isinstance(entry.get("value"), str) and entry["value"].strip()}
    missing = REQUIRED_VARIABLES - names
    if missing:
        raise IntakeError("H200 judge variables are missing: " + ", ".join(sorted(missing)))
    ready = [runner for runner in runners["runners"] if
             runner.get("status") == "online" and not runner.get("busy") and
             {"self-hosted", RUNNER_LABEL} <=
             {label["name"] for label in runner.get("labels", [])}]
    if not ready:
        raise IntakeError(f"no idle online self-hosted runner with label {RUNNER_LABEL}")
    return {"repository": repository, "runner_count": len(ready),
            "required_variable_count": len(REQUIRED_VARIABLES)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, help="OWNER/REPO")
    args = parser.parse_args()
    try:
        print(json.dumps(check_activation(args.repository), indent=2))
    except IntakeError as error:
        parser.exit(2, f"H200 activation check failed: {error}\n")


if __name__ == "__main__":
    main()
