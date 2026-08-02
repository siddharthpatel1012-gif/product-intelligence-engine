# Product Intelligence Engine — UniHack (Unilog Challenge)

Turns minimal input (MPN + brand + one-line description) into rich,
structured, commerce-ready product data — with a confidence score on
every field so downstream systems know what to trust and what needs
human review.

**Third-party APIs / AI tools used:** Google Gemini API (extraction,
vision-based datasheet reading, product-category classification —
free tier, no card required), plus Serper (web search, free tier),
with automatic fallback to Tavily if configured. The project also
supports Anthropic's Claude API as a swappable alternative (see
`LLM_PROVIDER` in `.env`), but Gemini is the tested, working default.

**Status: tested end-to-end with live APIs on 6 real, different
products** across 6 different categories — see "Tested results" below.

## Problem & approach

The core difficulty isn't "process data you have" — it's "you barely
have any data, go find the rest, and prove how sure you are." That
splits into three honest steps, and the pipeline mirrors them 1:1:

1. **Retrieval** — the input alone isn't enough. An agent searches the
   web (7 targeted query variants per product, with automatic fallback
   to a second search provider) for manufacturer pages, distributor
   listings, and datasheet PDFs for the given MPN/brand.
2. **Extraction** — the good data (dimensions, materials, certs,
   electrical specs) usually lives in messy HTML tables or scanned PDF
   datasheets, not clean text. A document/vision agent pulls structured
   fields out of whatever was found, including tables inside PDFs and
   spec-sheet images (vision fallback fires when a PDF has no
   extractable text — i.e. it's scanned).
3. **Structuring + Confidence Scoring** — raw extracted fields get
   normalized into one schema, category is validated against a fixed
   38-category taxonomy (not left as free text), and every field gets
   a confidence score based on source agreement, source authority, and
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
 │ Retrieval Agent  │  → web search (7 query variants, dual-provider
 └────────┬─────────┘     fallback), manufacturer site, distributor
          │                listings, datasheet PDFs
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
 │ Taxonomy Agent   │     a fixed 38-category product taxonomy
 └────────┬─────────┘
          │
          ▼
 ┌─────────────────┐
 │ Confidence Agent │  → per-field score: source count, source
 └────────┬─────────┘     authority, cross-source agreement,
          │                extraction-method reliability
          ▼
   Structured, scored, commerce-ready JSON
   (cached per MPN+brand for 1hr — instant repeat lookups)
```

## Tested results

Run live end-to-end (real search + real LLM calls, no mocking) across
six genuinely different product categories to confirm the pipeline
generalizes rather than working by luck on one example:

| MPN | Brand | Category | Sources succeeded | Spec fields found | Overall confidence |
|---|---|---|---|---|---|
| LM358P | Texas Instruments | Operational Amplifiers | 5/5 | 32 | 79% |
| 0603YC104KAT2A | AVX | Capacitors | 2/5 | 4 | 85% |
| L7805CV | STMicroelectronics | Power Management ICs | 3/5 | 14 | 84% |
| 1-1734248-1 | TE Connectivity | Connectors | 4/5 | 65 | 79% |
| SN7400N | Texas Instruments | Logic ICs | 4/5 | 18 | 78% |
| 24LC256-I/P | Microchip | Memory ICs | 2/5 | 9 | 81% |

Category was correctly classified against the fixed taxonomy in every
run (no false "Uncategorized"). Sources that failed or returned
nothing are tracked and surfaced, not silently dropped (see
`extraction_stats` in the response / the ⚠ warning in the UI). The
LM358P run above (5/5 sources, 32 fields) used the improved 7-query
retrieval — an earlier run with the original 4-query retrieval only
reached 3/5 sources and 21 fields on the identical product, which is
the direct, measured effect of that improvement.

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
producing thinner data with no explanation. In testing, 2-5 of 5
sources typically succeeded per run; the rest failed for ordinary
reasons (403s from distributor/manufacturer sites blocking scrapers,
thin pages) and that failure is visible in the UI rather than hidden.

**Is "category" just whatever the LLM said?**
No — it's validated against a fixed 38-category taxonomy list
(`app/agents/taxonomy_agent.py`). If nothing in the list is a confident
fit, the field is set to "Uncategorized" and flagged for review rather
than inventing a new category. If extraction never found explicit
category text but the taxonomy classifier still confidently picked one
from the input alone (common — most datasheets don't literally say
"Category: X"), that's scored as a moderate-confidence success, not a
failure.

**What happens if the same product is looked up twice?**
The second lookup is served instantly from an in-memory cache (keyed
on MPN+brand, 1-hour TTL) — no repeat API calls, no repeat cost. This
is visible in the UI: the pipeline stepper shows all four stages as
"cached" immediately instead of animating through each stage.

## What's in this repo

```
app/
  main.py                 FastAPI entrypoint — POST /enrich, POST /enrich/stream (SSE), CORS enabled, caching
  config.py                API keys / settings
  schemas.py               Pydantic models (input, enriched output, confidence + breakdown)
  agents/
    orchestrator.py        Pipeline stages as standalone functions (retrieval, extraction, structuring, scoring)
    retrieval_agent.py      Web search + candidate source ranking
    extraction_agent.py     HTML/PDF text extraction → LLM for structuring
    vlm_agent.py             Vision fallback for scanned datasheets/spec images
    taxonomy_agent.py        Classifies category against a fixed 38-category product taxonomy
    confidence_agent.py     Per-field confidence scoring + explainable breakdown
    llm_client.py            Provider abstraction — Gemini (default, free) or Anthropic (needs paid credits)
  utils/
    search.py               Pluggable web search client (Serper/Tavily) with automatic cross-provider fallback
    fetch.py                 Page + PDF fetching, cleaning (with browser User-Agent — some sites 403 without it)
    cache.py                 In-memory TTL cache — repeat MPN+brand lookups skip the pipeline entirely
data/
  sample_input.json         Example minimal input
  sample_output.json        Example enriched output (hand-written, for demo/UI)
frontend/
  index.html                Standalone dashboard: single lookup (live SSE progress, cache-hit indicator)
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
  method quality) per field. Repeat lookups show a "cached" indicator
  and return instantly.
- **Batch Compare** — queue several products, run them all, and see
  confidence side by side as cards; click a card for its full detail.

Works fully offline too: "Load Sample Result" renders embedded demo
data with no backend needed, so the UI can be reviewed even without
live API keys.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows; use `source venv/bin/activate` on Mac/Linux
pip install -r requirements.txt
copy .env.example .env         # Windows; use `cp .env.example .env` on Mac/Linux
```

Fill in `.env` with:
- `GEMINI_API_KEY` 
- `SERPER_API_KEY` 
- `TAVILY_API_KEY` 

Leave `LLM_PROVIDER=gemini` and `GEMINI_MODEL=gemini-3.1-flash-lite` as
the defaults — this is the exact configuration tested above. **Note:**
new Gemini accounts don't have access to older model names like
`gemini-2.5-flash` or the `gemini-flash-latest` alias (which currently
points to a model with only a 20 requests/day free quota — far too low
for this pipeline). If `gemini-3.1-flash-lite` stops working in the
future, check [aistudio.google.com](https://aistudio.google.com) for
the current recommended free-tier model name.

Then run:

```bash
uvicorn app.main:app --reload
```

Open `frontend/index.html` directly in a browser (double-click it —
no server needed for the frontend itself), or hit the API from the
command line:

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
- **Cache is in-memory, single-process.** Fine for a demo/pilot; would
  need Redis (or similar) to work across multiple worker processes in
  production.
- **Gemini free-tier rate limits are real.** Each enrichment run makes
  5-10+ calls (one per source, plus taxonomy classification), so heavy
  back-to-back testing can hit short-term per-minute limits.
  `llm_client.py` retries automatically on rate-limit errors with
  backoff, and repeat lookups are now served from cache instead of
  re-hitting the API at all.
- **No knowledge-graph layer.** Substitute/similar-part linking was
  scoped out to keep the core (retrieval → extraction → structuring →
  confidence) solid rather than spreading thin across an optional
  stretch feature.
- **Some manufacturer/distributor sites block scraping regardless of
  User-Agent** (Digi-Key, Newark, and even manufacturer.com itself in
  one test blocked requests) — a real, visible gap surfaced honestly
  via `extraction_stats` rather than hidden. Didn't stop the pipeline
  from succeeding overall since other sources filled in.