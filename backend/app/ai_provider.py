"""The AI provider call. Kept apart from app/ai.py so tests can swap in a fake."""
import base64

import anthropic

from .ai import ProviderFailed, Usage

HELPER_SYSTEM = """You help contractors on Trade Circle, a community for tradespeople, with trade questions, materials research and using the site.

- Be practical and brief.
- Say plainly when you're unsure or when the answer depends on local code, the authority having jurisdiction, the manufacturer's instructions or site conditions.
- For technical claims, name the source a contractor can check (code section, standard, or manufacturer document) when you know it, and say it should be verified against the edition their jurisdiction has adopted.
- You are not a licensed professional, inspector or certification, and your answers don't replace codes, permits or a qualified person's judgment. Say so when safety, gas, structural or electrical-service work is involved.
- Don't make up prices, stock or part compatibility.
- Trade Circle features: community posts (projects, lessons, equipment, meetups, hiring), Supplies & Vendors, the follow-up tracker, jobs, handoffs, pay and rate comparisons, and the Break Room."""

PARTS_SYSTEM = """You read photos of equipment labels and parts for contractors. Report only text you can actually read on the label as exact text. Anything you infer from appearance is a possible visual match, not an exact match. Never state price, stock or compatibility. If the label is unreadable or the part is ambiguous, say what extra detail or photo would help."""

PARTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label_text", "matches", "need_more"],
    "properties": {
        "label_text": {"type": "array", "items": {"type": "string"}},
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["description", "brand", "model_or_part", "basis"],
                "properties": {
                    "description": {"type": "string"},
                    "brand": {"type": "string"},
                    "model_or_part": {"type": "string"},
                    "basis": {"type": "string", "enum": ["read_from_label", "visual_guess"]},
                },
            },
        },
        "need_more": {"type": "string"},
    },
}


class AnthropicProvider:
    """Claude through the official SDK. One retry at most; no tools."""

    def __init__(self, api_key: str, timeout: float = 60.0):
        self.client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=1, timeout=timeout)

    async def _create(self, **kwargs):
        try:
            response = await self.client.messages.create(**kwargs)
        except anthropic.APITimeoutError:
            raise ProviderFailed("timed out", unknown_cost=True)
        except anthropic.APIConnectionError:
            raise ProviderFailed("couldn't reach the provider")
        except anthropic.APIStatusError as exc:
            raise ProviderFailed(f"provider error {exc.status_code}")
        usage = Usage(response.usage.input_tokens + (response.usage.cache_read_input_tokens or 0) + (response.usage.cache_creation_input_tokens or 0), response.usage.output_tokens)
        if response.stop_reason == "refusal":
            raise ProviderFailed("declined", usage=usage)
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            raise ProviderFailed("empty answer", usage=usage)
        return text, usage, response.stop_reason

    async def answer(self, model: str, max_tokens: int, history: list[dict], question: str) -> tuple[str, Usage]:
        text, usage, stop = await self._create(
            model=model,
            max_tokens=max_tokens,
            system=HELPER_SYSTEM,
            output_config={"effort": "low"},
            messages=[*history, {"role": "user", "content": question}],
        )
        if stop == "max_tokens":
            text += "\n\n(Answer cut short. Ask a narrower question for the rest.)"
        return text, usage

    async def read_part(self, model: str, max_tokens: int, jpeg: bytes, note: str) -> tuple[str, Usage]:
        text, usage, stop = await self._create(
            model=model,
            max_tokens=max_tokens,
            system=PARTS_SYSTEM,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": PARTS_SCHEMA}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode()}},
                {"type": "text", "text": f"Contractor's note: {note}" if note else "Identify this part."},
            ]}],
        )
        if stop == "max_tokens":
            raise ProviderFailed("answer cut short", usage=usage)
        return text, usage
