"""
Row Mapper
-----------
Two directions:

  1. build_product_input(raw_row) — turns one messy input row (the
     Sample-1000/200-item style columns: Mfg_Part_Num, Part_Desc,
     E1_Brand, Unilog_Brand, DIB_Brand, Part_Manuf) into the
     ProductInput the existing pipeline already expects.

  2. map_row_to_headers(raw_row, enriched) — takes the pipeline's
     EnrichedProduct output and writes it into the exact fixed
     header schema (see headers.py) the hackathon grades against.

Deliberately conservative: fields the pipeline has no real evidence
for are left blank rather than guessed, in keeping with "real data is
imperfect — say so" from the brief. A blank cell is honest; an
invented value is a scoring risk.
"""
import re
from app.schemas import ProductInput, EnrichedProduct, ScoredField
from app.batch.headers import EXPECTED_HEADERS
from app.batch.uom import normalize_value_uom

PLACEHOLDER_VALUES = {
    "-- unbranded --", "-- no unilog brand --", "-- no dib brand --",
    "", "n/a", "none", "null",
}

# Columns that should be filled directly from the input row (verbatim,
# untouched) whenever the input file actually has that column.
_PASSTHROUGH_ALIASES = {
    "PART_NUMBER": ["PART_NUMBER"],
    "Dept": ["Dept"],
    "Class": ["Class"],
    "Fine": ["Fine"],
    "SKU - MY_PART_NUMBER": ["SKU - MY_PART_NUMBER", "SKU"],
    "Mfg_Part_Num": ["Mfg_Part_Num"],
    "Part_Desc": ["Part_Desc"],
    "E1_Brand": ["E1_Brand"],
    "Unilog_Brand": ["Unilog_Brand"],
    "DIB_Brand": ["DIB_Brand"],
    "Part_Manuf": ["Part_Manuf"],
}


def _is_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().lower() in PLACEHOLDER_VALUES


def _strip_mfr_code(value: str) -> str:
    """'Freud Inc (2435)' -> 'Freud Inc' — strips a trailing parenthetical
    internal code so the string is usable as a brand/manufacturer name."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", value or "").strip()


def _get_any(raw_row: dict, *keys: str) -> str:
    for k in keys:
        if k in raw_row and raw_row[k] is not None:
            v = str(raw_row[k]).strip()
            if v:
                return v
    return ""


def resolve_brand(raw_row: dict) -> str:
    """Brand resolution order per the brief: prefer a real brand field;
    where an item has no brand, fall back to the manufacturer name."""
    for col in ("E1_Brand", "Unilog_Brand", "DIB_Brand"):
        val = _get_any(raw_row, col)
        if not _is_placeholder(val):
            return val
    manuf = _get_any(raw_row, "Part_Manuf")
    if not _is_placeholder(manuf):
        return _strip_mfr_code(manuf)
    return ""


def build_product_input(raw_row: dict) -> ProductInput:
    mpn = _get_any(raw_row, "Mfg_Part_Num", "MANUFACTURER_PART_NUMBER")
    brand = resolve_brand(raw_row)
    description = _get_any(raw_row, "Part_Desc")
    if not mpn:
        raise ValueError("Row has no Mfg_Part_Num — cannot process without an MPN.")
    if not brand:
        # Pipeline still runs, but retrieval quality drops sharply with
        # no brand at all — worth flagging rather than silently guessing.
        brand = "Unknown"
    return ProductInput(mpn=mpn, brand=brand, description=description or mpn)


def _invoice_desc(title: str) -> str:
    """Invoice Desc rule from the content guidelines: <=40 char, CAPS."""
    return title.upper()[:40].strip()


def _mobile_desc(brand: str, title: str) -> str:
    """Mobile Desc rule: roughly 60-80 char, brand-led."""
    text = f"{brand}, {title}" if brand else title
    return text[:80].strip()


_UNIT_SPLIT_RE = re.compile(r"^\s*([\d.\-/]+)\s*([A-Za-z°%\"'.]+)\s*$")


def _split_value_uom(value: str) -> tuple[str, str]:
    """'120 V' -> ('120', 'V'); 'Stainless Steel' -> ('Stainless Steel', '').
    Also runs the result through normalize_value_uom() so the unit is
    written the single approved way (space-separated, canonical
    abbreviation) and inch measurements convert decimal -> fraction
    per the content guidelines (0.5 -> 1/2, 50.25 -> 50-1/4)."""
    if not value:
        return "", ""
    m = _UNIT_SPLIT_RE.match(value.strip())
    if m:
        raw_value, raw_uom = m.group(1), m.group(2)
        return normalize_value_uom(raw_value, raw_uom)
    return value.strip(), ""


def _find_spec(specs: dict[str, ScoredField], *keywords: str) -> str:
    """Case-insensitive substring lookup across spec field names —
    e.g. _find_spec(specs, 'upc') matches a spec literally named
    'UPC', 'UPC Number', 'upc_code', etc."""
    for name, field in specs.items():
        lname = name.lower()
        if any(kw in lname for kw in keywords) and field.value:
            return field.value
    return ""

def _resolve_manufacturer_name(enriched: EnrichedProduct) -> str:
    """Prefer a brand actually found via extraction (real source
    evidence, scored) over the raw resolved-input-brand fallback,
    when extraction found one with reasonable confidence.

    This fixes a real case seen in testing: Part_Manuf sometimes holds
    a distributor/co-op name rather than the true manufacturer (e.g.
    input says "Appliance Dealers Cooperative", but the manufacturer's
    own page — and extraction — correctly found "Frigidaire"). The
    input-side value is a reasonable fallback when nothing better was
    found, but shouldn't override genuine extracted evidence."""
    extracted = enriched.specifications.get("brand") or enriched.specifications.get("manufacturer")
    if extracted and extracted.value and extracted.confidence >= 0.45:
        return extracted.value
    return enriched.brand
def map_row_to_headers(raw_row: dict, enriched: EnrichedProduct) -> dict:
    row: dict = {h: "" for h in EXPECTED_HEADERS}

    # 1. Passthrough columns — copy the original messy input verbatim.
    for header, aliases in _PASSTHROUGH_ALIASES.items():
        row[header] = _get_any(raw_row, *aliases)

    specs = enriched.specifications

    # 2. Source URLs — manufacturer source first, then up to 5 more.
    manufacturer_sources = [s for s in enriched.sources_used if s.source_type == "manufacturer_page"]
    other_sources = [s for s in enriched.sources_used if s.source_type != "manufacturer_page"]
    if manufacturer_sources:
        row["MFR URL"] = manufacturer_sources[0].url
        ref_pool = manufacturer_sources[1:] + other_sources
    else:
        ref_pool = other_sources
    for i, source in enumerate(ref_pool[:5], start=1):
        row[f"Ref URL {i}"] = source.url

        # 3. Resolved identity fields.
    manufacturer_name = _resolve_manufacturer_name(enriched)
    row["MANUFACTURER_NAME"] = manufacturer_name
    row["BRAND_NAME"] = manufacturer_name
    row["MANUFACTURER_PART_NUMBER"] = enriched.mpn

    # 4. Category / classpath (best-effort — this is the fixed-taxonomy
    # label, NOT a verified Unilog classpath; see known limitations).
    row["Classpath"] = enriched.category.value or ""

    # 5. The five description formats.
    title = enriched.title.value or ""
    description = enriched.description.value or ""
    row["SHORT_DESC"] = title
    row["LONG_DESC1"] = description
    row["INVOICE_DESC"] = _invoice_desc(title) if title else ""
    row["MOBILE_DESC"] = _mobile_desc(enriched.brand, title) if title else ""

    # 6. Item features — up to 20 "Label: Value" bullets from specs.
    for i, (spec_name, field) in enumerate(list(specs.items())[:20], start=1):
        if field.value:
            row[f"ITEM_FEATURES_{i}"] = f"{spec_name}: {field.value}"

    # 7. Attributes — up to 50 Label/Value/UOM triplets from specs.
    for i, (spec_name, field) in enumerate(list(specs.items())[:50], start=1):
        if not field.value:
            continue
        value, uom = _split_value_uom(field.value)
        row[f"ATTRIBUTE_LABEL {i}"] = spec_name
        row[f"ATTRIBUTE_VALUE {i}"] = value
        row[f"ATTRIBUTE_UOM {i}"] = uom

    # 8. Identifiers pulled out of specs when present.
    row["UPC"] = _find_spec(specs, "upc")
    row["EAN"] = _find_spec(specs, "ean")
    row["GTIN"] = _find_spec(specs, "gtin")
    row["UNSPSC"] = _find_spec(specs, "unspsc")
    row["Country Of Origin"] = _find_spec(specs, "country of origin", "country_of_origin")

    # 9. Dimensions, if the extractor found them.
    for dim, keywords in (
        ("LENGTH", ("length",)),
        ("HEIGHT", ("height",)),
        ("WIDTH", ("width",)),
        ("WEIGHT", ("weight",)),
    ):
        raw_dim_value = _find_spec(specs, *keywords)
        if raw_dim_value:
            value, uom = _split_value_uom(raw_dim_value)
            row[dim] = value
            row[f"{dim}_UOM"] = uom

    # 10. Images.
    for i, img_url in enumerate(enriched.images[:5]):
        col = "Product Image" if i == 0 else f"Alternate Image {i}"
        row[col] = img_url
    row["Actual Image (Yes/No)"] = "Yes" if enriched.images else "No"

    return row