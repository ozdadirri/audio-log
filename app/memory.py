"""Long-term memory per user: new recording digests are folded into a rolling
markdown document by the LLM, so the assistant has cross-recording context."""

import logging

from . import db, summarize

log = logging.getLogger("audiolog")

BATCH = 5  # digests folded into the memory per LLM call

MEMORY_PROMPT = """You maintain the long-term memory document for a user's audio
recording library. Fold the new recording digests below into the existing memory.

Rules:
- Keep exactly these sections: ## Overview, ## Projects & topics,
  ## Decisions & actions, ## Recurring themes, ## Timeline highlights.
- Write about the user's own activities, topics, plans, and commitments.
  Do NOT keep profiles of other people; mention someone else only inside an
  action item or decision where they are essential.
- Merge with what is already there — update facts, don't duplicate them.
- Prefix timeline entries with their date (YYYY-MM-DD).
- Keep the whole document under about 800 words; drop the least important
  details first.
- Output ONLY the updated memory document in markdown, nothing else.

Existing memory:
{memory}

New digests:
{digests}"""

EMPTY = "(no memory yet)"


def status(user: dict) -> dict:
    row = db.get_memory(user["id"])
    pending = db.memory_pending(user, row["last_file_id"] if row else 0)
    return {
        "content": row["content"] if row else None,
        "content_zh": row.get("content_zh") if row else None,
        "updated_at": row["updated_at"] if row else None,
        "pending": len(pending),
    }


def translate(user: dict) -> str | None:
    """Chinese version of the memory, generated once per build and cached."""
    row = db.get_memory(user["id"])
    if not row or not row["content"]:
        return None
    if row.get("content_zh"):
        return row["content_zh"]
    zh = summarize.translate_zh(row["content"])
    db.set_memory_zh(user["id"], zh)
    return zh


def build(user: dict) -> dict:
    """Fold all pending digests into the user's memory, batch by batch."""
    row = db.get_memory(user["id"])
    content = row["content"] if row else EMPTY
    last_id = row["last_file_id"] if row else 0
    pending = db.memory_pending(user, last_id)
    for i in range(0, len(pending), BATCH):
        batch = pending[i:i + BATCH]
        digests = "\n\n".join(
            f"[{f['created_at'][:10]}] {f['title'] or f['filename']}\n{f['summary']}"
            for f in batch
        )
        content = summarize._ollama_chat(
            MEMORY_PROMPT.format(memory=content, digests=digests)).strip()
        last_id = batch[-1]["id"]
        db.set_memory(user["id"], content, last_id)  # checkpoint per batch
        log.info("memory for %s: folded %d digests (through file %d)",
                 user["username"], len(batch), last_id)
    return status(user)


def for_prompt(user_id: int, limit: int = 4000) -> str:
    """The user's memory trimmed for inclusion in the ask prompt, or ''. """
    row = db.get_memory(user_id)
    if not row or not row["content"] or row["content"] == EMPTY:
        return ""
    return row["content"][:limit]
