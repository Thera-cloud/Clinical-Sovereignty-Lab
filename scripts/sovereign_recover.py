#!/usr/bin/env python3
"""
SOVEREIGN RECOVERY — Self-healing relaunch from cloud backup.
Layer 8 of Castle Defense architecture.

Usage:
  python3 scripts/sovereign_recover.py --signal <onedrive_signal_url>
  python3 scripts/sovereign_recover.py --azure <azure_blob_url>
  python3 scripts/sovereign_recover.py --local <local_bundle_path>

Requirements:
  - Python 3.11+
  - Docker + Docker Compose
  - cryptography package (pip install cryptography)

(c) 2026 Clinical Sovereignty Lab. All rights reserved.
"""

import argparse
import getpass
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path


def verify_integrity(bundle_path: str, expected_hash: str) -> bool:
    """Verify SHA-256 hash of the bundle."""
    sha = hashlib.sha256()
    with open(bundle_path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    actual = sha.hexdigest()
    if actual != expected_hash:
        print(f"INTEGRITY CHECK FAILED!")
        print(f"  Expected: {expected_hash}")
        print(f"  Actual:   {actual}")
        return False
    print(f"  Integrity verified: {actual[:16]}...")
    return True


def decrypt_bundle(bundle_path: str, vault_key: str, passphrase: str = "") -> bytes:
    """Decrypt the bundle using VAULT_ENCRYPTION_KEY + optional passphrase."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes

    with open(bundle_path, "rb") as f:
        data = f.read()

    salt = data[:16]
    nonce = data[16:28]
    ciphertext = data[28:]

    key_bytes = bytes.fromhex(vault_key)

    if passphrase:
        key_bytes = key_bytes + passphrase.encode()

    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"sovereign-fall-command",
    )
    derived_key = kdf.derive(key_bytes)

    aesgcm = AESGCM(derived_key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)

    return plaintext


def extract_bundle(plaintext: bytes, target_dir: str) -> None:
    """Extract the decrypted bundle to the target directory."""
    os.makedirs(target_dir, exist_ok=True)

    with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r:gz") as tar:
        tar.extractall(path=target_dir)

    print(f"  Extracted to: {target_dir}")


def relaunch(target_dir: str) -> bool:
    """Run docker compose up in the target directory."""
    compose_file = os.path.join(target_dir, "docker-compose.yml")
    if not os.path.exists(compose_file):
        print(f"  ERROR: docker-compose.yml not found at {compose_file}")
        return False

    print("  Starting Docker services...")
    result = subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=target_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("  Docker services started successfully!")
        return True
    else:
        print(f"  Docker Compose failed: {result.stderr}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Sovereign Recovery — relaunch from backup")
    parser.add_argument("--signal", help="OneDrive relaunch signal URL")
    parser.add_argument("--azure", help="Azure Blob Storage URL for encrypted bundle")
    parser.add_argument("--local", help="Local path to encrypted bundle")
    parser.add_argument("--target", default="./sovereign-recovery", help="Target directory for extraction")
    parser.add_argument("--hash", help="Expected SHA-256 hash of the bundle")
    parser.add_argument("--vault-key", help="VAULT_ENCRYPTION_KEY (hex)")
    parser.add_argument("--skip-docker", action="store_true", help="Skip Docker relaunch")
    args = parser.parse_args()

    print("=" * 60)
    print("  SOVEREIGN RECOVERY — Little Nate Self-Healing")
    print("=" * 60)
    print()

    # Determine bundle source
    bundle_path = None

    if args.local:
        bundle_path = args.local
        if not os.path.exists(bundle_path):
            print(f"ERROR: Bundle not found at {bundle_path}")
            sys.exit(1)
    elif args.azure:
        print("Downloading from Azure Blob Storage...")
        print("  (Azure download not yet implemented — use --local with a downloaded bundle)")
        sys.exit(1)
    elif args.signal:
        print("Reading OneDrive relaunch signal...")
        print("  (OneDrive signal reading not yet implemented — use --local)")
        sys.exit(1)
    else:
        print("ERROR: Provide --signal, --azure, or --local")
        parser.print_help()
        sys.exit(1)

    print(f"  Bundle: {bundle_path}")
    print(f"  Size: {os.path.getsize(bundle_path) / (1024*1024):.1f} MB")
    print()

    # Verify integrity
    if args.hash:
        print("[1/4] Verifying integrity...")
        if not verify_integrity(bundle_path, args.hash):
            sys.exit(1)
    else:
        print("[1/4] Skipping integrity check (no --hash provided)")

    # Get decryption key
    vault_key = args.vault_key or os.getenv("VAULT_ENCRYPTION_KEY", "")
    if not vault_key:
        vault_key = getpass.getpass("Enter VAULT_ENCRYPTION_KEY (hex): ")

    passphrase = getpass.getpass("Enter recovery passphrase (or press Enter to skip): ")

    # Decrypt
    print("[2/4] Decrypting bundle...")
    try:
        plaintext = decrypt_bundle(bundle_path, vault_key, passphrase)
        print(f"  Decrypted: {len(plaintext) / (1024*1024):.1f} MB")
    except Exception as e:
        print(f"  DECRYPTION FAILED: {e}")
        print("  Check your VAULT_ENCRYPTION_KEY and passphrase.")
        sys.exit(1)

    # Extract
    print(f"[3/4] Extracting to {args.target}...")
    try:
        extract_bundle(plaintext, args.target)
    except Exception as e:
        print(f"  EXTRACTION FAILED: {e}")
        sys.exit(1)

    # Relaunch
    if not args.skip_docker:
        print("[4/4] Relaunching Docker services...")
        approval = input("  Approve relaunch? (yes/no): ").strip().lower()
        if approval in ("yes", "y"):
            if relaunch(args.target):
                print()
                print("=" * 60)
                print("  SOVEREIGN RECOVERY COMPLETE")
                print("  Little Nate is alive.")
                print("=" * 60)
            else:
                print("  Relaunch failed. Check Docker logs.")
                sys.exit(1)
        else:
            print("  Relaunch cancelled. Bundle extracted to:", args.target)
    else:
        print("[4/4] Docker relaunch skipped (--skip-docker)")
        print(f"  Bundle extracted to: {args.target}")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
