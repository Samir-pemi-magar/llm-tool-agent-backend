"""
    The only file in this codebase that imports `docker`.

    Everything above this (manager.py, tools/) talks in terms of ExecutionJob
    and gets back a plain dict. If we ever swap Docker for something else,
    this is the only file that changes.
"""

import json
import docker
from docker.errors import ContainerError, ImageNotFound, APIError
from .models import ExecutionJob

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client

def run_job(job: ExecutionJob) -> dict:
    client = _get_client()

    volumes = {}
    if job.host_data_dir:
        volumes[job.host_data_dir] = {
            "bind": job.container_data_dir,
            "mode": "rw" if job.read_write else "ro",
        }

    # The image's ENTRYPOINT is ["python", "runner.py"]; we only pass args.
    command = [job.tool_name, json.dumps(job.args)]

    container = None
    try:
        container = client.containers.run(
            image=job.image,
            command=command,
            volumes=volumes,
            environment=job.extra_env,
            detach=True,
            network_disabled=job.network_disabled,
            mem_limit=job.memory_limit,
            nano_cpus=int(job.cpu_limit * 1_000_000_000),
            pids_limit=job.pids_limit,
            user="1000:1000",
            read_only=True,
            tmpfs={"/tmp": "size=32m"},
            security_opt=["no-new-privileges"],
            cap_drop=["ALL"],
        )

        try:
            result = container.wait(timeout=job.timeout_seconds)
            exit_code = result.get("StatusCode", 1)
        except Exception:
            container.kill()
            return {"error": "sandbox_timeout", "detail": f"Tool '{job.tool_name}' exceeded {job.timeout_seconds}s"}

        stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
        stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

        if exit_code != 0:
            return {"error": "sandbox_execution_failed", "detail": stderr.strip() or "unknown error", "exit_code": exit_code}

        try:
            return json.loads(stdout.strip())
        except json.JSONDecodeError:
            return {"error": "sandbox_bad_output", "detail": stdout.strip()}

    except ImageNotFound:
        return {"error": "sandbox_image_missing", "detail": f"Image '{job.image}' not found. Build it first."}
    except (ContainerError, APIError) as e:
        return {"error": "sandbox_error", "detail": str(e)}
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass