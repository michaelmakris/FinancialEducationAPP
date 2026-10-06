"""
DEV ONLY: mint an API token signed with the local BFF key, for curl / the CLI
agent (backend/agent/chat_agent.py) / Swagger at http://localhost:8000/docs.

    python -m scripts.dev_token --sub cli-dev                 # customer scopes, 1 hour
    python -m scripts.dev_token --sub ops --role staff        # + ops:read

The API caps token lifetime at 300 s, so tokens longer than that are refused;
the default here is therefore 300 s. Re-run when it expires.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import security  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sub", default="cli-dev", help="customer id the API will see")
    parser.add_argument("--role", choices=sorted(security.ROLE_SCOPES), default="customer")
    parser.add_argument("--lifetime", type=int, default=300)
    args = parser.parse_args()
    print(security.mint_api_token(args.sub, args.role, args.lifetime))
    return 0


if __name__ == "__main__":
    sys.exit(main())
