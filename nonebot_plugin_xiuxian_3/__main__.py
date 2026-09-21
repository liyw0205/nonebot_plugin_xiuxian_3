"""Small diagnostic entry point for the plugin package."""

from __future__ import annotations

import argparse
import asyncio

from .runtime import create_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Xiuxian 3 runtime diagnostics")
    parser.add_argument("--data-dir", default=None, help="runtime data directory")
    args = parser.parse_args()

    async def run() -> None:
        runtime = create_runtime(data_dir=args.data_dir)
        await runtime.initialize()
        await runtime.close()
        print(f"xiuxian3 ready: {runtime.settings.database_path}")

    asyncio.run(run())


if __name__ == "__main__":
    main()
