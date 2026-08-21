import io
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from app.schemas import ProductInput, EnrichedProduct
from app.agents.orchestrator import run_pipeline, run_retrieval, build_candidates, run_scoring
from app.agents.extraction_agent import extract_from_source
from app.utils import cache
from app.batch.headers import EXPECTED_HEADERS
from app.batch.row_mapper import build_product_input, map_row_to_headers
from app.batch.file_io import read_input_file, write_xlsx_bytes

# Batch runs are gated to a sane size for a hackathon demo on free-tier
# LLM/search quotas — each row costs several API calls. Raise this once
# paid keys / higher quotas are in place for a real evaluation run.
MAX_BATCH_ROWS = 25

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

    Extraction (stage 2) now runs all sources CONCURRENTLY via a thread
    pool instead of one at a time — this is the main speed fix. Progress
    events for each source arrive as that source finishes, which may be
    out of order (whichever source responds fastest reports first) —
    that's expected and fine, the frontend just logs each as it arrives.

    Event types: cache_hit, stage_start, source_extracting,
    source_extracted, stage_done, result, error.
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

        # Stage 2: Extraction — CONCURRENT now, not sequential.
        # All sources are submitted to a thread pool at once; we yield a
        # "source_extracting" event for each up front (since they all
        # start together), then a "source_extracted" event as each one
        # actually finishes, in whatever order that happens.
        yield _sse("stage_start", {"stage": "extraction"})
        for source in sources:
            yield _sse("source_extracting", {"url": source.url, "type": source.source_type})

        extractions: list[dict] = [None] * len(sources)
        with ThreadPoolExecutor(max_workers=min(5, len(sources) or 1)) as executor:
            future_to_index = {
                executor.submit(extract_from_source, source, product_input.mpn, product_input.brand): i
                for i, source in enumerate(sources)
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                source = sources[index]
                try:
                    result = future.result()
                except Exception as e:
                    from app.agents.extraction_agent import _empty_result
                    data = _empty_result()
                    data["_error"] = str(e)
                    result = {"source": source, "data": data}
                extractions[index] = result

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


@app.post("/enrich/batch-file")
async def enrich_batch_file(file: UploadFile = File(...)):
    """
    Takes an uploaded CSV/XLSX of raw catalogue rows (Mfg_Part_Num,
    Part_Desc, E1_Brand, Unilog_Brand, DIB_Brand, Part_Manuf — the
    Sample-1000/200-item schema), runs each row through the same
    four-stage pipeline as /enrich, and returns a single XLSX with
    every row mapped into the exact fixed Expected Output headers.

    A row that fails (no MPN, retrieval error, etc.) still gets a row
    in the output — with as many fields populated as could be, an
    error note in LONG_DESC1, and everything else left blank — rather
    than silently dropping it, so partial failures stay visible.
    """
    content = await file.read()
    try:
        raw_rows = read_input_file(content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not raw_rows:
        raise HTTPException(status_code=400, detail="No rows found in the uploaded file.")
    if len(raw_rows) > MAX_BATCH_ROWS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(raw_rows)} rows uploaded, but batch runs are capped at "
                f"{MAX_BATCH_ROWS} rows per request (free-tier API quota). "
                f"Split the file into smaller batches."
            ),
        )

    output_rows: list[dict] = []
    for raw_row in raw_rows:
        try:
            product_input = build_product_input(raw_row)
            cached = cache.get(product_input.mpn, product_input.brand)
            if cached:
                enriched = EnrichedProduct(**cached)
            else:
                enriched = run_pipeline(product_input)
                cache.set(product_input.mpn, product_input.brand, json.loads(enriched.model_dump_json()))
            output_rows.append(map_row_to_headers(raw_row, enriched))
        except Exception as e:
            error_row = {h: "" for h in EXPECTED_HEADERS}
            error_row["Mfg_Part_Num"] = str(raw_row.get("Mfg_Part_Num", ""))
            error_row["Part_Desc"] = str(raw_row.get("Part_Desc", ""))
            error_row["LONG_DESC1"] = f"ERROR: could not process this row — {e}"
            output_rows.append(error_row)

    xlsx_bytes = write_xlsx_bytes(output_rows, EXPECTED_HEADERS)
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=enriched_output.xlsx"},
    )