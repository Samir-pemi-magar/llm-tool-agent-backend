"""
    Sandbox Manager: The boundry between "tool code" and "container infra".
    
    tools/*.py should only ever call 'execute_tool(...)'.
    it should never build an ExecutionJob itself, never know about Volumes, and never touch docker_runtime directly
"""

import os
from . import policy
from .models import ExecutionJob
from .docker_runtime import run_job

ALLOWED_DATA_DIR = os.environ.get("SANDBOX_DATA_DIR", "/app/data") 
HOST_DATA_DIR = os.environ.get("SANDBOX_HOST_DATA_DIR", ALLOWED_DATA_DIR)

def _resolve_file_path(app_path: str) ->tuple[str,str]:
    """
    Validate the app_path (as seen inside the container) lives under ALLOWED_DATA_DIR, then returns:
    -host_dir_to_mount: the equivalent host path, for the docker daemon
    -container_path: the path the tool code will see inside the sandbox
    """
    real_allowed = os.path.realpath(ALLOWED_DATA_DIR)
    real_path = os.path.realpath(app_path)
    
    if os.path.commonpath([real_allowed,real_path]) != real_allowed:
        raise PermissionError(
            f"`{app_path}` is outside the allowed data directory ({ALLOWED_DATA_DIR})"
        )
    if not os.path.isfile(real_path):
        raise FileNotFoundError(app_path)
    
    relative = os.path.relpath(real_path,real_allowed)
    host_file_path = os.path.join(HOST_DATA_DIR, relative)
    host_dir = os.path.dirname(host_file_path)
    
    filename = os.path.basename(real_path)
    container_dir = "/workspace/data"
    return host_dir, f"{container_dir}/{filename}"


def _resolve_output_path(app_path: str) -> tuple[str, str]:
    """
    Same as _resolve_file_path, but for a file the tool is about to CREATE --
    so unlike an input file_path, it's fine (expected) for it not to exist
    yet. Only the parent directory needs to already exist and live inside
    ALLOWED_DATA_DIR.
    """
    real_allowed = os.path.realpath(ALLOWED_DATA_DIR)
    real_path = os.path.realpath(app_path)

    if os.path.commonpath([real_allowed, real_path]) != real_allowed:
        raise PermissionError(
            f"`{app_path}` is outside the allowed data directory ({ALLOWED_DATA_DIR})"
        )

    parent = os.path.dirname(real_path)
    if not os.path.isdir(parent):
        raise FileNotFoundError(f"parent directory for `{app_path}` does not exist")

    relative = os.path.relpath(real_path, real_allowed)
    host_file_path = os.path.join(HOST_DATA_DIR, relative)
    host_dir = os.path.dirname(host_file_path)

    filename = os.path.basename(real_path)
    container_dir = "/workspace/data"
    return host_dir, f"{container_dir}/{filename}"


def execute_tool(tool_name: str, args: dict) -> dict:
    """
    Run one tool call inside an isolated, ephemeral container and return
    its JSON result. This is the only function tools/excel.py should call.
    """
    try:
        profile = policy.get_profile(tool_name)
    except ValueError as e:
        return {"error": "unknown_tool", "detail": str(e)}

    args = dict(args)  # don't mutate the caller's dict
    host_data_dir = None

    if "file_path" in args and args["file_path"]:
        try:
            host_data_dir, container_path = _resolve_file_path(args["file_path"])
        except (PermissionError, FileNotFoundError) as e:
            return {"error": "invalid_file_path", "detail": str(e)}
        args["file_path"] = container_path

    if "output_path" in args and args["output_path"]:
        try:
            out_host_dir, out_container_path = _resolve_output_path(args["output_path"])
        except (PermissionError, FileNotFoundError) as e:
            return {"error": "invalid_output_path", "detail": str(e)}
        if host_data_dir is not None and out_host_dir != host_data_dir:
            return {
                "error": "unsupported_layout",
                "detail": "file_path and output_path must live in the same directory",
            }
        host_data_dir = out_host_dir
        args["output_path"] = out_container_path

    job = ExecutionJob(
        tool_name=tool_name,
        args=args,
        image=profile["image"],
        timeout_seconds=profile["timeout_seconds"],
        memory_limit=profile["memory_limit"],
        cpu_limit=profile["cpu_limit"],
        pids_limit=profile["pids_limit"],
        host_data_dir=host_data_dir,
        read_write=profile["read_write"],
    )

    return run_job(job)