"""
VLM Agent
----------
Fallback used when a PDF datasheet has little/no extractable text
(i.e. it's scanned or image-based). Renders PDF pages to images and
asks the configured LLM's vision capability (Anthropic or Gemini — see
llm_client.py) to read specs directly off the page.

Uses PyMuPDF (fitz) to render PDF pages to images — no system poppler
binary needed.
"""
import json
from app.utils.fetch import fetch_pdf_bytes
from app.agents import llm_client

VLM_SYSTEM_PROMPT = """You read scanned/image-based datasheet pages and \
extract structured product data for an eCommerce product-intelligence \
pipeline.

Return ONLY valid JSON, no prose, no markdown fences, matching exactly:
{
  "title": string or null,
  "category": string or null,
  "description": string or null,
  "specifications": { "<spec_name>": "<spec_value>", ... },
  "image_urls": []
}

Only include values you can actually read on the page. Never guess.
"""


def _render_pdf_pages_to_images(pdf_bytes: bytes, max_pages: int = 5) -> list[bytes]:
    import fitz  # PyMuPDF
    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page_num in range(min(max_pages, len(doc))):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=150)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def extract_from_pdf_images(pdf_url: str, mpn: str, brand: str) -> dict:
    empty = {"title": None, "category": None, "description": None,
             "specifications": {}, "image_urls": []}
    try:
        pdf_bytes = fetch_pdf_bytes(pdf_url)
        page_images = _render_pdf_pages_to_images(pdf_bytes)
    except Exception as e:
        empty["_error"] = f"pdf render failed: {e}"
        return empty

    if not page_images:
        return empty

    user_text = (
        f"Manufacturer part number: {mpn}\nBrand: {brand}\n\n"
        f"Extract product data from these datasheet page images."
    )

    try:
        raw = llm_client.generate(VLM_SYSTEM_PROMPT, user_text, images=page_images, max_tokens=1500)
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except json.JSONDecodeError:
        empty["_error"] = "could not parse VLM response as JSON"
        return empty
    except Exception as e:
        empty["_error"] = str(e)
        return empty