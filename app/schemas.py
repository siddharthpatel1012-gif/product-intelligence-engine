from typing import Optional
from pydantic import BaseModel, Field


class ProductInput(BaseModel):
    """The minimal input the challenge specifies."""
    mpn: str = Field(..., description="Manufacturer part number")
    brand: str = Field(..., description="Brand / manufacturer name")
    description: str = Field(..., description="One-line description, if available")


class SourceRef(BaseModel):
    url: str
    title: Optional[str] = None
    source_type: str = Field(
        default="webpage",
        description="webpage | pdf_datasheet | distributor_listing | manufacturer_page",
    )
    authority_score: float = Field(
        default=0.5,
        description="0-1 heuristic trust score for this source (manufacturer > distributor > generic web)",
    )


class FieldValue(BaseModel):
    """A single extracted field, with provenance, before scoring."""
    value: str
    source_url: str
    extraction_method: str = Field(
        description="text_parse | html_table | pdf_table | vlm_image"
    )


class ConfidenceBreakdown(BaseModel):
    """Explains how a field's confidence score was computed — shown in the
    UI as a tooltip so the score isn't a black box."""
    source_authority: float = 0.0
    agreement_bonus: float = 0.0
    method_bonus: float = 0.0
    conflicting_sources: bool = False
    contributing_sources: int = 0


class ScoredField(BaseModel):
    """A field after structuring + confidence scoring — what ships to the client."""
    value: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_band: str = Field(description="high | medium | low")
    sources: list[str] = Field(default_factory=list)
    needs_review: bool = False
    breakdown: ConfidenceBreakdown = Field(default_factory=ConfidenceBreakdown)


class ExtractionStats(BaseModel):
    sources_attempted: int = 0
    sources_succeeded: int = 0
    sources_failed: int = 0
    failed_urls: list[str] = Field(default_factory=list)


class EnrichedProduct(BaseModel):
    mpn: str
    brand: str
    category: ScoredField
    category_matched_taxonomy: bool = Field(
        default=True,
        description="False if no fixed taxonomy category was a confident fit (value falls back to 'Uncategorized')",
    )
    title: ScoredField
    description: ScoredField
    specifications: dict[str, ScoredField] = Field(default_factory=dict)
    images: list[str] = Field(default_factory=list)
    sources_used: list[SourceRef] = Field(default_factory=list)
    extraction_stats: ExtractionStats = Field(default_factory=ExtractionStats)
    overall_confidence: float = Field(ge=0.0, le=1.0)
    review_flagged_fields: list[str] = Field(default_factory=list)
