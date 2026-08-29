import json
import os
import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from agent import run_agent_loop
from agent.config import DATA_DIR, PUBLIC_MODEL_ID
from schemas import ChatRequest

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Open WebUI runs as its own container/origin
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/files/{filename}")
async def get_file(filename: str):
    """
    Serve a generated file from the shared data directory.

    basename() prevents path traversal such as /files/../../etc/passwd.
    """
    safe_name = os.path.basename(filename)

    # Generated outputs (e.g. from create_pdf_from_data) live in a
    # subfolder kept separate from source data files -- check there first
    # since that's where every newly created download actually is.
    for base in (os.path.join(DATA_DIR, "generated"), DATA_DIR):
        path = os.path.join(base, safe_name)
        if os.path.isfile(path):
            return FileResponse(path, filename=safe_name)

    return {"error": "not_found", "detail": filename}


@app.post("/chat")
async def chat(request: ChatRequest):
    content = await run_agent_loop([m.model_dump() for m in request.messages])
    return {"response": content}


# ---------------------------------------------------------------------------
# OpenAI-compatible surface, so Open WebUI can add this server as a normal
# "OpenAI API" connection and use it like any other model. The tool-calling
# loop in agent/ stays completely hidden from Open WebUI -- it only ever
# receives the finished assistant message.
# ---------------------------------------------------------------------------

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": PUBLIC_MODEL_ID,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "local",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def openai_chat_completions(request: dict):
    incoming_messages = request.get("messages", [])

    # Only role/content matter to our loop; strip anything else the client sent.
    clean_messages = [
        {"role": m["role"], "content": m.get("content", "")}
        for m in incoming_messages
    ]

    content = await run_agent_loop(clean_messages)

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    if request.get("stream"):
        return StreamingResponse(
            _stream_completion(content, completion_id, created),
            media_type="text/event-stream",
        )

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": PUBLIC_MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


async def _stream_completion(content: str, completion_id: str, created: int):
    """Fake a one-shot SSE stream: our agent loop already ran to
    completion before this is called, so there's nothing to actually
    stream incrementally -- this just speaks the protocol Open WebUI
    expects for `stream: true`."""
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": PUBLIC_MODEL_ID,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": None,
            }
        ],
    }
    yield f"data: {json.dumps(chunk)}\n\n"

    final_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": PUBLIC_MODEL_ID,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"

    yield "data: [DONE]\n\n"