"""
Orchestrator
-------------
Runs the pipeline: Retrieval -> Extraction (+VLM fallback) -> Structuring
-> Confidence Scoring, and assembles the final EnrichedProduct.

Kept as plain sequential Python (no agent framework) on purpose: it's
transparent, easy to debug live during judging, and easy to defend —
"here's exactly what happens at each step" beats a framework black box
for a hackathon Q&A.

Each stage is its own function so `main.py` can call them one at a time
and stream progress events between them (see /enrich/stream). The plain
`run_pipeline` below just calls all four stages back to back for the
non-streaming /enrich endpoint.
"""
from app.schemas import ProductInput, EnrichedProduct, ScoredField, SourceRef, ExtractionStats
from app.agents.retrieval_agent import find_sources
from app.agents.extraction_agent import extract_from_source
from app.agents.confidence_agent import score_field, overall_confidence
from app.agents.taxonomy_agent import classify_category


def _infer_method(source_type: str) -> str:
    if source_type == "pdf_datasheet":
        return "pdf_table"
    return "html_table"


def run_retrieval(product_input: ProductInput) -> list[SourceRef]:
    """Stage 1."""
    return find_sources(product_input.mpn, product_input.brand, product_input.description)


def run_extraction(sources: list[SourceRef], product_input: ProductInput) -> list[dict]:
    """Stage 2 (non-streaming — extracts all sources with no progress callback).
    See main.py's stream generator for the per-source streaming version."""
    return [extract_from_source(s, product_input.mpn, product_input.brand) for s in sources]


def build_candidates(extractions: list[dict], product_input: ProductInput) -> dict:
    """Stage 3: collect all candidate values per field across sources into
    the shape confidence_agent.score_field expects. Also tracks which
    sources actually yielded data vs. failed, so failures are visible
    in the output instead of silently disappearing."""
    title_candidates, category_candidates, description_candidates = [], [], []
    spec_candidates: dict[str, list[dict]] = {}
    all_images: list[str] = []
    failed_urls: list[str] = []
    succeeded = 0

    for item in extractions:
        source = item["source"]
        data = item["data"]
        method = "vlm_image" if data.get("_vlm_used") else _infer_method(source.source_type)

        has_any_field = bool(
            data.get("title") or data.get("category") or data.get("description")
            or (data.get("specifications") or {})
        )
        if data.get("_error") or not has_any_field:
            failed_urls.append(source.url)
        else:
            succeeded += 1

        if data.get("title"):
            title_candidates.append({"value": data["title"], "source": source, "method": method})
        if data.get("category"):
            category_candidates.append({"value": data["category"], "source": source, "method": method})
        if data.get("description"):
            description_candidates.append({"value": data["description"], "source": source, "method": method})
        for spec_name, spec_value in (data.get("specifications") or {}).items():
            if not spec_value:
                continue
            spec_candidates.setdefault(spec_name, []).append(
                {"value": str(spec_value), "source": source, "method": method}
            )
        for img in data.get("image_urls") or []:
            if img not in all_images:
                all_images.append(img)

    if not description_candidates and product_input.description:
        fallback_source = extractions[0]["source"] if extractions else _fallback_source()
        description_candidates = [{
            "value": product_input.description,
            "source": fallback_source,
            "method": "text_parse",
        }]

    return {
        "title": title_candidates,
        "category": category_candidates,
        "description": description_candidates,
        "specifications": spec_candidates,
        "images": all_images,
        "extraction_stats": ExtractionStats(
            sources_attempted=len(extractions),
            sources_succeeded=succeeded,
            sources_failed=len(failed_urls),
            failed_urls=failed_urls,
        ),
    }


def run_scoring(candidates: dict, product_input: ProductInput, sources: list[SourceRef]) -> EnrichedProduct:
    """Stage 4."""
    title_field = score_field(candidates["title"])
    category_field = score_field(candidates["category"])
    description_field = score_field(candidates["description"])
    spec_fields: dict[str, ScoredField] = {
        name: score_field(vals) for name, vals in candidates["specifications"].items()
    }

    # Validate category against the fixed taxonomy rather than shipping
    # whatever free-text an extraction call happened to produce.
    taxonomy_result = classify_category(
        product_input.mpn, product_input.brand, product_input.description,
        category_field.value,
    )
    category_field.value = taxonomy_result["category"]
    if not taxonomy_result["matched"]:
        # No confident taxonomy fit — this is a real signal, not noise,
        # so it drags confidence down and gets flagged for review.
        category_field.confidence = round(min(category_field.confidence, 0.4), 2)
        category_field.confidence_band = "low"
        category_field.needs_review = True
    elif category_field.confidence < 0.65:
        # Taxonomy DID confidently classify it, even if extraction never
        # found explicit category text to score in the first place (common
        # for parts whose datasheets don't literally say "category: X").
        # A successful classification shouldn't be left at the 0%/needs-review
        # defaults that only reflect "no extracted candidate", so give it a
        # sensible floor instead of a false "needs review" signal.
        category_field.confidence = 0.65
        category_field.confidence_band = "medium"
        category_field.needs_review = False
        if not category_field.sources:
            category_field.sources = ["user_input"]  # classified from input, not a scraped source

    all_scored = [title_field, category_field, description_field] + list(spec_fields.values())
    named = {"title": title_field, "category": category_field, "description": description_field, **spec_fields}
    review_flags = [name for name, f in named.items() if f.needs_review]

    return EnrichedProduct(
        mpn=product_input.mpn,
        brand=product_input.brand,
        category=category_field,
        category_matched_taxonomy=taxonomy_result["matched"],
        title=title_field,
        description=description_field,
        specifications=spec_fields,
        images=candidates["images"],
        sources_used=sources,
        extraction_stats=candidates["extraction_stats"],
        overall_confidence=overall_confidence(all_scored),
        review_flagged_fields=review_flags,
    )


def run_pipeline(product_input: ProductInput) -> EnrichedProduct:
    """Runs all four stages back to back — used by the plain /enrich endpoint."""
    sources = run_retrieval(product_input)
    extractions = run_extraction(sources, product_input)
    candidates = build_candidates(extractions, product_input)
    return run_scoring(candidates, product_input, sources)


def _fallback_source():
    return SourceRef(url="user_input", title="User-provided input", source_type="webpage", authority_score=0.3)