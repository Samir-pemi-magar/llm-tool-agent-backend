"""
Excel tool definitions for the LLM.

This file does not touch openpyxl or the filesystem directly.
It defines the tools the LLM may call and forwards execution to
the sandbox.

All actual Excel work, path validation, and resource limits happen
inside client/sandbox/.
"""

from sandbox import execute_tool


def list_sheets(file_path: str) -> dict:
    return execute_tool(
        "list_sheets",
        {
            "file_path": file_path,
        },
    )


def read_excel_data(file_path: str, sheet_name: str) -> dict:
    return execute_tool(
        "read_excel_data",
        {
            "file_path": file_path,
            "sheet_name": sheet_name,
        },
    )


def update_excel_data(
    file_path: str,
    cell: str,
    value: str,
    sheet_name: str,
) -> dict:
    return execute_tool(
        "update_excel_data",
        {
            "file_path": file_path,
            "cell": cell,
            "value": value,
            "sheet_name": sheet_name,
        },
    )


def append_row_data(
    file_path: str,
    row_data: dict,
    sheet_name: str,
) -> dict:
    return execute_tool(
        "append_row_data",
        {
            "file_path": file_path,
            "row_data": row_data,
            "sheet_name": sheet_name,
        },
    )


def summarize_column(
    file_path: str,
    column: str,
    operation: str,
    sheet_name: str,
) -> dict:
    return execute_tool(
        "summarize_column",
        {
            "file_path": file_path,
            "column": column,
            "operation": operation,
            "sheet_name": sheet_name,
        },
    )


def get_rows_by_value(
    file_path: str,
    column: str,
    values: list[str],
    sheet_name: str,
) -> dict:
    return execute_tool(
        "get_rows_by_value",
        {
            "file_path": file_path,
            "column": column,
            "values": values,
            "sheet_name": sheet_name,
        },
    )


SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_sheets",
            "description": (
                "List every sheet in an Excel workbook and identify the active "
                "sheet. Call this first when working with a workbook unless the "
                "correct sheet has already been explicitly established during "
                "the current task."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the .xlsx file",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_excel_data",
            "description": (
                "Read data from one specific Excel worksheet. Always pass the "
                "exact sheet_name. Use this to inspect a sheet's actual headers "
                "before constructing row_data for a new record or when the full "
                "sheet contents are needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the .xlsx file",
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": (
                            "Exact worksheet name. Required. Never rely on the "
                            "workbook's active/default sheet."
                        ),
                    },
                },
                "required": ["file_path", "sheet_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_excel_data",
            "description": (
                "Edit one specific cell in an existing row and save the workbook. "
                "Use this only when the exact target cell is known and the row "
                "already exists. Do not use this to create a new sale, entry, or "
                "record because it can overwrite existing data. Use "
                "append_row_data for new records. Always pass sheet_name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the .xlsx file",
                    },
                    "cell": {
                        "type": "string",
                        "description": "Exact cell reference, for example B2",
                    },
                    "value": {
                        "type": "string",
                        "description": "New value for the cell",
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": (
                            "Exact worksheet name. Required. Never rely on the "
                            "active/default sheet."
                        ),
                    },
                },
                "required": [
                    "file_path",
                    "cell",
                    "value",
                    "sheet_name",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_row_data",
            "description": (
                "Add a brand-new record to a specific worksheet. Use this when "
                "the user asks to add, log, or record something new. The "
                "sheet_name is required. row_data keys must exactly match the "
                "headers on that sheet. Inspect the destination sheet's headers "
                "before calling this tool. Do not append sales records to "
                "pricing, catalog, inventory, or reference sheets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the .xlsx file",
                    },
                    "row_data": {
                        "type": "object",
                        "description": (
                            "Mapping of exact worksheet column header names to "
                            "values. Only use headers that actually exist on the "
                            "selected sheet. Example: "
                            "{'Sale Date': '2026-08-28', "
                            "'Model Name': 'E 350 Sedan', "
                            "'Units Sold': 2, "
                            "'Sale Price/Unit (USD)': 53760}"
                        ),
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": (
                            "Exact destination worksheet name. Required. Never "
                            "rely on the workbook's active/default sheet."
                        ),
                    },
                },
                "required": [
                    "file_path",
                    "row_data",
                    "sheet_name",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_column",
            "description": (
                "Compute an exact summary statistic over a named column on one "
                "specific worksheet. Use this for totals, counts, averages, "
                "minimums, or maximums instead of manually estimating from raw "
                "rows. Always pass the exact sheet_name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the .xlsx file",
                    },
                    "column": {
                        "type": "string",
                        "description": (
                            "Exact column header name, for example 'Units Sold'"
                        ),
                    },
                    "operation": {
                        "type": "string",
                        "enum": [
                            "sum",
                            "count",
                            "average",
                            "min",
                            "max",
                        ],
                        "description": "The summary operation to perform",
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": (
                            "Exact worksheet name. Required. Never rely on the "
                            "active/default sheet."
                        ),
                    },
                },
                "required": [
                    "file_path",
                    "column",
                    "operation",
                    "sheet_name",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rows_by_value",
            "description": (
                "Fetch rows from one specific worksheet where a named column "
                "matches one or more requested values. Use this for targeted "
                "lookups instead of reading an entire sheet. Always pass the "
                "exact sheet_name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the .xlsx file",
                    },
                    "column": {
                        "type": "string",
                        "description": (
                            "Exact column header to search, for example "
                            "'Model Name'"
                        ),
                    },
                    "values": {
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                        "description": (
                            "Values to search for, for example "
                            "['E 350 Sedan', 'GLC 300 SUV']"
                        ),
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": (
                            "Exact worksheet name. Required. Never rely on the "
                            "active/default sheet."
                        ),
                    },
                },
                "required": [
                    "file_path",
                    "column",
                    "values",
                    "sheet_name",
                ],
            },
        },
    },
]


REGISTRY = {
    "list_sheets": list_sheets,
    "read_excel_data": read_excel_data,
    "update_excel_data": update_excel_data,
    "append_row_data": append_row_data,
    "summarize_column": summarize_column,
    "get_rows_by_value": get_rows_by_value,
}