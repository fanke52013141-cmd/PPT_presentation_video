"""Fail when a business entrypoint changes without an Agent coverage decision."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_contract.features import coverage_errors, load_features


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-complete", action="store_true", help="Final full-openness release gate")
    args = parser.parse_args()
    errors = coverage_errors()
    if args.require_complete:
        errors.extend(f"Incomplete feature: {key}" for key, value in load_features().items()
                      if value["coverage"] in {"pending", "partial"})
    for error in errors:
        print(error)
    if errors:
        return 1
    print("Agent business entrypoint coverage decisions are current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
