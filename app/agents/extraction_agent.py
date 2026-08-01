"""
Extraction Agent
-----------------
Fetches each candidate source's content and asks the configured LLM
(Anthropic or Gemini — see llm_client.py) to pull out structured product
fields as JSON. Falls back to the VLM agent when a PDF looks image-based
(little/no extractable text).
"""
import json
import traceback
from app.schemas import SourceRef
from app.utils.fetch import fetch_page_text, fetch_pdf_text, is_pdf_url
from app.agents.vlm_agent import extract_from_pdf_images
from app.agents import llm_client

EXTRACTION_SYSTEM_PROMPT = """You extract structured product data from raw \
webpage or datasheet text for an eCommerce product-intelligence pipeline.

Return ONLY valid JSON, no prose, no markdown fences, matching exactly:
{
  "title": string or null,
  "category": string or null,
  "description": string or null,
  "specifications": { "<spec_name>": "<spec_value>", ... },
  "image_urls": [string, ...]
}

Rules:
- Only include values that are explicitly present in the text. Never guess or infer.
- Normalize spec names to short lowercase snake_case keys (e.g. "operating_voltage").
- If nothing relevant is found, return the JSON shape with nulls/empty collections.
"""


def _extract_from_text(text: str, mpn: str, brand: str) -> dict:
    if not text.strip():
        return _empty_result()
    user_text = (
        f"Manufacturer part number: {mpn}\nBrand: {brand}\n\n"
        f"Source text:\n{text}"
    )
    raw = llm_client.generate(EXTRACTION_SYSTEM_PROMPT, user_text, max_tokens=1500)
    return _safe_json(raw)


def _safe_json(raw: str) -> dict:
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return _empty_result()


def _empty_result() -> dict:
    return {"title": None, "category": None, "description": None,
             "specifications": {}, "image_urls": []}


def extract_from_source(source: SourceRef, mpn: str, brand: str) -> dict:
    """
    Returns {"source": SourceRef, "data": {...extracted fields...}}
    Handles webpages, text-based PDFs, and falls back to VLM for
    image-based/scanned PDFs.
    """
    try:
        if is_pdf_url(source.url):
            text = fetch_pdf_text(source.url)
            print(f"[extract] PDF {source.url} -> {len(text.strip())} chars of text")
            if len(text.strip()) < 200:  # looks scanned/image-based
                print(f"[extract] falling back to VLM for {source.url}")
                data = extract_from_pdf_images(source.url, mpn, brand)
                data["_vlm_used"] = True
            else:
                data = _extract_from_text(text, mpn, brand)
        else:
            text = fetch_page_text(source.url)
            print(f"[extract] page {source.url} -> {len(text.strip())} chars of text")
            data = _extract_from_text(text, mpn, brand)
    except Exception as e:
        print(f"[extract] ERROR on {source.url}: {e}")
        traceback.print_exc()
        data = _empty_result()
        data["_error"] = str(e)

    return {"source": source, "data": data}


def extract_from_all_sources(sources: list[SourceRef], mpn: str, brand: str) -> list[dict]:
    return [extract_from_source(s, mpn, brand) for s in sources]