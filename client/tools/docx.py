"""
    This file never touches python-docx or the filesystem directly.
    It only defines what the LLM is allowed to call (SCHEMAS) and forwards
    the actual work to the sandbox. All execution, path validation, and
    resource limits live in client/sandbox/.
"""
from sandbox import execute_tool


def read_docx_text(file_path: str) -> dict:
    return execute_tool("read_docx_text", {"file_path": file_path})


def get_docx_tables(file_path: str) -> dict:
    return execute_tool("get_docx_tables", {"file_path": file_path})


def find_and_replace_text(file_path: str, find: str, replace: str) -> dict:
    return execute_tool("find_and_replace_text", {"file_path": file_path, "find": find, "replace": replace})


SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_docx_text",
            "description": "Extract all paragraph text from a Word document",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the .docx file"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_docx_tables",
            "description": "Extract all tables from a Word document as rows of cell text",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the .docx file"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_and_replace_text",
            "description": "Find a piece of text in a Word document and replace it, then save the document",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the .docx file"},
                    "find": {"type": "string", "description": "Exact text to find"},
                    "replace": {"type": "string", "description": "Text to replace it with"},
                },
                "required": ["file_path", "find", "replace"],
            },
        },
    },
]

REGISTRY = {
    "read_docx_text": read_docx_text,
    "get_docx_tables": get_docx_tables,
    "find_and_replace_text": find_and_replace_text,
}