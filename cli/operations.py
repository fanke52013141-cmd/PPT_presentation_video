"""Exact operation commands; all business calls use the dynamic client."""

import json

from agent_client.client import AgentClient
from agent_client.polling import PollConfig, wait_operation


def execute(args):
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    if args.action == "list":
        result = client.list_operations(args.project, offset=args.offset, limit=args.limit)
    elif args.action == "get":
        result = client.get_operation(args.project, args.operation_id)
    elif args.action == "cancel":
        result = client.cancel_operation(args.project, args.operation_id,
                                         expected_contract_revision=args.contract_revision)
    else:
        result = wait_operation(client, args.project, args.operation_id, PollConfig(timeout=args.timeout, interval=args.interval))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def add_commands(subparsers):
    parser = subparsers.add_parser("operation", help="Query and control exact persistent operations")
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("get", "list", "cancel", "wait"):
        command = actions.add_parser(name)
        command.add_argument("--project", required=True)
        if name != "list":
            command.add_argument("--operation-id", required=True)
        else:
            command.add_argument("--offset", type=int, default=0)
            command.add_argument("--limit", type=int, default=50)
        if name == "cancel":
            command.add_argument("--contract-revision", required=True)
        if name == "wait":
            command.add_argument("--timeout", type=int, default=300)
            command.add_argument("--interval", type=int, default=5)
        command.set_defaults(func=execute)
