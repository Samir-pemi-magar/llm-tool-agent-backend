from dataclasses import dataclass, field

@dataclass
class ExecutionJob:
    """
    A single Request to run one tool call inside an isolated container
    The Sandbox layer only  ever deals in execution job. it doesn`t know or care that this happens to be an `excel tool`.
    Adding a new Sandboxed tool family later means adding policy entry + a runner image, not touching this model.
    """
    tool_name: str
    args: dict
    image: str
    timeout_seconds: int
    memory_limit: str
    cpu_limit: float
    pids_limit: int
    host_data_dir: str | None = None
    container_data_dir: str = "/workspace/data"
    read_write: bool = False
    network_disabled: bool = True
    extra_env: dict = field(default_factory=dict)
    