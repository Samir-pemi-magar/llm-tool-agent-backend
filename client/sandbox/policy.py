"""
    Central Place for "what this tool is allowed to do.
    Nothing outside this file should decide the resource limits or read/write access.
    if you need a new sandbox tool, add a profile here.
    don`t scatter limit/permissions into tool code or the runtime.
"""

SandBOX_IMAGE = "sandbox-excel:latest"

DEFAULT_PROFILE = {
    "image": SandBOX_IMAGE,
    "timeout_seconds": 15,
    "memory_limit": "256m",
    "cpu_limit": 0.5,
    "pids_limit": 32,
    "read_write": False
}

TOOL_PROFILES = {
    "list_sheets": {},
    "read_excel_data": {},
    "summarize_column": {},
    "get_rows_by_value": {},
    "update_excel_data": {
        "read_write": True,
        "timeout_seconds": 10,
    },
    "append_row_data": {
        "read_write": True,
        "timeout_seconds": 10,
    },
    "read_pdf_text": {},
    "get_pdf_metadata": {},
    "search_pdf_text": {},
    "create_pdf_from_data": {
        "read_write": True,
        "timeout_seconds": 10,
    },
    "read_docx_text": {},
    "get_docx_tables": {},
    "find_and_replace_text": {
        "read_write": True,
        "timeout_seconds": 10,
    },
}

def get_profile(tool_name: str) ->dict:
    if tool_name not in TOOL_PROFILES:
        raise ValueError(f"No sandbox policy definded for tool '{tool_name}'")
    profile = dict(DEFAULT_PROFILE)
    profile.update(TOOL_PROFILES[tool_name])
    return profile