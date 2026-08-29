"""
    Generic sandbox entrypoint: `python runner.py <tool_name> <json_args>`

    Contract with the host side (sandbox/docker_runtime.py):
    - stdout gets EXACTLY ONE line of JSON: the result. Nothing else may be
    printed to stdout, or the host's json.loads will break.
    - Any diagnostic info goes to stderr.
    - Exit code 0 on success. Non-zero + stderr message on failure.
"""

import sys
import json
from excel_ops import REGISTRY as EXCEL_REGISTRY
from pdf_ops import REGISTRY as PDF_REGISTRY
from docx_ops import REGISTRY as DOCX_REGISTRY

REGISTRY = {**EXCEL_REGISTRY, **PDF_REGISTRY, **DOCX_REGISTRY}


def main():
    if len(sys.argv) != 3:
        print("usage: runner.py <tool_name> <json_args>", file=sys.stderr)
        sys.exit(1)

    tool_name, raw_args = sys.argv[1], sys.argv[2]
    fn = REGISTRY.get(tool_name)
    if fn is None:
        print(f"unknown tool: {tool_name}", file=sys.stderr)
        sys.exit(1)

    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as e:
        print(f"invalid json args: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        result = fn(**args)
    except Exception as e:
        result = {"error": str(e)}

    print(json.dumps(result))


if __name__ == "__main__":
    main()