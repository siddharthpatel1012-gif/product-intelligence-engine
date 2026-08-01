"""
Fetches and cleans web pages and PDFs so extraction agents get plain
text / tables instead of raw HTML or PDF bytes.
"""
import io
import requests
from bs4 import BeautifulSoup
import pdfplumber
from app import config

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/pdf,text/html,application/xhtml+xml,*/*;q=0.8",
}


def fetch_page_text(url: str) -> str:
    """Fetch a webpage and return cleaned visible text (tables kept as rows)."""
    resp = requests.get(
        url,
        headers=BROWSER_HEADERS,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    # Keep table structure explicit — specs usually live in <table>
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append(" | ".join(cells))
        table.replace_with("\n" + "\n".join(rows) + "\n")

    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)[:20000]  # cap to keep prompts sane


def is_pdf_url(url: str) -> bool:
    return url.lower().endswith(".pdf")


def fetch_pdf_text(url: str) -> str:
    """Extract text + tables from a PDF datasheet."""
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=config.REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    text_parts = []
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        for page in pdf.pages[: config.MAX_PDF_PAGES]:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            for table in page.extract_tables():
                rows = [" | ".join(cell or "" for cell in row) for row in table]
                text_parts.append("\n".join(rows))
    return "\n".join(text_parts)[:20000]


def fetch_pdf_bytes(url: str) -> bytes:
    """Raw bytes — used when we fall back to VLM on scanned/image PDFs."""
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=config.REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.content