"""One entry point for everything the pipeline produces.

    python -m codegeneration client [provider ...]        generate HTTP clients
    python -m codegeneration operations <provider> [--all]        the connector's operations
    python -m codegeneration contract <provider> <opId>   one endpoint, self-contained
    python -m codegeneration check <provider>             enforce the mapper rules

`contract` feeds an LLM writing a mapper: one operation, every reference inlined,
from the vendored OpenAPI. Terminals show YAML; redirected output stays compact JSON.
"""

from __future__ import annotations

import sys

from codegeneration import (
    check_connector,
    generate_client,
    generate_context,
)

COMMANDS = ("client", "operations", "contract", "check")

USAGE = """usage:
  python -m codegeneration client [provider ...]
  python -m codegeneration operations <provider> [--all]
  python -m codegeneration contract <provider> <operationId> [input | response <status>] [--yaml | --json]
  python -m codegeneration check <provider> [vertical]
"""


def main(argv: list[str] | None = None) -> None:
    """Dispatch one subcommand, defaulting to client generation."""
    args = list(argv if argv is not None else sys.argv[1:])
    command = args.pop(0) if args and args[0] in COMMANDS else "client"

    if command == "client":
        generate_client.main(args)
    elif command == "operations":
        generate_context.list_operations(args)
    elif command == "contract":
        generate_context.main(args)
    elif command == "check":
        check_connector.main(args)
    else:  # pragma: no cover
        raise SystemExit(USAGE)


if __name__ == "__main__":
    main()
