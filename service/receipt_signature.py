#!/usr/bin/env python3
"""Sign and verify immutable judge receipts with an external Ed25519 key."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def openssl(*args: str) -> bytes:
    result = subprocess.run(["openssl", *args], capture_output=True)
    if result.returncode:
        raise ValueError("OpenSSL receipt signature operation failed")
    return result.stdout


def public_key(private_key: Path) -> bytes:
    return openssl("pkey", "-in", str(private_key), "-pubout", "-outform", "DER")


def require_ed25519(public_der: bytes) -> None:
    if len(public_der) != 44 or not public_der.startswith(ED25519_SPKI_PREFIX):
        raise ValueError("operator key must be Ed25519")


def sign(receipt: Path, private_key: Path, state: Path) -> dict:
    key = private_key.resolve()
    if (not private_key.is_file() or private_key.is_symlink() or
            key.is_relative_to(ROOT) or key.is_relative_to(state.resolve()) or
            stat.S_IMODE(key.stat().st_mode) & 0o077):
        raise ValueError("signing key must be a private regular file outside repositories and service state")
    raw = receipt.read_bytes()
    pub = public_key(key)
    require_ed25519(pub)
    with tempfile.TemporaryDirectory(prefix="receipt-sign-", dir=state / "tmp") as temporary:
        signature_path = Path(temporary) / "signature.bin"
        public_path = Path(temporary) / "public.pem"
        openssl("pkeyutl", "-sign", "-rawin", "-inkey", str(key),
                "-in", str(receipt), "-out", str(signature_path))
        openssl("pkey", "-in", str(key), "-pubout", "-out", str(public_path))
        openssl("pkeyutl", "-verify", "-rawin", "-pubin", "-inkey",
                str(public_path), "-sigfile", str(signature_path), "-in", str(receipt))
        signature = signature_path.read_bytes()
    if len(signature) != 64 or receipt.read_bytes() != raw:
        raise ValueError("signed receipt changed during publication")
    return {"schema": "stwo-cuda-receipt-signature-v1", "algorithm": "Ed25519",
            "receipt_sha256": hashlib.sha256(raw).hexdigest(),
            "key_id": hashlib.sha256(pub).hexdigest(),
            "signature_base64": base64.b64encode(signature).decode("ascii")}


def verify(receipt: Path, envelope: dict, public_key_path: Path) -> None:
    raw = receipt.read_bytes()
    if (envelope.get("schema") != "stwo-cuda-receipt-signature-v1" or
            envelope.get("algorithm") != "Ed25519" or
            envelope.get("receipt_sha256") != hashlib.sha256(raw).hexdigest()):
        raise ValueError("receipt signature metadata differs")
    pub = openssl("pkey", "-pubin", "-in", str(public_key_path),
                  "-pubout", "-outform", "DER")
    require_ed25519(pub)
    if envelope.get("key_id") != hashlib.sha256(pub).hexdigest():
        raise ValueError("receipt signer key differs")
    try:
        signature = base64.b64decode(envelope["signature_base64"], validate=True)
    except (KeyError, ValueError) as error:
        raise ValueError("invalid receipt signature encoding") from error
    if len(signature) != 64:
        raise ValueError("invalid Ed25519 signature length")
    with tempfile.TemporaryDirectory(prefix="receipt-verify-") as temporary:
        sig_path = Path(temporary) / "signature.bin"
        sig_path.write_bytes(signature)
        openssl("pkeyutl", "-verify", "-rawin", "-pubin", "-inkey",
                str(public_key_path), "-sigfile", str(sig_path), "-in", str(receipt))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    args = parser.parse_args()
    verify(args.receipt, json.loads(args.signature.read_text()), args.public_key)
    print("receipt signature verified")


if __name__ == "__main__":
    main()
