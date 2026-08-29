import os
import httpx

# Use the compose service name so this resolves inside the Docker network.
SGLANG_URL = os.environ.get("SGLANG_URL", "http://sglang:3000")
MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen/Qwen3-1.7B")

# The public-facing id Open WebUI will show in its model dropdown.
# Kept separate from MODEL_NAME so we're not leaking the underlying model name.
PUBLIC_MODEL_ID = os.environ.get("PUBLIC_MODEL_ID", "file-agent")

# Shared data directory inside the app container.
DATA_DIR = os.environ.get("SANDBOX_DATA_DIR", "/app/data")

# URL that the user's browser can access to download generated files.
FILE_SERVER_URL = os.environ.get("FILE_SERVER_URL", "http://localhost:8000")

REQUEST_TIMEOUT = httpx.Timeout(120.0, connect=5.0)
MAX_TOOL_ROUNDS = 5

# sglang occasionally crashes and auto-restarts (container restart policy
# handles the process; this just keeps a single user request from failing
# outright during that ~15-20s reload window). Delays are seconds to wait
# before each retry -- two attempts, backing off, rather than one fixed
# sleep, since a fresh crash needs longer than a slow request does.
SGLANG_RETRY_DELAYS = [5.0, 15.0]

# Tool names where the model completing a sentence like "I'll send that
# now" is NOT the same as the action having happened. If the model
# responds with prose that sounds like one of these already happened, but
# never actually emitted a tool_call, we re-prompt it once and force a
# real tool call instead of relaying the false confirmation to the user.
ACTION_TOOLS = {"send_email"}

# Cap how many characters of any single tool result we keep in the
# conversation history that gets resent to the model on every subsequent
# round. Tools like read_excel_data can return up to 200 rows; keeping that
# in full on every round is what blows out the context window. The model
# already saw the full result once (this turn) to reason about it -- it
# doesn't need it resent verbatim on every later round.
MAX_TOOL_RESULT_CHARS = 4000