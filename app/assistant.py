"""AI assistant over the transcript library: FTS5 retrieval picks the most
relevant excerpts, the Ollama model answers grounded in them."""

from . import db, embeddings, memory, summarize

ASK_PROMPT = """You are the assistant for a personal library of audio transcripts.
Answer the user's latest question using the transcript excerpts below and the
long-term memory (and the earlier conversation for context). Cite recordings
you used inline as [#id]. Be concise. If neither the excerpts nor the memory
contain the answer, say you couldn't find it in the recordings.
{memory}
Excerpts:
{context}
{history}
Question: {question}"""

MAX_HISTORY = 4  # question/answer pairs sent back into the prompt


def ask(question: str, user: dict,
        history: list[dict] | None = None) -> dict:
    """Retrieval is scoped to the user's recordings (admin sees all).
    history is a list of {"question", "answer"} dicts from the client."""
    user_id = None if user["is_admin"] else user["id"]
    # Retrieve on the current question plus the previous one, so follow-ups
    # like "and what did she say about it?" still find the right recordings.
    query = question
    if history:
        query = history[-1]["question"] + " " + question
    # Semantic retrieval first (matches meaning, not just words); FTS fallback
    # covers libraries indexed before embeddings existed.
    try:
        hits = embeddings.retrieve(query, user_id)
    except Exception:
        hits = []
    if not hits:
        hits = db.retrieve(query, user_id)
    mem = memory.for_prompt(user["id"])
    if not hits and not mem:
        return {"answer": "No recordings matched that question.", "sources": []}
    context = "\n\n".join(
        f"[#{h['id']}] {h['filename']} (recorded {h['created_at'][:10]})\n{h['excerpt']}"
        for h in hits
    ) or "(none matched)"
    mem_block = f"\nLong-term memory:\n{mem}\n" if mem else ""
    convo = ""
    if history:
        turns = history[-MAX_HISTORY:]
        convo = "\nConversation so far:\n" + "\n".join(
            f"Q: {t['question']}\nA: {t['answer']}" for t in turns) + "\n"
    answer = summarize._ollama_chat(
        ASK_PROMPT.format(memory=mem_block, context=context, history=convo,
                          question=question))
    return {
        "answer": answer,
        "sources": [{"id": h["id"], "filename": h["filename"]} for h in hits],
    }
