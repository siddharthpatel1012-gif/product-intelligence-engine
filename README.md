# Product Intelligence Engine — UniHack (Unilog Challenge)

Turns a raw catalogue row (MPN + brand + one-line description — often
with placeholder brand fields like `-- Unbranded --`) into rich,
structured, commerce-ready product data — with a confidence score on
every field so downstream systems know what to trust and what needs
human review.

Two ways to use it:
- **Single Lookup / Batch Compare** — interactive, one or a handful of
  products at a time, live in the browser.
- **Batch File** — upload a CSV/XLSX of raw catalogue rows, get back
  one downloadable XLSX with every row mapped to the **exact 252 fixed
  Expected Output columns** the evaluation sheet requires — unmodified
  headers, populated fields, honest blanks where no real evidence
  exists. This is the actual deliverable format the brief specifies.

🔗 **Live demo:** https://product-intelligence-engine.onrender.com
(Free-tier hosting — if it's been idle, the first request may take
30-60 seconds to wake up.)

**Third-party APIs / AI tools used:** Google Gemini API (extraction,
vision-based datasheet reading, product-category classification —
free tier, no card required), plus Serper (web search, free tier),
with automatic fallback to Tavily if configured. The project also
supports Anthropic's Claude API as a swappable alternative (see
`LLM_PROVIDER` in `.env`), but Gemini is the tested, working default.

**Status: tested end-to-end with live APIs on 9 electronics products**
across 9 categories, **plus a second round of testing across
non-electronics verticals** (abrasives, power tools, appliances) via
the Batch File pipeline — four real defects were found through that
testing and fixed with verified before/after evidence. See "Tested
results" and "Bugs found & fixed via testing" below.

## Problem & approach

The core difficulty isn't "process data you have" — it's "you barely
have any data, go find the rest, and prove how sure you are." That
splits into honest steps, and the pipeline mirrors them 1:1:

1. **Retrieval** — the input alone isn't enough. An agent searches the
   web (9 targeted query variants per product, with automatic fallback
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
4. **Header Mapping + File Output** (Batch File path only) — the
   scored record gets mapped into the exact 252 fixed Expected Output
   columns: the client's own header names, unmodified, with the
   client's own field-splitting rules applied — the five description
   formats (Invoice/Mobile/Short/Long) at their specified lengths and
   casing, attribute values split into Label/Value/UOM triplets with
   units canonicalized and decimals converted to trade fractions
   (0.5 in → 1/2 in). One XLSX per batch, ready to submit.

This is deliberately **not** a single RAG call or a single VLM call.
Real PIM (Product Information Management) teams don't trust one-shot
LLM output for commerce data — they need traceability (which source
said what) and a trust signal per field. That's the piece most
enrichment demos skip, and it's the thing this project leads with.

```
 MPN + Brand + description                Raw catalogue CSV/XLSX
 (Single Lookup / Batch Compare)           (Batch File)
          │                                          │
          ▼                                          ▼
 ┌─────────────────┐                    ┌───────────────────────┐
 │ Retrieval Agent  │  → web search      │ build_product_input() │
 └────────┬─────────┘     (9 query           → resolves brand from
          │                variants,           messy/placeholder
          │                dual-provider       fields (E1_Brand,
          │                fallback)            Unilog_Brand,
          ▼                                     DIB_Brand, Part_Manuf)
 ┌─────────────────┐                            │
 │ Extraction Agent │  → HTML table parsing,     │  (same 4 stages,
 │ (+ VLM sub-agent)│     PDF text extraction,    │   left column)
 └────────┬─────────┘     VLM for scanned         │
          │                spec sheets            │
          ▼                                       │
 ┌─────────────────┐                              │
 │ Structuring +    │  → normalize fields,         │
 │ Taxonomy Agent   │     classify against fixed    │
 └────────┬─────────┘     38-category taxonomy       │
          │                                            │
          ▼                                            ▼
 ┌─────────────────┐                    ┌───────────────────────┐
 │ Confidence Agent │  → per-field score  │ Row Mapper + UOM/     │
 └────────┬─────────┘                    │ Fraction Normalizer   │
          │                              └───────────┬───────────┘
          ▼                                          ▼
   Structured, scored,                     ┌───────────────────┐
   commerce-ready JSON                     │   XLSX Writer      │
   (cached per MPN+brand)                  │ 252 fixed headers, │
                                            │  1 file per batch  │
                                            └───────────────────┘
```

## Tested results

Run live end-to-end (real search + real LLM calls, no mocking) across
nine genuinely different product categories to confirm the pipeline
generalizes rather than working by luck on one example:

| MPN | Brand | Category | Sources succeeded | Spec fields found | Overall confidence |
|---|---|---|---|---|---|
| LM358P | Texas Instruments | Operational Amplifiers | 5/5 | 32 | 79% |
| 0603YC104KAT2A | AVX | Capacitors | 2/5 | 4 | 85% |
| L7805CV | STMicroelectronics | Power Management ICs | 3/5 | 14 | 84% |
| 1-1734248-1 | TE Connectivity | Connectors | 4/5 | 65 | 79% |
| SN7400N | Texas Instruments | Logic ICs | 4/5 | 18 | 78% |
| 24LC256-I/P | Microchip | Memory ICs | 2/5 | 9 | 81% |
| EVQ-11L05K | Panasonic | Switches & Relays | 2/5 | 8 | 82% |

Category was correctly classified against the fixed taxonomy in every
run (no false "Uncategorized"). Sources that failed or returned
nothing are tracked and surfaced, not silently dropped (see
`extraction_stats` in the response / the ⚠ warning in the UI).

The LM358P row above reflects the improved retrieval query set (9
queries, including targeted `site:octopart.com` / `site:findchips.com`
searches) — an earlier run with the original 4-query retrieval only
reached 3/5 sources and 21 fields on the identical product. A later
re-run after that improvement reached a full 5/5 sources and 31-32
fields, which is the direct, measured effect of that change.

### Batch File — tested outside electronics too

The electronics table above was the first testing pass. Since the
actual evaluation data is industrial/distributor catalogue rows (not
electronics components), the Batch File pipeline was separately run
against abrasives, power tools, and appliances via a raw CSV in the
Sample-1000-item schema (`Mfg_Part_Num, Part_Desc, E1_Brand,
Unilog_Brand, DIB_Brand, Part_Manuf`):

| Mfg_Part_Num | Part_Manuf (raw input) | Resolved brand | Result |
|---|---|---|---|
| DCB518ASTS06G | Freud Inc (2435) | Freud Inc | Manufacturer page found (diablotools.com), moderate confidence — sparse manufacturer page vs. richer distributor listing is a real, honest trade-off (see below) |
| 49-94-0013 | Milwaukee Tool | Milwaukee Tool | Manufacturer page found (milwaukeetool.com), 34 spec fields, 82% confidence |
| 5B-332-080 | Mirka Inc | Mirka Inc | No true manufacturer domain in top candidates — correctly scored lower (63%) rather than falsely inflated, once the domain-matching bug below was fixed |
| PDSH4816AF | Appliance Dealers Cooperative (APPDE) | Frigidaire *(reconciled from extraction, not the raw input)* | Full enrichment matching the brief's own worked ground-truth example for this exact product |

This round of testing against real, non-electronics data is what
surfaced the four defects below — none of them showed up in the
electronics-only testing above.

## Bugs found & fixed via testing

Found and fixed through live runs against real product data, each
with a reproducible before/after:

- **Source-authority scoring matched brand tokens against the full
  URL, not the domain.** A distributor product page whose URL slug
  happened to contain the brand name (e.g.
  `beavertools.com/.../mirka-hiolit-...`) could score as high-authority
  as the manufacturer's own site. Fixed in `retrieval_agent.py` by
  restricting the match to `urlparse(url).netloc` — confirmed via a
  before/after run where a distributor page's inflated 89% confidence
  correctly dropped to an honest 63% once it stopped being
  misclassified as a manufacturer source.
- **`MANUFACTURER_NAME`/`BRAND_NAME` blindly trusted the raw input.**
  `Part_Manuf` sometimes holds a distributor/co-op name rather than
  the true manufacturer (seen live: input said "Appliance Dealers
  Cooperative," but extraction correctly found "Frigidaire" from a
  real source). Fixed in `row_mapper.py`'s `_resolve_manufacturer_name()`
  — now prefers a genuinely extracted, confidently-scored brand over
  the raw input, falling back to the input only when extraction found
  nothing better.
- **Grit sizing risked colliding with the gram unit alias.** "80G"
  grit values, if run through generic UOM normalization, could be
  misread via the "g" → gram alias. Fixed with a spec-name-aware split
  (`_split_value_uom_for_spec`) that routes anything with "grit" in
  its label around the generic UOM table entirely.
- **A common spreadsheet mistake silently broke every row.** Pasting
  CSV text into Excel without splitting it into columns leaves an
  entire row as one comma-separated string in column A — every row
  then fails with "no Mfg_Part_Num." `file_io.py` now detects that
  exact shape (one header cell containing commas, matching comma
  counts in every data row) and auto-recovers instead of failing.

None of these were found by design review — all four came from
running real data through the live pipeline and reading the actual
output, which is why "test against real data before trusting a
pipeline" is the throughline of how this was built.

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

**Why Gemini instead of Claude, given this project is for a
Claude/Anthropic-adjacent audience?**
Purely practical: Anthropic's API requires a paid credit balance (even
a small one, ~$5) before any call succeeds — there's no ongoing free
tier. Gemini has a genuinely free daily quota, which is what actually
let this get built and tested end-to-end without a payment blocker.
The code supports both (`LLM_PROVIDER=anthropic|gemini` in `.env`,
see `app/agents/llm_client.py`) — switching back to Claude is a one-line
config change, not a rewrite, if credits are available.

**What happens if the same product is looked up twice?**
The second lookup is served instantly from an in-memory cache (keyed
on MPN+brand, 1-hour TTL) — no repeat API calls, no repeat cost. This
is visible in the UI: the pipeline stepper shows all four stages as
"cached" immediately instead of animating through each stage.

## What's in this repo

```
app/
  main.py                 FastAPI entrypoint — serves the dashboard at "/", POST /enrich,
                           POST /enrich/stream (SSE), POST /enrich/batch-file (CSV/XLSX in,
                           exact-header XLSX out), CORS enabled, caching
  config.py                API keys / settings
  schemas.py               Pydantic models (input, enriched output, confidence + breakdown)
  agents/
    orchestrator.py        Pipeline stages as standalone functions (retrieval, extraction, structuring, scoring)
    retrieval_agent.py      Web search + candidate source ranking (domain-restricted authority weighting)
    extraction_agent.py     HTML/PDF text extraction → LLM for structuring
    vlm_agent.py             Vision fallback for scanned datasheets/spec images
    taxonomy_agent.py        Classifies category against a fixed 38-category product taxonomy
    confidence_agent.py     Per-field confidence scoring + explainable breakdown
    llm_client.py            Provider abstraction — Gemini (default, free) or Anthropic (needs paid credits)
  batch/
    headers.py               The exact 252 fixed Expected Output column headers, built
                              programmatically (loops for the repeating ITEM_FEATURES_n and
                              ATTRIBUTE_LABEL/VALUE/UOM n blocks) to avoid a transcription slip
    row_mapper.py             Raw row → ProductInput (brand resolution, placeholder cleaning),
                              and EnrichedProduct → the fixed header schema
    uom.py                    UOM canonicalization + decimal-to-fraction conversion
                              (0.5 in → 1/2 in, 50.25 in → 50-1/4 in) per the content guidelines
    file_io.py                CSV/XLSX read (with defensive recovery from a common Excel
                              paste mistake) and exact-header XLSX write
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
                             + batch file (upload CSV/XLSX, download the fixed-header XLSX)
                             Also served directly by the backend at the deployed root URL.
tests/
  test_confidence.py         Unit tests for the scoring logic (no API calls)
  test_extraction_stats.py   Unit tests for failure-tracking bookkeeping (no API calls)
```

## Frontend

The dashboard is served directly at the deployed root URL (see "Live
demo" above) — no separate setup needed to view it. It's also a
standalone file (`frontend/index.html`) you can open directly in a
browser with no build step. Three views:

- **Single Lookup** — enter one MPN/brand/description, watch the four
  pipeline stages update live as the backend streams real progress
  (via Server-Sent Events), then see the scored fields with a
  click-to-expand confidence breakdown (source authority / agreement /
  method quality) per field. Repeat lookups show a "cached" indicator
  and return instantly.
- **Batch Compare** — queue several products, run them all, and see
  confidence side by side as cards; click a card for its full detail.
- **Batch File** — upload a CSV or XLSX of raw catalogue rows
  (`Mfg_Part_Num, Part_Desc, E1_Brand, Unilog_Brand, DIB_Brand,
  Part_Manuf`), and download one XLSX with every row mapped to the
  exact 252 fixed Expected Output headers — this is the actual
  submission-format deliverable, not a JSON preview of it.

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
- `GEMINI_API_KEY` — free at [aistudio.google.com](https://aistudio.google.com), no card needed
- `SERPER_API_KEY` — free at [serper.dev](https://serper.dev)
- `TAVILY_API_KEY` — optional, free at [tavily.com](https://tavily.com); enables automatic search fallback if Serper fails

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

Visit `http://localhost:8000` in a browser — the dashboard is served
directly at the root URL. Or hit the API from the command line:

```bash
curl -X POST http://localhost:8000/enrich \
  -H "Content-Type: application/json" \
  -d @data/sample_input.json

# streaming version (SSE) — same input, live progress events
curl -N -X POST http://localhost:8000/enrich/stream \
  -H "Content-Type: application/json" \
  -d @data/sample_input.json

# batch file — upload a raw catalogue CSV/XLSX, download the
# fixed-header XLSX (capped at MAX_BATCH_ROWS per request, see main.py)
# — create your own CSV with columns Mfg_Part_Num, Part_Desc,
# E1_Brand, Unilog_Brand, DIB_Brand, Part_Manuf (matching the
# hackathon's Sample-1000-item schema), or point at that file directly
curl -X POST http://localhost:8000/enrich/batch-file \
  -F "file=@your_batch.csv" \
  -o enriched_output.xlsx
```

Two extra dependencies beyond the original pipeline power the batch
path: `openpyxl` (CSV/XLSX read + exact-header XLSX write) and
`python-multipart` (required by FastAPI for file-upload endpoints) —
both are already in `requirements.txt`, no extra setup needed.

Run the test suite (no API keys required — these only test scoring
and bookkeeping logic):

```bash
python3 tests/test_confidence.py
python3 tests/test_extraction_stats.py
```

## Known limitations & honest next steps

- **Attribute values aren't yet constrained to Unilog's real LOV
  vocabulary.** The content guidelines specify that attribute values
  must come from Unilog's ~161K-row List of Values file
  (`Unicat_Lov_v1_0`), with category-specific depth for Faucets and
  Fittings. This pipeline extracts attributes freely from real sources
  (never invented — see "Bugs found & fixed" for how source quality is
  enforced) but doesn't yet check them against that constrained
  vocabulary. Scoping this to one category (Faucets or Fittings, as
  the brief itself recommends for depth) is the natural next step,
  given the reference file.
- **Manufacturer/brand names aren't yet matched against the real
  27K-row approved master list.** `MANUFACTURER_NAME`/`BRAND_NAME` are
  resolved and reconciled (see "Bugs found & fixed"), but not yet
  fuzzy-matched against `UniCat_Manufacturer_and_Brand_List.xlsx` for
  exact legal casing, suffixes, and ®/™ symbols.
- **Taxonomy is still electronics-scoped (~38 categories)**, not yet
  mapped to Unilog's actual Dept/Class/Fine classpath system. A
  non-electronics product correctly falls back to "Uncategorized"
  rather than being force-fit into a wrong electronics bucket — an
  honest gap, not a silent misclassification — but a real classpath
  mapping needs Unilog's own taxonomy data to build properly.
- **No de-duplication stage.** The brief's own pipeline order lists
  de-dup as step one; this build doesn't detect or collapse repeated
  input rows, so a catalogue with duplicate MPNs processes each one
  independently (each hitting the cache after the first, at least).
- **Batch requests are capped (`MAX_BATCH_ROWS` in `main.py`) per
  call**, since each row costs several API calls against a free-tier
  quota. A larger evaluation set needs either multiple smaller
  submissions or a raised cap paired with a paid API tier.
- **Not concurrency-safe yet.** The `/enrich/stream` generator runs
  synchronously per request, which serializes concurrent requests
  under load. Moving extraction to a task queue or running sources
  concurrently with `asyncio` is the natural next step.
- **Cache is in-memory, single-process.** Fine for a demo/pilot; would
  need Redis (or similar) to work across multiple worker processes in
  production, and resets whenever the host restarts the process (e.g.
  after idle spin-down on free hosting tiers).
- **Gemini free-tier rate limits are real.** Each enrichment run makes
  5-10+ calls (one per source, plus taxonomy classification), so heavy
  back-to-back testing — especially a full batch file run — can hit
  short-term per-minute limits. `llm_client.py` retries automatically
  on rate-limit errors with backoff, and repeat lookups are served
  from cache instead of re-hitting the API at all.
- **No knowledge-graph layer.** Substitute/similar-part linking was
  scoped out to keep the core (retrieval → extraction → structuring →
  confidence → header mapping) solid rather than spreading thin across
  an optional stretch feature.
- **Some manufacturer/distributor sites block scraping regardless of
  User-Agent** (Digi-Key, Newark, RS Online, and even manufacturer.com
  itself in some tests blocked requests) — a real, visible gap
  surfaced honestly via `extraction_stats` rather than hidden.
- **If deploying elsewhere:** some hosts (e.g. Render) now default to
  very new Python versions (3.14+) that don't yet have pre-built
  packages for a few pinned dependencies (`pydantic-core` in
  particular), causing build failures. Fix: explicitly set
  `PYTHON_VERSION=3.11.9` as an environment variable on the host —
  that's the version this was actually built and tested against.