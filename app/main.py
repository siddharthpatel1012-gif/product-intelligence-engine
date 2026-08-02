import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from app.schemas import ProductInput, EnrichedProduct
from app.agents.orchestrator import run_pipeline, run_retrieval, build_candidates, run_scoring
from app.agents.extraction_agent import extract_from_source
from app.utils import cache

app = FastAPI(
    title="UniHack Product Intelligence Engine",
    description="Turns minimal product input (MPN, brand, description) "
                "into rich, structured, confidence-scored commerce data.",
    version="0.1.0",
)

# Wide open for hackathon demo purposes — the frontend may be opened as a
# local file:// page or served from a different origin than the API.
# Tighten allow_origins before shipping this anywhere real.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_PATH = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    """
    Serves the dashboard directly at the root URL, so the deployed link
    (e.g. https://your-app.onrender.com) shows the actual product instead
    of a bare JSON health check. Falls back to the JSON health check if
    the frontend file isn't found (e.g. in an environment that only ships
    the backend).
    """
    if FRONTEND_PATH.exists():
        return FileResponse(FRONTEND_PATH)
    return {"status": "ok", "service": "product-intelligence-engine"}


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "product-intelligence-engine"}


@app.post("/enrich", response_model=EnrichedProduct)
def enrich(product_input: ProductInput):
    cached = cache.get(product_input.mpn, product_input.brand)
    if cached:
        return cached
    try:
        result = run_pipeline(product_input)
        cache.set(product_input.mpn, product_input.brand, json.loads(result.model_dump_json()))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _stream_pipeline(product_input: ProductInput):
    """
    Generator that runs the same four stages as run_pipeline, but yields
    an SSE event after each meaningful step so the frontend can show real
    progress instead of a canned animation.

    Event types: cache_hit, stage_start, source_found, source_extracted,
    stage_done, result, error.
    """
    cached = cache.get(product_input.mpn, product_input.brand)
    if cached:
        yield _sse("cache_hit", {"detail": "served from cache — no API calls made"})
        yield _sse("result", cached)
        return

    try:
        # Stage 1: Retrieval
        yield _sse("stage_start", {"stage": "retrieval"})
        sources = run_retrieval(product_input)
        yield _sse("stage_done", {
            "stage": "retrieval",
            "detail": f"found {len(sources)} candidate source(s)",
            "sources": [s.url for s in sources],
        })

        # Stage 2: Extraction (per-source events so the UI can show what's
        # actively being read, not just a spinner)
        yield _sse("stage_start", {"stage": "extraction"})
        extractions = []
        for source in sources:
            yield _sse("source_extracting", {"url": source.url, "type": source.source_type})
            result = extract_from_source(source, product_input.mpn, product_input.brand)
            extractions.append(result)
            found_fields = sum([
                1 if result["data"].get("title") else 0,
                1 if result["data"].get("category") else 0,
                len((result["data"].get("specifications") or {})),
            ])
            yield _sse("source_extracted", {"url": source.url, "fields_found": found_fields})
        yield _sse("stage_done", {"stage": "extraction", "detail": f"processed {len(sources)} source(s)"})

        # Stage 3: Structuring
        yield _sse("stage_start", {"stage": "structuring"})
        candidates = build_candidates(extractions, product_input)
        spec_count = len(candidates["specifications"])
        stats = candidates["extraction_stats"]
        detail = f"{spec_count} spec field(s) identified"
        if stats.sources_failed:
            detail += f" ({stats.sources_failed}/{stats.sources_attempted} source(s) yielded nothing)"
        yield _sse("stage_done", {"stage": "structuring", "detail": detail})

        # Stage 4: Confidence scoring
        yield _sse("stage_start", {"stage": "scoring"})
        enriched = run_scoring(candidates, product_input, sources)
        yield _sse("stage_done", {
            "stage": "scoring",
            "detail": f"overall confidence {round(enriched.overall_confidence * 100)}%",
        })

        result_dict = json.loads(enriched.model_dump_json())
        cache.set(product_input.mpn, product_input.brand, result_dict)
        yield _sse("result", result_dict)

    except Exception as e:
        yield _sse("error", {"message": str(e)})


@app.post("/enrich/stream")
def enrich_stream(product_input: ProductInput):
    return StreamingResponse(
        _stream_pipeline(product_input),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if deployed behind it
        },
    )