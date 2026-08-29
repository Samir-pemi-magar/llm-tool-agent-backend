import asyncio
import json
import re

import httpx

from tools import TOOLS_SCHEMA, TOOL_REGISTRY

from .config import (
    ACTION_TOOLS,
    MAX_TOOL_ROUNDS,
    MODEL_NAME,
    REQUEST_TIMEOUT,
    SGLANG_RETRY_DELAYS,
    SGLANG_URL,
)
from .sglang_quirks import recover_stray_tool_call, strip_reasoning, trim_for_context
from .system_prompt import build_system_prompt

CONTEXT_TOO_LARGE_MESSAGE = (
    "This conversation (plus the data I pulled in) got too large for me to "
    "process in one go. Could you start a new chat, or ask a narrower "
    "question — e.g. use get_rows_by_value or summarize_column instead of "
    "reading a whole sheet?"
)

# Catches phrasing like "I'll send", "I will email", "sending it now",
# "I've sent", "the email has been sent", "I will generate the PDF" --
# the model narrating an action tool as already done/in progress/about to
# happen without having actually called it. Checks both word orders since
# the verb can land before or after the confirmation phrase. Includes
# file-creation verbs (generate/create/etc.) alongside send/email/mail
# because create_pdf_from_data is just as much a "did this really happen"
# tool as send_email is -- a small model narrating "I will generate the
# PDF" instead of calling the tool is the exact same failure mode.
# Deliberately narrow: this only needs to catch confident
# false-confirmations, not every mention of these words, so a false
# positive just costs one extra model round.
_CONFIRM_WORDS = r"(i'll|i will|i've|i have|sending|sent|has been sent)"
_ACTION_WORDS = r"(send|email|mail|generate|create|build|produce|export|save)"
_FALSE_CONFIRMATION_RE = re.compile(
    rf"\b{_CONFIRM_WORDS}\b.{{0,40}}\b{_ACTION_WORDS}\b"
    rf"|\b{_ACTION_WORDS}\b.{{0,40}}\b{_CONFIRM_WORDS}\b",
    re.IGNORECASE,
)

# Catches the model fabricating a fake deliverable instead of calling a
# tool: placeholder download links, template comments, or a "click here"
# link that doesn't point at our real file server. These strings have no
# legitimate reason to ever appear in a real answer -- create_pdf_from_data
# always returns a concrete https://.../files/{filename} URL, never a
# comment telling *itself* to fill one in later. Unlike
# _FALSE_CONFIRMATION_RE, this doesn't require a specific tense/phrasing
# match, since a fabricated placeholder is unambiguous on its own.
_FAKE_DELIVERABLE_RE = re.compile(
    r"<!--.*?-->"
    r"|replace (this |it )?with the actual"
    r"|\[?download (pdf|file|it) here\]?"
    r"|\(url will be\)"
    r"|\(link (goes|to be) here\)",
    re.IGNORECASE | re.DOTALL,
)

# Tool names where a false "I did X" narration is worth catching. These
# are the tools with real, user-visible side effects -- if the model
# claims one of these happened, we need proof (an actual successful call
# already made in this run), not just confident phrasing. Read-only tools
# (read_excel_data, list_sheets, etc.) are deliberately excluded: their
# success doesn't make a claim about send_email/create_pdf_from_data any
# more truthful.
_SIDE_EFFECT_TOOLS = {
    "send_email",
    "create_pdf_from_data",
    "update_excel_data",
    "append_row_data",
    "find_and_replace_text",
}


async def run_agent_loop(messages: list[dict]) -> str:
    """
    The actual agent: talks to sglang, executes tool calls in the sandbox,
    feeds results back, repeats until the model gives a final answer or
    MAX_TOOL_ROUNDS is hit.

    Shared by both /chat and the OpenAI-compatible endpoint so there's
    exactly one place this logic lives.
    """
    # Rebuilt per request so newly added files in DATA_DIR show up without
    # needing to restart the app container.
    messages = [build_system_prompt()] + messages

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        # Belt-and-suspenders on top of the post-hoc hallucination checks
        # below: a 1.7B model is unreliable enough that it will sometimes
        # narrate a full "Step 1 / Step 2 / Step 3" plan in prose -- with
        # zero tool_calls -- for a request that's clearly asking it to DO
        # something (generate/send a file), rather than describe how it
        # would. If the request looks action-oriented, don't give it the
        # option to just talk; force a real tool call on the first round.
        forced_tool_choice = "required" if _looks_like_action_request(messages) else None
        # Names of side-effecting tools that have already succeeded for
        # real in this run. Once a tool is in here, the model reporting
        # that action as done is a truthful summary, not a hallucination
        # -- don't force yet another (real, duplicate!) call of it.
        completed_side_effects: set[str] = set()

        for _ in range(MAX_TOOL_ROUNDS):
            message, choice, error = await _call_model(
                client, messages, tool_choice=forced_tool_choice
            )
            forced_tool_choice = None
            if error:
                return error

            tool_calls = _extract_tool_calls(message)

            if not tool_calls:
                content = strip_reasoning(message).get("content", "") or ""
                print(
                    "[agent] no tool call; model answered directly: "
                    f"{content[:200]!r}"
                )

                if not content.strip():
                    # Empty content usually means the accumulated context
                    # left little/no room in max_tokens for an actual
                    # answer (often paired with finish_reason == "length"),
                    # rather than the model genuinely having nothing to
                    # say. Fail soft instead of silently returning "".
                    print(
                        "[agent] empty completion content "
                        f"(finish_reason={choice.get('finish_reason')!r})"
                    )
                    return CONTEXT_TOO_LARGE_MESSAGE

                unverified_confirmation = (
                    _looks_like_false_confirmation(content)
                    and not completed_side_effects
                )
                if unverified_confirmation or _FAKE_DELIVERABLE_RE.search(content):
                    # The model just claimed to have done something (e.g.
                    # "I'll send the PDF to...", "I will generate the
                    # PDF...") or fabricated a placeholder link/comment,
                    # and no side-effecting tool has actually succeeded
                    # yet this run to back that claim up. Don't relay it
                    # to the user -- re-prompt once, forcing a real tool
                    # call, instead of returning an unbacked confirmation.
                    #
                    # If completed_side_effects is non-empty, we skip this
                    # branch entirely and fall through to `return content`
                    # below -- the model already did the thing for real,
                    # so it reporting that truthfully is not a
                    # hallucination, and forcing another round would just
                    # trigger a duplicate real send/write.
                    print(
                        "[agent] discarding false confirmation / fake "
                        f"deliverable, forcing a real tool call: {content[:200]!r}"
                    )
                    forced_tool_choice = "required"
                    continue

                return content

            messages.append(strip_reasoning(message))
            completed_side_effects |= await _run_tool_calls(tool_calls, messages)
            # Loop again with the tool results appended.

    return "Sorry, I couldn't complete that after several tool calls."


_ACTION_REQUEST_RE = re.compile(
    r"\b(send|email|mail)\b.{0,60}\b(pdf|file|excel|spreadsheet|document|docx|report)\b"
    r"|\b(pdf|file|excel|spreadsheet|document|docx|report)\b.{0,60}\b(send|email|mail)\b"
    r"|\b(generate|create|make|build|export)\b.{0,40}\b(pdf|report|file|document)\b",
    re.IGNORECASE,
)


def _looks_like_action_request(messages: list[dict]) -> bool:
    """True if the most recent user message is clearly asking for a file
    to be created and/or sent, as opposed to just a question. Only looks
    at the latest user turn -- forcing tool_choice on every round of a
    multi-round conversation would prevent the model from ever giving a
    plain-text final answer."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "") or ""
        if not isinstance(content, str):
            return False
        return bool(_ACTION_REQUEST_RE.search(content))
    return False


def _looks_like_false_confirmation(content: str) -> bool:
    if not _FALSE_CONFIRMATION_RE.search(content):
        return False
    # Only worth forcing a retry if an action tool (send_email, etc.) is
    # actually available this turn -- otherwise "required" would just
    # force some unrelated tool call.
    return bool(ACTION_TOOLS)


async def _call_model(
    client: httpx.AsyncClient, messages: list[dict], tool_choice: str | None = None
):
    """POST the current conversation to sglang. Returns (message, choice,
    error_text). error_text is set (and message/choice are None) if the
    call failed in a way that should short-circuit the loop.

    Retries a couple of times, with backoff, on connection errors -- these
    are almost always sglang mid-restart after a crash (see
    SGLANG_RETRY_DELAYS), not a permanent failure, and a real restart
    takes 15-20s to reload the model."""
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 3000,
        "tools": TOOLS_SCHEMA,
        # Qwen3's "thinking" mode emits a <think>...</think> block of
        # chain-of-thought before every tool call and every answer. For a
        # job this structured (pick a tool, pass args, or give a short
        # answer), that reasoning adds little and is the single biggest
        # driver of context blowup: it gets stored in `messages` and
        # resent in full on every remaining round of this loop. Disabling
        # it keeps each round small enough that MAX_TOOL_ROUNDS worth of
        # history actually fits in the model's 32K context.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if tool_choice:
        payload["tool_choice"] = tool_choice

    delays = [0.0] + SGLANG_RETRY_DELAYS
    last_error = None

    for attempt, delay in enumerate(delays):
        if delay:
            print(
                f"[agent] sglang unreachable, retrying in {delay}s "
                f"(attempt {attempt + 1}/{len(delays)})"
            )
            await asyncio.sleep(delay)

        try:
            response = await client.post(
                f"{SGLANG_URL}/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = e.response.text
            print(f"[agent] sglang returned {e.response.status_code}: {body[:300]}")

            if e.response.status_code == 400 and "maximum allowed length" in body:
                # The conversation + tool results grew past sglang's context
                # window. Fail soft instead of raising, so the client gets a
                # real JSON response instead of a bare 500/traceback.
                return None, None, CONTEXT_TOO_LARGE_MESSAGE

            # Not a connection issue -- retrying won't help, fail now.
            return None, None, (
                "Something went wrong talking to the model backend "
                f"(HTTP {e.response.status_code}). Please try again."
            )
        except httpx.RequestError as e:
            print(f"[agent] request to sglang failed: {e!r}")
            last_error = e
            continue

        data = response.json()
        choice = data["choices"][0]
        return choice["message"], choice, None

    print(f"[agent] sglang still unreachable after {len(delays)} attempts: {last_error!r}")
    return None, None, "Couldn't reach the model backend. Please try again in a moment."


def _extract_tool_calls(message: dict) -> list[dict] | None:
    """Pull tool_calls off the model message, recovering a stray
    <tool_call> text block if sglang's parser failed to structure it (see
    sglang_quirks.recover_stray_tool_call)."""
    tool_calls = message.get("tool_calls")
    if tool_calls:
        return tool_calls

    content = strip_reasoning(message).get("content", "") or ""
    recovered = recover_stray_tool_call(content)
    if recovered:
        print(
            "[agent] recovered a stray tool_call that sglang's parser "
            f"missed: {recovered[0]['function']}"
        )
        message["content"] = None
        message["tool_calls"] = recovered
        return recovered

    return None


async def _run_tool_calls(tool_calls: list[dict], messages: list[dict]) -> set[str]:
    """Execute each requested tool call and append its result as a `tool`
    message, mutating `messages` in place. Returns the names of any
    _SIDE_EFFECT_TOOLS that completed without an "error" key this round,
    so the caller can tell a truthful "I sent it" apart from a
    hallucinated one on the next round."""
    succeeded: set[str] = set()

    for call in tool_calls:
        fn_name = call["function"]["name"]

        try:
            fn_args = json.loads(call["function"]["arguments"])
        except json.JSONDecodeError as e:
            print(
                f"[agent] malformed tool arguments for {fn_name}: "
                f"{call['function']['arguments']!r} ({e})"
            )
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps({
                    "error": "invalid_arguments",
                    "detail": (
                        f"Arguments for {fn_name} were not valid JSON: {e}. "
                        "Re-call the tool with corrected arguments."
                    ),
                }),
            })
            continue

        fn = TOOL_REGISTRY.get(fn_name)
        print(f"[agent] tool call: {fn_name}({fn_args})")

        if fn is None:
            result = {"error": f"Unknown tool: {fn_name}"}
        else:
            try:
                # Tool calls can launch sandbox containers and may take
                # real wall-clock time. Run them outside the event loop.
                result = await asyncio.to_thread(fn, **fn_args)
            except TypeError as e:
                # Model passed wrong/missing arg names for the tool's
                # signature -- surface it instead of a 500.
                result = {
                    "error": "invalid_arguments",
                    "detail": (
                        f"{fn_name} was called with bad arguments: {e}. "
                        "Re-call with the correct parameters."
                    ),
                }

        print(f"[agent] tool result: {json.dumps(result)[:500]}")

        if (
            fn_name in _SIDE_EFFECT_TOOLS
            and isinstance(result, dict)
            and "error" not in result
        ):
            succeeded.add(fn_name)

        messages.append({
            "role": "tool",
            "tool_call_id": call["id"],
            "content": trim_for_context(json.dumps(result)),
        })

    return succeeded