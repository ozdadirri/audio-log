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


# code -> (native label, English name for the prompt). English is the original.
LANGUAGES = [
    ("en", "English", "English"),
    ("zh", "中文", "Simplified Chinese"),
    ("es", "Español", "Spanish"),
    ("fr", "Français", "French"),
    ("de", "Deutsch", "German"),
    ("ja", "日本語", "Japanese"),
    ("ko", "한국어", "Korean"),
    ("pt", "Português", "Portuguese"),
    ("it", "Italiano", "Italian"),
    ("hi", "हिन्दी", "Hindi"),
    ("ar", "العربية", "Arabic"),
    ("vi", "Tiếng Việt", "Vietnamese"),
]
_LANG_NAMES = {code: english for code, _, english in LANGUAGES}

TRANSLATE_PROMPT = """Translate the following markdown into {language}.
Translate section headings naturally and keep the markdown structure exactly.
Output only the translation, nothing else.

{text}"""


def translate(text: str, lang: str) -> str:
    language = _LANG_NAMES.get(lang, "Simplified Chinese")
    return _ollama_chat(TRANSLATE_PROMPT.format(language=language, text=text))


def translate_zh(text: str) -> str:  # kept for backward compatibility
    return translate(text, "zh")


TITLE_PROMPT = """Based on this digest of an audio recording, write a short descriptive
title of at most 8 words. Output only the title itself — no quotes, no punctuation
at the end, no explanation.

{text}"""


TAG_VOCABULARY = [
    "meeting", "standup", "interview", "call", "idea", "journal",
    "note", "lecture", "demo", "music", "personal", "work",
]

TAGS_PROMPT = """Classify this recording digest with 1 to 3 tags.
Prefer tags from this list: {vocab}.
You may invent one extra tag if none fit well.
Output ONLY the tags, lowercase, comma-separated — nothing else.

{text}"""


def make_tags(summary: str) -> str:
    raw = _ollama_chat(TAGS_PROMPT.format(vocab=", ".join(TAG_VOCABULARY), text=summary))
    tags = [t.strip().lower() for t in raw.splitlines()[0].split(",")]
    tags = [t for t in tags if t and len(t) <= 20 and t.replace("-", "").isalnum()]
    return ",".join(dict.fromkeys(tags[:3]))  # dedupe, max 3


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
