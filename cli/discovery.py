"""CLI bootstrap commands use the runtime service, independent of local schemas."""

import json
from pathlib import Path

from agent_client.client import AgentClient


def execute(args):
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    if args.command == "capability":
        result = client.describe(args.capability_id) if args.action == "show" else client.discover(
            q=args.q, domain=args.domain, offset=args.offset, limit=args.limit)
    else:
        text = Path(args.arguments_file).read_text(encoding="utf-8") if args.arguments_file else args.arguments
        arguments = json.loads(text)
        if not isinstance(arguments, dict):
            raise ValueError("Arguments must be a JSON object")
        result = client.invoke(args.capability_id, arguments,
                               expected_contract_revision=args.contract_revision)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def add_commands(subparsers):
    parser = subparsers.add_parser("capability", help="Discover current service capabilities")
    commands = parser.add_subparsers(dest="action", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--q", default="")
    listing.add_argument("--domain", default="")
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--limit", type=int, default=50)
    listing.set_defaults(func=execute)
    show = commands.add_parser("show")
    show.add_argument("capability_id")
    show.set_defaults(func=execute)
    invoke = subparsers.add_parser("invoke", help="Invoke a current capability using its described revision")
    invoke.add_argument("capability_id")
    inputs = invoke.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--arguments")
    inputs.add_argument("--arguments-file")
    invoke.add_argument("--contract-revision", required=True)
    invoke.set_defaults(func=execute)
