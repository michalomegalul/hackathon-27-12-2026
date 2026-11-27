"""python -m s2d.api token <name> <student|teacher|admin>   prints a new token
python -m s2d.api tokens                                  lists who has one
python -m s2d.api serve [--port 8000]                     runs the API (uvicorn)
"""

from __future__ import annotations

import argparse
import sys

from .auth import ROLES, add_token, tokens_path
from . import store


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m s2d.api")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("token", help="create a token")
    t.add_argument("name")
    t.add_argument("role", choices=ROLES)
    sub.add_parser("tokens", help="list token holders (not the tokens)")
    s = sub.add_parser("serve", help="run the API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    if args.cmd == "token":
        print(add_token(args.name, args.role))
        print(f"stored in {tokens_path()}", file=sys.stderr)
    elif args.cmd == "tokens":
        for tok, e in (store.read_json(tokens_path()) or {}).items():
            print(f"{e.get('name')}\t{e.get('role')}\t{tok[:4]}…")
    else:
        import uvicorn
        uvicorn.run("s2d.api.main:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
