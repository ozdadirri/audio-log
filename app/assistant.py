"""AI assistant over the transcript library: FTS5 retrieval picks the most
relevant excerpts, the Ollama model answers grounded in them."""

from . import db, summarize

ASK_PROMPT = """You are the assistant for a personal library of audio transcripts.
Answer the user's latest question using ONLY the transcript excerpts below
(and the earlier conversation for context). Cite the recordings you used
inline as [#id]. Be concise. If the excerpts don't contain the answer, say
you couldn't find it in the recordings.

Excerpts:
{context}
{history}
Question: {question}"""

MAX_HISTORY = 4  # question/answer pairs sent back into the prompt


def ask(question: str, user_id: int | None = None,
        history: list[dict] | None = None) -> dict:
    """user_id scopes retrieval to that user's recordings; None = all (admin).
    history is a list of {"question", "answer"} dicts from the client."""
    # Retrieve on the current question plus the previous one, so follow-ups
    # like "and what did she say about it?" still find the right recordings.
    query = question
    if history:
        query = history[-1]["question"] + " " + question
    hits = db.retrieve(query, user_id)
    if not hits:
        return {"answer": "No recordings matched that question.", "sources": []}
    context = "\n\n".join(
        f"[#{h['id']}] {h['filename']} (recorded {h['created_at'][:10]})\n{h['excerpt']}"
        for h in hits
    )
    convo = ""
    if history:
        turns = history[-MAX_HISTORY:]
        convo = "\nConversation so far:\n" + "\n".join(
            f"Q: {t['question']}\nA: {t['answer']}" for t in turns) + "\n"
    answer = summarize._ollama_chat(
        ASK_PROMPT.format(context=context, history=convo, question=question))
    return {
        "answer": answer,
        "sources": [{"id": h["id"], "filename": h["filename"]} for h in hits],
    }
