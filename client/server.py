import os
import json
import httpx

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from tools import TOOLS_SCHEMA, TOOL_REGISTRY

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001"],
    allow_methods=["*"],
    allow_headers=["*"],
    )
# Use the compose service name so this resolves inside the Docker network.
# Overridable via env var so it still works if you run this outside compose.
SGLANG_URL = os.environ.get("SGLANG_URL", "http://sglang:3000")

REQUEST_TIMEOUT = httpx.Timeout(120.0, connect=5.0)


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat(request: ChatRequest):
    FILE_PATH = "/app/data/Comprehensive Mercedes-Benz Models & Pricing Directory V2.xlsx"  # match your actual container path
    system_prompt = {
        "role": "system",
        "content": (
            f"You have access to an Excel database at '{FILE_PATH}'. "
            "Use get_rows_by_value to look up specific rows (e.g. specific model names) "
            "when comparing or answering about particular items, "
            "summarize_column for totals/averages/min/max, "
            "read_excel_data only when you need the entire sheet, "
            "and update_excel_data to write changes. "
            "Never guess values — always call a tool to get real data first."
        ),
    }
    messages = [system_prompt] + [m.model_dump() for m in request.messages]

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for _ in range(5):  # safety cap so it can't loop forever
            payload = {
                "model": "Qwen/Qwen3-1.7B",
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 3000,
                "tools": TOOLS_SCHEMA,
            }
            response = await client.post(f"{SGLANG_URL}/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]

            tool_calls = message.get("tool_calls")
            if not tool_calls:
                # normal answer, no tool needed — we're done
                return {"response": message["content"]}

            # model wants to call one or more tools
            messages.append(message)  # record the assistant's tool-call request

            for call in tool_calls:
                fn_name = call["function"]["name"]
                fn_args = json.loads(call["function"]["arguments"])
                fn = TOOL_REGISTRY.get(fn_name)

                if fn is None:
                    result = {"error": f"Unknown tool: {fn_name}"}
                else:
                    result = fn(**fn_args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result),
                })
            # loop again: send messages (now including tool results) back to sglang

    return {"response": "Sorry, I couldn't complete that after several tool calls."}