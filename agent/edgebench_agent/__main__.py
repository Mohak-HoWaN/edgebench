"""``python -m edgebench_agent --server http://127.0.0.1:8000 --token <one-time token>``"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .agent import Agent
from .client import Rejected, ServerClient


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="edgebench-agent", description="Runs EdgeBench benchmarks on this machine.")
    ap.add_argument("--server", required=True, help="the EdgeBench server, for example http://127.0.0.1:8000")
    ap.add_argument("--token", help="one-time enrolment token from the Devices page (only needed the first time)")
    ap.add_argument("--name", help="a name for this device (defaults to the one chosen in the app)")
    ap.add_argument("--state-dir", type=Path, default=Path.home() / ".edgebench-agent")
    ap.add_argument("--once", action="store_true", help="exit after the first job")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    agent = Agent(ServerClient(args.server), args.state_dir)
    try:
        if args.token:
            data = agent.enroll(args.token, args.name)
            print(f"Enrolled as '{data['name']}' ({data['kind']}). Waiting for jobs; Ctrl+C stops the agent.")
        elif agent.load_identity():
            print(f"edgebench-agent {__version__}: waiting for jobs; Ctrl+C stops the agent.")
        else:
            print("This device is not enrolled yet. Add it on the Devices page and pass --token.", file=sys.stderr)
            return 2
        agent.serve(once=args.once)
    except Rejected as exc:
        print(f"The server does not accept this device: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        agent.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
