"""
LLM Client
-----------
Thin abstraction so extraction_agent, vlm_agent, and taxonomy_agent don't
need to know or care which provider is actually answering. Switch
providers with LLM_PROVIDER=anthropic|gemini in .env — no other code
changes needed.

Why this exists: Anthropic's API needs a paid credit balance (even a
small one) to make any call at all. Gemini's API has a genuinely free
tier (no card required) that's generous enough for testing a project
like this. This lets the project run on whichever one you actually
have working credentials for.
"""
from app import config

_anthropic_client = None
_gemini_configured = False


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import Anthropic
        _anthropic_client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _anthropic_client


def _ensure_gemini_configured():
    global _gemini_configured
    if not _gemini_configured:
        import google.generativeai as genai
        genai.configure(api_key=config.GEMINI_API_KEY)
        _gemini_configured = True


def generate(system_prompt: str, user_text: str, images: list[bytes] | None = None, max_tokens: int = 1500) -> str:
    """
    Sends a system prompt + user text (+ optional list of raw image bytes,
    PNG/JPEG) to whichever provider is configured, and returns the raw
    text response.
    """
    if config.LLM_PROVIDER == "gemini":
        return _generate_gemini(system_prompt, user_text, images, max_tokens)
    return _generate_anthropic(system_prompt, user_text, images, max_tokens)


def _generate_anthropic(system_prompt: str, user_text: str, images: list[bytes] | None, max_tokens: int) -> str:
    import base64
    client = _get_anthropic_client()

    if images:
        content = [{"type": "text", "text": user_text}]
        for img_bytes in images:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(img_bytes).decode("utf-8")},
            })
        messages = [{"role": "user", "content": content}]
    else:
        messages = [{"role": "user", "content": user_text}]

    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
    )
    return message.content[0].text.strip()


def _generate_gemini(system_prompt: str, user_text: str, images: list[bytes] | None, max_tokens: int) -> str:
    import time
    import google.generativeai as genai
    from google.api_core.exceptions import ResourceExhausted
    _ensure_gemini_configured()

    model = genai.GenerativeModel(
        config.GEMINI_MODEL,
        system_instruction=system_prompt,
        generation_config={"max_output_tokens": max_tokens},
    )

    parts: list = [user_text]
    if images:
        for img_bytes in images:
            parts.append({"mime_type": "image/png", "data": img_bytes})

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            response = model.generate_content(parts)
            return (response.text or "").strip()
        except ResourceExhausted as e:
            if attempt == max_attempts:
                raise
            # Google's error includes a suggested retry_delay in seconds when
            # this is a short-term rate limit (RPM) rather than an exhausted
            # daily quota (RPD) - the latter won't be fixed by waiting a few
            # seconds, but we still back off briefly rather than failing fast.
            wait_seconds = getattr(getattr(e, "retry_delay", None), "seconds", None) or (5 * attempt)
            print(f"[llm_client] rate limited, retrying in {wait_seconds}s (attempt {attempt}/{max_attempts})")
            time.sleep(min(wait_seconds, 30))