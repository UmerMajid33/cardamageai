"""Groq vision call.

qwen/qwen3.6-27b is currently the only model on Groq that accepts images, and
it is a reasoning model - it spends output tokens thinking before it answers.
Both facts drive the token budget below.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import groq
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=False)

# The only vision-capable model on Groq at time of writing. `python -c
# "import llm; llm.list_models()"` will show what a given key can reach.
MODEL = os.environ.get("DAMAGESCAN_MODEL", "qwen/qwen3.6-27b")

# Groq charges prompt + reserved max_tokens against the per-minute budget
# (8000 on the free tier). An image at 800px costs a few thousand prompt
# tokens on its own, so this ceiling is deliberately tight.
MAX_TOKENS = int(os.environ.get("DAMAGESCAN_MAX_TOKENS", "3500"))

# Assessment wants determinism, not flair.
TEMPERATURE = float(os.environ.get("DAMAGESCAN_TEMPERATURE", "0.2"))

_client = None


def client():
    global _client
    if _client is None:
        if not os.environ.get("GROQ_API_KEY", "").strip():
            raise RuntimeError(
                "No Groq API key found.\n"
                "Paste it into damagescan/.env after GROQ_API_KEY= "
                "(no quotes), then restart the server."
            )
        _client = groq.Groq()
    return _client


def list_models():
    return sorted(m.id for m in client().models.list().data)


def analyse_image(data_url, system, user_text, schema):
    """Send one image plus instructions, get back JSON matching `schema`."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]},
    ]

    try:
        response = client().chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "assessment", "strict": True,
                                "schema": schema},
            },
        )
    except groq.NotFoundError as exc:
        raise RuntimeError(
            f"This key has no access to '{MODEL}'. Available: "
            f"{', '.join(list_models())}"
        ) from exc
    except groq.APIStatusError as exc:
        if exc.status_code in (413, 429):
            raise RuntimeError(
                f"Groq rate limit:\n  {exc.message}\n\n"
                f"The photo may be too large. Images are downscaled in the "
                f"browser before upload - if this keeps happening, lower the "
                f"limit in static/index.html or DAMAGESCAN_MAX_TOKENS in .env."
            ) from exc
        raise

    choice = response.choices[0]
    if choice.finish_reason == "length":
        raise RuntimeError(
            f"The model ran out of room at {MAX_TOKENS} tokens before finishing. "
            f"Raise DAMAGESCAN_MAX_TOKENS in .env."
        )

    content = (choice.message.content or "").strip()
    if not content:
        raise RuntimeError(
            f"Model returned nothing (finish_reason={choice.finish_reason})."
        )

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Model returned invalid JSON: {exc}\nFirst 300 chars: {content[:300]}"
        ) from exc

    missing = [k for k in schema.get("required", []) if k not in data]
    if missing:
        raise RuntimeError(f"Model omitted required field(s): {missing}")

    usage = SimpleNamespace(
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
    )
    return data, usage
