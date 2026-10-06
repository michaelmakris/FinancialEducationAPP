"""
Create the BFF's keys:
  * Ed25519 key pair the BFF signs API tokens with
  * a symmetric data key that encrypts TOTP secrets at rest (bff_data_key)

    python -m scripts.generate_keys            # writes ../secrets/bff_ed25519_{private,public}.pem
    python -m scripts.generate_keys --force    # rotate (restart BFF and API afterwards)

The private key stays with the BFF (BFF_SIGNING_KEY_FILE). The API only gets
the public key (API_TRUSTED_ISSUERS=bff=/path/bff_ed25519_public.pem), so it
can verify tokens but never create them. secrets/ is git-ignored.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "secrets"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--name", default="bff", help="issuer name, e.g. bff or mcp")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    args.dir.mkdir(parents=True, exist_ok=True)
    priv_path = args.dir / f"{args.name}_ed25519_private.pem"
    pub_path = args.dir / f"{args.name}_ed25519_public.pem"
    data_key = args.dir / f"{args.name}_data_key"
    if args.name == "bff" and not data_key.exists():
        # Never rotated by --force: it would make every stored TOTP secret unreadable.
        data_key.write_bytes(Fernet.generate_key())
        try:
            os.chmod(data_key, 0o600)
        except OSError:
            pass
        print(f"wrote {data_key}")
    if priv_path.exists() and not args.force:
        print(f"{priv_path} already exists (use --force to rotate)")
        return 0
    key = Ed25519PrivateKey.generate()
    priv_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
    try:
        os.chmod(priv_path, 0o600)
    except OSError:
        pass  # Windows: rely on the user profile ACLs
    pub_path.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                       serialization.PublicFormat.SubjectPublicKeyInfo))
    print(f"wrote {priv_path}\nwrote {pub_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
