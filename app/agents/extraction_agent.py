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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    """Sequential version — kept for reference/fallback. Prefer the
    concurrent version below for actual use; this processes one source
    at a time, which is much slower (the original bottleneck)."""
    return [extract_from_source(s, mpn, brand) for s in sources]


def extract_from_all_sources_concurrent(
    sources: list[SourceRef], mpn: str, brand: str, max_workers: int = 5
) -> list[dict]:
    """
    Runs extraction for all sources IN PARALLEL using a thread pool,
    instead of one at a time. This is the actual fix for slow enrichment
    runs — each source's fetch+LLM-call was previously waited on fully
    before the next one started, so 5 sources sequentially took roughly
    5x as long as they needed to. Since each extraction is I/O-bound
    (waiting on network requests and API responses, not CPU-bound work),
    threads work well here despite Python's GIL — the GIL is released
    during I/O waits, so this genuinely runs concurrently, not just
    interleaved.

    Returns results in the SAME ORDER as `sources` was given, even
    though they may complete out of order internally — this keeps the
    return value consistent with the old sequential version so nothing
    downstream needs to change.
    """
    results: list[dict | None] = [None] * len(sources)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(extract_from_source, source, mpn, brand): i
            for i, source in enumerate(sources)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results[index] = future.result()
            except Exception as e:
                # A single source's unexpected crash shouldn't take down
                # the whole batch — record it as a failed extraction.
                source = sources[index]
                print(f"[extract] thread crashed for {source.url}: {e}")
                data = _empty_result()
                data["_error"] = str(e)
                results[index] = {"source": source, "data": data}
    return results