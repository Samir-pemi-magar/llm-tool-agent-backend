"""
This tool is intentionally NOT routed through sandbox.execute_tool().

The Excel/PDF/DOCX tools run inside network-disabled, secret-free sandbox
containers (see client/sandbox/) -- that's the right place for untrusted
file parsing, but it's the wrong place for sending email: SMTP needs a
real network connection and real credentials, and we don't want those
sitting inside a container whose whole design point is "has neither."

So this file talks to SMTP directly from the trusted app process, using
credentials that only ever live in this process's environment.

Two safety nets on top of "just send the email":
  1. RECIPIENT ALLOWLIST -- the model can only send to addresses/domains
     an operator has explicitly approved (env var below). Without this,
     an LLM-driven "send email" tool is a spam/exfiltration primitive
     that fires on tone alone.
  2. ATTACHMENTS must already live in SANDBOX_DATA_DIR (the same shared
     folder create_pdf_from_data / update_excel_data write to), so this
     can't be repointed at arbitrary files on disk.
"""

import os
import re
import smtplib
from email.message import EmailMessage

DATA_DIR = os.environ.get("SANDBOX_DATA_DIR", "/app/data")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USERNAME)

# Comma-separated list of exact addresses ("alice@acme.com") and/or bare
# domains ("@acme.com") the agent is allowed to send to. Empty = nothing
# is allowed, on purpose: an operator has to opt in.
#   ALLOWED_EMAIL_RECIPIENTS="alice@acme.com,bob@acme.com,@acme.com"
_ALLOWLIST = [
    entry.strip().lower()
    for entry in os.environ.get("ALLOWED_EMAIL_RECIPIENTS", "").split(",")
    if entry.strip()
]

# Optional name -> email aliases, so the model can say "sam" instead of
# retyping a full address in every tool call. Small local models are
# prone to mangling long digit/character sequences when generating tool
# arguments (e.g. turning "pemi99" into "pemisi99") -- aliases remove
# that failure mode entirely since the address is looked up, not typed.
#   EMAIL_CONTACTS="sam:samirpemimagar@gmail.com,sam2:samirpemi99@gmail.com"
_CONTACTS = {}
for _entry in os.environ.get("EMAIL_CONTACTS", "").split(","):
    _entry = _entry.strip()
    if not _entry or ":" not in _entry:
        continue
    _name, _addr = _entry.split(":", 1)
    _CONTACTS[_name.strip().lower()] = _addr.strip().lower()


def _resolve(address: str) -> str:
    """Map a known contact name to its real address; pass through anything else."""
    return _CONTACTS.get(address.strip().lower(), address)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_allowed(address: str) -> bool:
    address = address.lower().strip()
    if address in _ALLOWLIST:
        return True
    domain = "@" + address.split("@")[-1]
    return domain in _ALLOWLIST


def send_email(
    to: list[str],
    subject: str,
    body: str,
    attachment_filename: str | None = None,
) -> dict:
    """
    Send a plain-text email to one or more recipients, optionally
    attaching a file that already exists in the shared data directory
    (e.g. a PDF just built with create_pdf_from_data).
    """
    if not SMTP_HOST or not SMTP_USERNAME or not SMTP_PASSWORD:
        return {
            "error": "email_not_configured",
            "detail": (
                "SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD are not set "
                "in the app environment."
            ),
        }

    if not to:
        return {"error": "no_recipients"}

    to = [_resolve(addr) for addr in to]

    invalid = [addr for addr in to if not _EMAIL_RE.match(addr)]
    if invalid:
        return {"error": "invalid_recipients", "detail": invalid}

    not_allowed = [addr for addr in to if not _is_allowed(addr)]
    if not_allowed:
        return {
            "error": "recipient_not_allowed",
            "detail": (
                f"{not_allowed} are not on ALLOWED_EMAIL_RECIPIENTS. "
                "Ask an operator to add them."
            ),
        }

    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)

    if attachment_filename:
        safe_name = os.path.basename(attachment_filename)
        candidates = (
            os.path.join(DATA_DIR, "generated", safe_name),
            os.path.join(DATA_DIR, safe_name),
        )
        path = next((p for p in candidates if os.path.isfile(p)), None)
        if path is None:
            return {"error": "attachment_not_found", "detail": safe_name}
        with open(path, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="application",
                subtype="octet-stream",
                filename=safe_name,
            )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
    except smtplib.SMTPException as e:
        return {"error": "smtp_error", "detail": str(e)}
    except OSError as e:
        return {"error": "connection_error", "detail": str(e)}

    return {"sent": True, "to": to, "subject": subject}


SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": (
                "Send an email to one or more specific, pre-approved "
                "recipients. Use this when the user asks to email, send, "
                "or share a file or piece of information with named "
                "people. If the user refers to a recipient by a short "
                "name (e.g. 'sam', 'sam2') that matches a configured "
                "contact, pass that name as-is in 'to' rather than typing "
                "out a full email address -- it will be resolved "
                "automatically. If a PDF/Excel/Word file was just created "
                "for this conversation, pass its filename as "
                "attachment_filename to attach it. Recipients must be on "
                "the operator-approved allowlist -- if the tool returns "
                "recipient_not_allowed, tell the user that address isn't "
                "approved rather than retrying."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Recipient email addresses.",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Plain-text email body.",
                    },
                    "attachment_filename": {
                        "type": "string",
                        "description": (
                            "Optional. Filename only (not a full path) of "
                            "a file already in the shared data directory, "
                            "e.g. 'mercedes_models.pdf'."
                        ),
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
]

REGISTRY = {
    "send_email": send_email,
}