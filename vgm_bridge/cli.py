from __future__ import annotations

import argparse
import os
from pathlib import Path

from .engine import Bridge


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "once", "healthcheck"])
    args = parser.parse_args()
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))

    if args.command == "healthcheck":
        required = [data_dir / "config/config.json"]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise SystemExit("Missing required files: " + ", ".join(missing))
        print("ok")
        return

    bridge = Bridge(data_dir)
    if args.command == "once":
        state = bridge.setup()
        bridge.repo.pull()
        state = bridge.process_decisions(state)
        bridge.create_request_if_needed(state)
        bridge.write_status(state)
        return

    bridge.run_forever()


if __name__ == "__main__":
    main()
