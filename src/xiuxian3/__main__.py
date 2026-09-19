"""Small local diagnostic entry point for the P1 runtime."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence

from .bootstrap.config import RuntimeConfig
from .plugin import create_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xiuxian3")
    parser.add_argument("--data-dir", help="override XIUXIAN3_DATA_DIR for this process")
    parser.add_argument(
        "--check",
        action="store_true",
        help="start the local runtime and print its readiness report",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    environ = dict(os.environ)
    if args.data_dir is not None:
        environ["XIUXIAN3_DATA_DIR"] = args.data_dir
    runtime = create_runtime(environ)
    runtime.start()
    if args.check:
        print(json.dumps(runtime.health().as_dict(), sort_keys=True))
    else:
        print(json.dumps({"status": runtime.phase.value}, sort_keys=True))
    runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())