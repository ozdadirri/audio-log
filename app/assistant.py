"""AI assistant over the transcript library: FTS5 retrieval picks the most
relevant excerpts, the Ollama model answers grounded in them."""

from . import db, summarize

ASK_PROMPT = """You are the assistant for a personal library of audio transcripts.
Answer the user's question using ONLY the transcript excerpts below.
Cite the recordings you used inline as [#id]. Be concise.
If the excerpts don't contain the answer, say you couldn't find it in the recordings.

Excerpts:
{context}

Question: {question}"""


def ask(question: str) -> dict:
    hits = db.retrieve(question)
    if not hits:
        return {"answer": "No recordings matched that question.", "sources": []}
    context = "\n\n".join(
        f"[#{h['id']}] {h['filename']} (recorded {h['created_at'][:10]})\n{h['excerpt']}"
        for h in hits
    )
    answer = summarize._ollama_chat(ASK_PROMPT.format(context=context, question=question))
    return {
        "answer": answer,
        "sources": [{"id": h["id"], "filename": h["filename"]} for h in hits],
    }
