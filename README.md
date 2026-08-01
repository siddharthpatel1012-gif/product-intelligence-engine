# Product Intelligence Engine 

Turns minimal input (MPN + brand + one-line description) into rich,
structured, commerce-ready product data — with a confidence score on
every field so downstream systems know what to trust and what needs
human review.

**Third-party APIs / AI tools used:** Anthropic Claude API (extraction,
vision-based datasheet reading, product-category classification), plus
a pluggable web search API (Serper or Tavily — either has a free tier).

## Problem & approach

The core difficulty isn't "process data you have" — it's "you barely
have any data, go find the rest, and prove how sure you are." That
splits into three honest steps, and the pipeline mirrors them 1:1:

1. **Retrieval** — the input alone isn't enough. An agent searches the
   web for manufacturer pages, distributor listings, and datasheet PDFs
   for the given MPN/brand.
2. **Extraction** — the good data (dimensions, materials, certs,
   electrical specs) usually lives in messy HTML tables or scanned PDF
   datasheets, not clean text. A document/vision agent pulls structured
   fields out of whatever was found, including tables inside PDFs and
   spec-sheet images (via Claude vision when a PDF has no extractable
   text — i.e. it's scanned).
3. **Structuring + Confidence Scoring** — raw extracted fields get
   normalized into one schema, category is validated against a fixed
   taxonomy list (not left as free text), and every field gets a
   confidence score based on source agreement, source authority, and
   extraction certainty. Low-confidence fields are flagged for human
   review instead of silently shipped.

This is deliberately **not** a single RAG call or a single VLM call.
Real PIM (Product Information Management) teams don't trust one-shot
LLM output for commerce data — they need traceability (which source
said what) and a trust signal per field. That's the piece most
enrichment demos skip, and it's the thing this project leads with.

```
 MPN + Brand + description
          │
          ▼
 ┌─────────────────┐
 │ Retrieval Agent  │  → web search, manufacturer site, distributor
 └────────┬─────────┘     listings, datasheet PDFs
          │  candidate sources (URLs, PDFs)
          ▼
 ┌─────────────────┐
 │ Extraction Agent │  → HTML table parsing, PDF text extraction,
 │ (+ VLM sub-agent)│     VLM for scanned/image-based spec sheets
 └────────┬─────────┘
          │  raw field: value: source mappings (multiple sources)
          ▼
 ┌─────────────────┐
 │ Structuring +    │  → normalize fields, dedupe, classify against
 │ Taxonomy Agent   │     a fixed product-category list
 └────────┬─────────┘
          │
          ▼
 ┌─────────────────┐
 │ Confidence Agent │  → per-field score: source count, source
 └────────┬─────────┘     authority, cross-source agreement,
          │                extraction-method reliability
          ▼
   Structured, scored, commerce-ready JSON
```

## Design decisions & why

**Why not just one RAG call?**
RAG retrieves and answers, but it doesn't reconcile sources that
disagree, and it doesn't tell you how sure it is. A commerce team needs
both — knowing a field is 90%-confident vs. a rough guess changes what
they do with it downstream.

**Why not just a VLM on the datasheet?**
Two reasons. First, a lot of MPNs don't have a public datasheet at all
— retrieval has to find something to look at before vision can read
it. Second, vision extraction is inherently less certain than parsing
clean text or an HTML table, which is why the scoring model weights it
lower (0.7x vs. 1.0x for text-based extraction).

**How are conflicting sources handled?**
The value from the higher-authority source wins (manufacturer >
datasheet > distributor > general web), but the confidence score is
capped when sources disagree — a conflict is a signal that something
needs a second look, not something to paper over silently.

**What happens when a source fails or times out?**
It's tracked, not swallowed. Every response includes `extraction_stats`
— how many sources were attempted vs. how many actually yielded data —
so a partial failure is visible in the output rather than silently
producing thinner data with no explanation.

**Is "category" just whatever the LLM said?**
No — it's validated against a fixed taxonomy list (`app/agents/taxonomy_agent.py`).
If nothing in the list is a confident fit, the field is set to
"Uncategorized" and flagged for review rather than inventing a new
category. A wrong category is worse than an honest "we don't know."

## What's in this repo

```
app/
  main.py                 FastAPI entrypoint — POST /enrich, POST /enrich/stream (SSE), CORS enabled
  config.py                API keys / settings
  schemas.py               Pydantic models (input, enriched output, confidence + breakdown)
  agents/
    orchestrator.py        Pipeline stages as standalone functions (retrieval, extraction, structuring, scoring)
    retrieval_agent.py      Web search + candidate source ranking
    extraction_agent.py     HTML/PDF text extraction → Claude for structuring
    vlm_agent.py             Claude vision for scanned datasheets/spec images
    taxonomy_agent.py        Classifies category against a fixed product-category list
    confidence_agent.py     Per-field confidence scoring + explainable breakdown
  utils/
    search.py               Pluggable web search client (Serper/Tavily/SerpAPI)
    fetch.py                 Page + PDF fetching, cleaning
data/
  sample_input.json         Example minimal input
  sample_output.json        Example enriched output (hand-written, for demo/UI)
frontend/
  index.html                Standalone dashboard: single lookup (live SSE progress)
                             + batch compare (queue of products, side-by-side cards)
tests/
  test_confidence.py         Unit tests for the scoring logic (no API calls)
  test_extraction_stats.py   Unit tests for failure-tracking bookkeeping (no API calls)
```

## Frontend

`frontend/index.html` is a standalone dashboard — open it directly in a
browser, no build step. Two views:

- **Single Lookup** — enter one MPN/brand/description, watch the four
  pipeline stages update live as the backend streams real progress
  (via Server-Sent Events), then see the scored fields with a
  click-to-expand confidence breakdown (source authority / agreement /
  method quality) per field.
- **Batch Compare** — queue several products, run them all, and see
  confidence side by side as cards; click a card for its full detail.

Works fully offline too: "Load Sample Result" renders embedded demo
data with no backend needed, so the UI can be reviewed even without
live API keys.

*(Screenshots of both views should go here before submission — see
"Before you submit" below.)*

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY and a search API key (Serper or Tavily)
uvicorn app.main:app --reload
```

Then either open `frontend/index.html` directly, or hit the API from
the command line:

```bash
curl -X POST http://localhost:8000/enrich \
  -H "Content-Type: application/json" \
  -d @data/sample_input.json

# streaming version (SSE) — same input, live progress events
curl -N -X POST http://localhost:8000/enrich/stream \
  -H "Content-Type: application/json" \
  -d @data/sample_input.json
```

Run the test suite (no API keys required — these only test scoring
and bookkeeping logic):

```bash
python3 tests/test_confidence.py
python3 tests/test_extraction_stats.py
```

## Known limitations & honest next steps

- **Not concurrency-safe yet.** The `/enrich/stream` generator runs
  synchronously per request, which serializes concurrent requests
  under load. Moving extraction to a task queue or running sources
  concurrently with `asyncio` is the natural next step.
- **No caching.** Repeat lookups of the same MPN re-run the full
  pipeline (and re-spend API calls) every time. A simple cache keyed
  on MPN+brand would fix this cheaply.
- **No knowledge-graph layer.** Substitute/similar-part linking was
  scoped out to keep the core (retrieval → extraction → structuring →
  confidence) solid rather than spreading thin across an optional
  stretch feature.
- **Taxonomy list is small and electronics-specific** (`app/agents/taxonomy_agent.py`)
  — easy to extend, but currently only covers ~20 categories.

## Before you submit

- [ ] Run the pipeline end-to-end with real API keys on several real
      MPNs across different categories — this repo has been syntax-
      checked and unit-tested, but never run against live search/Claude
      APIs (no outbound internet in the environment it was built in).
- [ ] Add 3–4 screenshots (single lookup result, batch compare, a
      confidence tooltip open) to this README.
- [ ] Confirm your actual submission portal's required fields (repo
      link, video, screenshots, third-party tool disclosure — the note
      at the top of this README covers the latter) and fill them in.
- [ ] If a live working copy is wanted, deploy the backend somewhere
      reachable (Render/Railway/Fly.io free tiers all work) rather than
      leaving the frontend pointed at `localhost`.
