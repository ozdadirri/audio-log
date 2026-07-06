"""Summarization via a local Ollama model. Long transcripts are summarized
map-reduce style: chunk -> summarize each -> merge."""

import httpx

from . import config, db

# Roughly 4 chars/token; qwen3.x handles 32k tokens comfortably, stay well under.
CHUNK_CHARS = 16_000

SUMMARY_PROMPT = """You are given a transcript of an audio recording.
Produce a digest in markdown with exactly these sections:

## TL;DR
One or two sentences.

## Key points
Bullet points of the main content.

## Decisions
Bullets, or "None" if there are no decisions.

## Action items
Bullets with owners if mentioned, or "None".

## Open questions
Bullets, or "None".

Be faithful to the transcript; do not invent details.

Transcript:
{text}"""

MERGE_PROMPT = """The following are partial digests of consecutive parts of one long recording.
Merge them into a single digest with the same section structure
(TL;DR, Key points, Decisions, Action items, Open questions). Remove duplicates.

{text}"""


def _ollama_chat(prompt: str) -> str:
    resp = httpx.post(
        f"{config.OLLAMA_URL}/api/chat",
        json={
            # the UI can switch models at runtime; env var is the default
            "model": db.get_setting("ollama_model", config.OLLAMA_MODEL),
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
        },
        timeout=600,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


TRANSLATE_ZH_PROMPT = """Translate the following markdown digest into Simplified Chinese.
Translate the section headings naturally and keep the markdown structure exactly.
Output only the translation, nothing else.

{text}"""


def translate_zh(text: str) -> str:
    return _ollama_chat(TRANSLATE_ZH_PROMPT.format(text=text))


TITLE_PROMPT = """Based on this digest of an audio recording, write a short descriptive
title of at most 8 words. Output only the title itself — no quotes, no punctuation
at the end, no explanation.

{text}"""


def make_title(summary: str) -> str:
    title = _ollama_chat(TITLE_PROMPT.format(text=summary)).strip().strip('"')
    return title.splitlines()[0][:80] if title else ""


def summarize(transcript: str) -> str:
    if len(transcript) <= CHUNK_CHARS:
        return _ollama_chat(SUMMARY_PROMPT.format(text=transcript))

    chunks = [
        transcript[i : i + CHUNK_CHARS]
        for i in range(0, len(transcript), CHUNK_CHARS)
    ]
    partials = [
        f"### Part {i + 1}\n" + _ollama_chat(SUMMARY_PROMPT.format(text=chunk))
        for i, chunk in enumerate(chunks)
    ]
    return _ollama_chat(MERGE_PROMPT.format(text="\n\n".join(partials)))
