from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow", type=Path)
    args = parser.parse_args()

    text = args.workflow.read_text(encoding="utf-8")
    markers = {
        "download": "Download patch artifact",
        "probe": "Probe platform-observed pending artifact",
        "handler": "Process Safe Outputs",
    }

    positions = {name: text.find(marker) for name, marker in markers.items()}
    missing = [name for name, pos in positions.items() if pos < 0]
    if missing:
        raise SystemExit(f"Missing compiled step marker(s): {', '.join(missing)}")

    if not positions["download"] < positions["probe"] < positions["handler"]:
        raise SystemExit(
            "Unsafe or unsupported ordering: expected artifact download < probe < handler; "
            f"observed {positions}"
        )

    print("PASS: compiled workflow orders download < probe < built-in handler")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
