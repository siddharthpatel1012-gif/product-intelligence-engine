"""
Taxonomy Agent
---------------
Free-text "category" output from extraction isn't commerce-ready on its
own — a real PIM needs categories that map to a fixed taxonomy so
downstream systems (search facets, routing, tax rules) can rely on it.

This agent takes whatever category text extraction produced (plus the
raw input) and classifies it against a small fixed taxonomy using the
configured LLM (Anthropic or Gemini — see llm_client.py), with a
confidence-affecting fallback: if the model can't confidently match
anything in the list, it returns "Uncategorized" rather than inventing
a new leaf category — that's a signal, not a failure, and should reduce
confidence for that field.

Swap TAXONOMY for your own category list to fit whatever product
domain you're demoing (electronics is used here as the default,
matching the sample data).
"""
import json
from app.agents import llm_client

TAXONOMY = [
    # Passive components
    "Resistors", "Capacitors", "Inductors", "Crystals & Oscillators",
    "Transformers", "Ferrites & EMI Suppression",
    # Active / semiconductor
    "Operational Amplifiers", "Diodes", "Transistors", "Microcontrollers",
    "Microprocessors", "Memory ICs", "Logic ICs", "Power Management ICs",
    "Voltage Regulators", "Amplifier ICs", "Interface ICs", "Sensor ICs",
    "RF & Wireless ICs", "Optoelectronics & LEDs",
    # Electromechanical
    "Connectors", "Switches & Relays", "Fuses & Circuit Protection",
    "Motors & Actuators", "Solenoids",
    # Sensing / measurement
    "Sensors", "Encoders",
    # Power
    "Batteries & Power Supplies", "Chargers & Power Adapters",
    # Physical / mechanical
    "Cables & Wire", "Fasteners & Hardware", "Enclosures",
    "Heat Sinks & Thermal Management", "PCB Hardware & Standoffs",
    # Tools / test / misc
    "Tools & Equipment", "Test & Measurement Instruments",
    "Development Boards & Kits", "Antennas",
    "Other Electronic Components",
]

TAXONOMY_SYSTEM_PROMPT = f"""You classify a product into exactly one category \
from this fixed list — never invent a new one:

{json.dumps(TAXONOMY)}

Return ONLY valid JSON, no prose, no markdown fences:
{{"category": "<one of the list above>", "matched": true}}

If nothing in the list is a reasonable fit, return:
{{"category": "Uncategorized", "matched": false}}
"""


def classify_category(mpn: str, brand: str, description: str, extracted_category_hint: str | None) -> dict:
    """
    Returns {"category": str, "matched": bool}. `matched=False` means
    the taxonomy didn't have a confident fit — callers should treat
    that as lower confidence, not hide it.
    """
    user_text = (
        f"MPN: {mpn}\nBrand: {brand}\nDescription: {description}\n"
        f"Extracted category hint (may be empty or noisy): {extracted_category_hint or 'none'}"
    )
    try:
        raw = llm_client.generate(TAXONOMY_SYSTEM_PROMPT, user_text, max_tokens=500)
        print(f"[taxonomy] raw response: {raw!r}")
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(cleaned)
        if result.get("category") not in TAXONOMY:
            print(f"[taxonomy] category '{result.get('category')}' not in fixed list -> Uncategorized")
            return {"category": "Uncategorized", "matched": False}
        return {"category": result["category"], "matched": bool(result.get("matched", True))}
    except Exception as e:
        print(f"[taxonomy] ERROR: {e}")
        return {"category": "Uncategorized", "matched": False}