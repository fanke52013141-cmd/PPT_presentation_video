#!/usr/bin/env python3
"""Generate the Agent capability matrix documentation from the registry.

Usage:
    python scripts/generate_agent_contracts.py           # Generate docs
    python scripts/generate_agent_contracts.py --check    # CI mode: fail if out of sync

This script reads agent_contract.capabilities.CAPABILITIES and produces:
- docs/agent/capability-matrix.md  (human-readable table)

In --check mode, it generates to a temp location and compares with the
committed file. If they differ, it exits non-zero (CI failure).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

# Ensure repo root is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_contract.capabilities import CAPABILITIES, CapabilityStatus
from agent_contract.versions import AGENT_API_VERSION, get_contract_hash


OUTPUT_DIR = REPO_ROOT / "docs" / "agent"
OUTPUT_FILE = OUTPUT_DIR / "capability-matrix.md"


def generate_markdown() -> str:
    """Generate the capability matrix as Markdown."""
    lines: list[str] = []
    lines.append("# Agent Capability Matrix")
    lines.append("")
    lines.append(f"- **Agent API Version**: {AGENT_API_VERSION}")
    lines.append(f"- **Contract Hash**: `{get_contract_hash()}`")
    lines.append(f"- **Total Capabilities**: {len(CAPABILITIES)}")
    lines.append("")
    lines.append("This document is auto-generated from `agent_contract/capabilities.py`.")
    lines.append("Do not edit manually — run `python scripts/generate_agent_contracts.py`.")
    lines.append("")
    lines.append("## Capability Table")
    lines.append("")

    # Table header
    lines.append("| Capability ID | Version | Status | Method | Agent API Path | MCP Tool | CLI Command | Service Ref | Long-running | Destructive |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")

    for cap in CAPABILITIES:
        row = "| "
        row += f"`{cap.id}` | "
        row += f"{cap.version} | "
        row += f"{cap.status.value} | "
        row += f"{cap.agent_api_method} | "
        row += f"`{cap.agent_api_path}` | "
        row += f"`{cap.mcp_tool_name}` | "
        row += f"`{cap.cli_command}` | "
        row += f"`{cap.service_ref}` | "
        row += ("Yes" if cap.long_running else "No") + " | "
        row += ("Yes" if cap.destructive else "No") + " |"
        lines.append(row)

    lines.append("")

    # Checkpoint stages
    lines.append("## Pipeline Checkpoints")
    lines.append("")
    from agent_contract.operations import CHECKPOINT_STAGES
    lines.append("| Checkpoint | Label | Internal Stage | Description |")
    lines.append("|---|---|---|---|")
    for name, info in CHECKPOINT_STAGES.items():
        lines.append(f"| `{name}` | {info['label']} | `{info['internal_stage']}` | {info['description']} |")

    lines.append("")

    # MCP tool summary
    lines.append("## MCP Tool Summary")
    lines.append("")
    stable_caps = [c for c in CAPABILITIES if c.status == CapabilityStatus.stable]
    lines.append(f"The MCP server exposes **{len(stable_caps)}** stable tools:")
    lines.append("")
    for cap in stable_caps:
        lines.append(f"- `{cap.mcp_tool_name}` — {cap.description}")
    lines.append("")

    # Resource URIs
    lines.append("## Resource URIs")
    lines.append("")
    lines.append("MCP resources use the following URI scheme:")
    lines.append("")
    lines.append("```")
    lines.append("ppt://projects/{project_id}/summary")
    lines.append("ppt://projects/{project_id}/slides")
    lines.append("ppt://projects/{project_id}/slides/{slide_id}/image")
    lines.append("ppt://projects/{project_id}/slides/{slide_id}/audio")
    lines.append("ppt://projects/{project_id}/videos/latest")
    lines.append("ppt://projects/{project_id}/runs/{run_id}/logs")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Agent contract documentation")
    parser.add_argument(
        "--check", action="store_true",
        help="CI mode: fail if generated doc differs from committed version",
    )
    args = parser.parse_args()

    content = generate_markdown()

    if args.check:
        # CI mode: compare
        if not OUTPUT_FILE.exists():
            print(f"ERROR: {OUTPUT_FILE} does not exist. Run without --check first.")
            return 1

        existing = OUTPUT_FILE.read_text(encoding="utf-8")
        if existing.strip() != content.strip():
            print(f"ERROR: {OUTPUT_FILE} is out of sync with the capability registry.")
            print("Run: python scripts/generate_agent_contracts.py")
            return 1
        print(f"OK: {OUTPUT_FILE} is up to date.")
        return 0

    # Generate mode
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(content, encoding="utf-8")
    print(f"Generated: {OUTPUT_FILE}")
    print(f"  Capabilities: {len(CAPABILITIES)}")
    print(f"  Contract hash: {get_contract_hash()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
