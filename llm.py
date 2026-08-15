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

# qwen is a reasoning model, and left to itself it spends most of the output
# budget thinking before it writes any JSON - measured at 2415 tokens of
# reasoning against 168 tokens of actual answer on the same image. When that
# thinking runs past the ceiling the JSON never completes and Groq rejects the
# call with json_validate_failed and an empty generation.
#
# This is structured extraction against a strict schema, not a problem that
# needs deliberation, so reasoning is off by default. Set "default" to turn it
# back on, and raise DAMAGESCAN_MAX_TOKENS well above 3500 if you do.
REASONING = os.environ.get("DAMAGESCAN_REASONING", "none").strip()

_client = None


def client():
    global _client
    if _client is None:
        if not os.environ.get("GROQ_API_KEY", "").strip():
            # An empty value in .env resolves to "", which the SDK accepts and
            # then fails on with an opaque 401 much later. Catch it here.
            deployed = bool(os.environ.get("RENDER") or os.environ.get("PORT"))
            where = ("Set GROQ_API_KEY in your host's environment settings "
                     "(on Render: Dashboard > your service > Environment)."
                     if deployed else
                     "Paste it into damagescan/.env after GROQ_API_KEY= , with "
                     "no quotes and no spaces around the = .")
            raise RuntimeError(
                f"No Groq API key found.\n{where}\nThen restart the service."
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

    def create(max_tokens, reasoning):
        kwargs = {
            "model": MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": TEMPERATURE,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "assessment", "strict": True,
                                "schema": schema},
            },
        }
        if reasoning:
            kwargs["reasoning_effort"] = reasoning
        return client().chat.completions.create(**kwargs)

    try:
        try:
            response = create(MAX_TOKENS, REASONING)
        except groq.APIStatusError as first:
            # json_validate_failed means the model ran out of room before the
            # JSON was complete. One retry with reasoning off and more headroom
            # fixes the overwhelming majority of these.
            spent_on_thinking = (first.status_code == 400
                                 and "json_validate_failed" in str(first))
            if not spent_on_thinking or REASONING == "none":
                raise
            response = create(min(MAX_TOKENS * 2, 8000), "none")
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
                f"browser before upload - if this keeps happening, lower "
                f"MAX_EDGE in static/index.html."
            ) from exc
        if exc.status_code == 400 and "json_validate_failed" in str(exc):
            raise RuntimeError(
                f"The model could not produce a complete report for this photo "
                f"within {MAX_TOKENS} tokens.\n"
                f"Raise DAMAGESCAN_MAX_TOKENS, or set DAMAGESCAN_REASONING=none "
                f"(currently '{REASONING}') so the budget goes to the answer "
                f"rather than to thinking."
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
