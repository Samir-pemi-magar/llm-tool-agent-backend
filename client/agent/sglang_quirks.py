"""
Workarounds for a few quirks in how sglang serves small local models
(Qwen3 in particular). Kept together and named for what they patch over,
so it's obvious this file can shrink/disappear if the model server side
improves.
"""

import json
import re
import uuid

from .config import MAX_TOOL_RESULT_CHARS

_TOOL_CALL_OPEN_RE = re.compile(r"<tool_call>\s*(\{)")

# Matches a curly-brace "set literal" of bare scalars -- e.g.
# {"2023-10-05", "GLC 350e 4MATIC SUV", "3"} or {2026, 179700} -- with no
# colons anywhere inside. Small models sometimes emit this Python-set-like
# shape where a JSON array was intended (rows/headers as a bag of values
# instead of ["a", "b", "c"]). A real JSON object always has a colon after
# its first key, so this can't false-positive on a legitimate {"k": "v"}.
_SCALAR = r'(?:"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?|true|false|null)'
_SET_LITERAL_RE = re.compile(
    rf"\{{\s*({_SCALAR}(?:\s*,\s*{_SCALAR})*)\s*\}}"
)


def _find_balanced_json(text: str, start: int) -> str | None:
    """Return the substring from `start` (index of an opening '{') up to
    and including its matching closing '}', tracking string literals so
    braces inside quoted values don't throw off the depth count. Needed
    because the old lazy-regex approach (`\\{.*?\\}`) breaks on any
    nested object -- it stops at the *first* inner '}', truncating the
    JSON before it's complete."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None  # unbalanced -- output was truncated (e.g. hit max_tokens)


def strip_reasoning(message: dict) -> dict:
    """
    Defense in depth alongside `enable_thinking: False`. If sglang still
    attaches a `reasoning_content` field (e.g. thinking briefly re-enabled,
    or a future model/version that doesn't fully honor the flag), never let
    it ride along into `messages` -- it would otherwise get resent in full
    on every remaining round of the agent loop, which is exactly what blows
    out the context window. Qwen's own guidance is to never feed prior
    thinking blocks back in multi-turn conversations.

    Also belt-and-braces strips a literal <think>...</think> prefix from
    `content` in case a parser mismatch leaves it un-separated.
    """
    message = dict(message)
    message.pop("reasoning_content", None)

    content = message.get("content")
    if isinstance(content, str) and content.lstrip().startswith("<think>"):
        end = content.find("</think>")
        if end != -1:
            message["content"] = content[end + len("</think>"):].lstrip()

    return message


def trim_for_context(content: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Cap a tool result's size before it's stored in `messages`. Large
    results (e.g. a 200-row read_excel_data dump) otherwise get resent in
    full on every remaining round of the loop, which is what blows out the
    model's context window within a single request."""
    if len(content) <= max_chars:
        return content
    return (
        content[:max_chars]
        + f"... [truncated, {len(content) - max_chars} more characters omitted "
        "to stay within context limits -- use a narrower tool like "
        "get_rows_by_value or summarize_column for specific data instead of "
        "re-reading the whole result]"
    )


def recover_stray_tool_call(content: str) -> list[dict] | None:
    """
    Best-effort recovery for when sglang's tool-call parser fails to
    extract a structured tool_calls entry and one or more of the model's
    <tool_call>...</tool_call> blocks leak through as plain text content
    instead.

    Recovers *every* <tool_call> block found, not just the first -- a
    model asked to do two things (e.g. "make a PDF for X and a separate
    PDF for Y") will often emit two blocks back-to-back in one message,
    and only running the first one silently drops the second.

    Also repairs two common small-model JSON mistakes:
    - Python literals (None/True/False) where JSON requires
      (null/true/false).
    - A curly-brace "set literal" of bare values (e.g.
      {"a", "b", "c"}) where a JSON array ([...]) was intended --
      most often seen in fabricated row/header data.

    Returns a synthetic tool_calls list (matching the shape the rest of the
    loop expects) if at least one call could be recovered, else None.
    """
    recovered: list[dict] = []

    for open_match in _TOOL_CALL_OPEN_RE.finditer(content):
        raw = _find_balanced_json(content, open_match.start(1))
        if raw is None:
            continue

        repaired = re.sub(r"\bNone\b", "null", raw)
        repaired = re.sub(r"\bTrue\b", "true", repaired)
        repaired = re.sub(r"\bFalse\b", "false", repaired)
        repaired = _SET_LITERAL_RE.sub(r"[\1]", repaired)

        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError:
            continue

        name = parsed.get("name")
        arguments = parsed.get("arguments")
        if not name or arguments is None:
            continue

        recovered.append({
            "id": f"recovered-{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(arguments),
            },
        })

    return recovered or None