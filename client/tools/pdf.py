"""
    This file never touches pypdf/reportlab or the filesystem directly.
    It only defines what the LLM is allowed to call (SCHEMAS) and forwards
    the actual work to the sandbox. All execution, path validation, and
    resource limits live in client/sandbox/.
"""
import os

from sandbox import execute_tool

# Browser-accessible file server -- same env var server.py uses to build
# the /files/{filename} route. Read here too so create_pdf_from_data can
# hand the model back a real, clickable download link instead of the
# internal sandbox path.
FILE_SERVER_URL = os.environ.get("FILE_SERVER_URL", "http://localhost:8000")

DATA_DIR = os.environ.get("SANDBOX_DATA_DIR", "/app/data")

# Generated PDFs live in their own subfolder, deliberately kept OUT of
# DATA_DIR's top level. server.py's system prompt lists every top-level
# file in DATA_DIR as "available data" on every turn -- if generated
# outputs sat alongside the source spreadsheets, each new PDF you create
# adds one more candidate file for the model to (mis)pick when answering
# an unrelated question later in the same conversation. Keeping outputs
# in a subfolder means os.listdir(DATA_DIR) never sees them.
GENERATED_DIR = os.path.join(DATA_DIR, "generated")
os.makedirs(GENERATED_DIR, exist_ok=True)


def read_pdf_text(file_path: str, page_number: int | None = None) -> dict:
    return execute_tool("read_pdf_text", {"file_path": file_path, "page_number": page_number})


def get_pdf_metadata(file_path: str) -> dict:
    return execute_tool("get_pdf_metadata", {"file_path": file_path})


def search_pdf_text(file_path: str, query: str) -> dict:
    return execute_tool("search_pdf_text", {"file_path": file_path, "query": query})


def create_pdf_from_data(data: list[dict], output_path: str, title: str | None = None) -> dict:
    # Ignore whatever directory the model included in output_path -- only
    # the filename matters. This guarantees every generated PDF lands in
    # GENERATED_DIR regardless of what the model guesses, so it never
    # ends up back in the "available data files" list.
    filename = os.path.basename(output_path) or "output.pdf"
    forced_path = os.path.join(GENERATED_DIR, filename)

    result = execute_tool(
        "create_pdf_from_data",
        {"data": data, "output_path": forced_path, "title": title},
    )
    # The sandbox only knows the internal path it wrote to (e.g.
    # /app/data/generated/mercedes_models.pdf). Turn that into the URL
    # the user's browser can actually hit, via the /files/{filename}
    # route in server.py, so the model has something real to hand back
    # instead of just repeating the internal path.
    if isinstance(result, dict) and result.get("created"):
        result["download_url"] = f"{FILE_SERVER_URL}/files/{filename}"
    return result


SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_pdf_text",
            "description": "Extract text from a PDF file, either a single page or all pages",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the .pdf file"},
                    "page_number": {"type": "integer", "description": "Optional 1-indexed page number; omit to extract all pages"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pdf_metadata",
            "description": "Read metadata (title, author, subject, creator, page count) from a PDF file",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the .pdf file"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_pdf_text",
            "description": "Search a PDF for pages containing a given text query",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the .pdf file"},
                    "query": {"type": "string", "description": "Text to search for"},
                },
                "required": ["file_path", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_pdf_from_data",
            "description": (
                "Render a list of flat records into a table PDF. The "
                "result includes a 'download_url' field -- always give "
                "the user THAT link, never the raw output_path/created "
                "path, since the internal sandbox path isn't reachable "
                "from their browser."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of records (dicts) to render as table rows",
                    },
                    "output_path": {
                        "type": "string",
                        "description": (
                            "Filename for the generated PDF, e.g. "
                            "'vehicles_sold.pdf'. Just a name -- it is "
                            "always saved to the shared output location "
                            "regardless of any path given."
                        ),
                    },
                    "title": {"type": "string", "description": "Optional title shown at the top of the PDF"},
                },
                "required": ["data", "output_path"],
            },
        },
    },
]

REGISTRY = {
    "read_pdf_text": read_pdf_text,
    "get_pdf_metadata": get_pdf_metadata,
    "search_pdf_text": search_pdf_text,
    "create_pdf_from_data": create_pdf_from_data,
}