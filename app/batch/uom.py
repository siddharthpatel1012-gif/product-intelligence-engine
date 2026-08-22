"""
UOM & Fraction Normalization
-----------------------------
Two things the content guidelines require and nothing in the pipeline
did before this module:

  1. Units written one approved way, always with a space between the
     number and the unit ("24 in", never "24in" or "24 IN." or "24
     inches"). This maps common variants to a single canonical
     abbreviation.

  2. Trade buyers search in fractions, manufacturers publish in
     decimals: 0.5 in -> 1/2 in, 50.25 in -> 50-1/4 in.

HONEST LIMITATION: the real UOM_ALIASES table below is a reasonable,
manually curated set covering the units this pipeline actually
extracts (length, weight, electrical, sound level, etc.) — it is NOT
a verified match against the real ~500-row
Unilog_Master_UOM_Standards_Abbreviations_and_Terms.xlsx, since that
file wasn't available to build against. If/when that file is
supplied, UOM_ALIASES should be regenerated from it directly rather
than hand-maintained.

Fraction conversion, by contrast, is exact — it's pure arithmetic
against 64ths, not a lookup table, so it doesn't have that caveat.
"""
from fractions import Fraction

# lowercased variant -> canonical approved form. Extend as new units
# show up in extracted specs.
UOM_ALIASES: dict[str, str] = {
    # length
    "inch": "in", "inches": "in", "in.": "in", "\"": "in",
    "foot": "ft", "feet": "ft", "ft.": "ft", "'": "ft",
    "millimeter": "mm", "millimetre": "mm", "mm.": "mm",
    "centimeter": "cm", "centimetre": "cm", "cm.": "cm",
    "meter": "m", "metre": "m", "m.": "m",
    # weight
    "pound": "lb", "pounds": "lb", "lbs": "lb", "lb.": "lb",
    "ounce": "oz", "ounces": "oz", "oz.": "oz",
    "kilogram": "kg", "kilograms": "kg", "kg.": "kg",
    "gram": "g", "grams": "g", "g.": "g",
    # electrical
    "volt": "V", "volts": "V", "v.": "V", "vdc": "VDC", "vac": "VAC",
    "amp": "A", "amps": "A", "ampere": "A", "amperes": "A", "a.": "A",
    "watt": "W", "watts": "W", "w.": "W",
    "hertz": "Hz", "hz.": "Hz",
    # sound / misc
    "decibel": "dBA", "decibels": "dBA", "db": "dBA", "dba": "dBA",
    "rpm": "RPM", "revolutions per minute": "RPM",
    "percent": "%", "percentage": "%",
    "degree": "°", "degrees": "°", "deg": "°",
    "gallon": "gal", "gallons": "gal",
    "liter": "L", "litre": "L", "liters": "L", "litres": "L",
}


def normalize_uom(raw_uom: str) -> str:
    """'IN.' -> 'in'; 'Inches' -> 'in'; already-canonical values pass
    through unchanged. Falls back to the original string (trimmed)
    for anything not in the table, rather than guessing."""
    if not raw_uom:
        return ""
    key = raw_uom.strip().lower().rstrip(".")
    return UOM_ALIASES.get(raw_uom.strip().lower(), UOM_ALIASES.get(key, raw_uom.strip()))


# Units where trade buyers conventionally search in fractions rather
# than decimals — per the brief, this is specifically an inches
# convention, not a general rule for every unit.
_FRACTION_ELIGIBLE_UOMS = {"in", "ft"}


def decimal_to_fraction(value: str, denominator: int = 64) -> str:
    """
    '0.5' -> '1/2'; '50.25' -> '50-1/4'; whole numbers and
    already-fractional strings ('1/2', '3-1/4') pass through
    unchanged. Rounds to the nearest 1/64th, matching the
    Decimal_Fraction.xlsx range (1/64 to 63/64).
    """
    if not value:
        return value
    text = value.strip()
    if "/" in text:
        return text  # already a fraction, leave it alone
    try:
        number = float(text)
    except ValueError:
        return text  # not a plain number, leave it alone

    whole = int(number)
    remainder = abs(number - whole)
    if remainder < 1e-9:
        return str(whole)  # exact whole number, no fraction needed

    frac = Fraction(round(remainder * denominator), denominator)
    if frac.numerator == 0:
        return str(whole)
    if frac.numerator == frac.denominator:
        # rounded up to the next whole number, e.g. .995 -> 1
        return str(whole + 1)

    frac_str = f"{frac.numerator}/{frac.denominator}"
    return f"{whole}-{frac_str}" if whole != 0 else frac_str


def normalize_value_uom(value: str, uom: str) -> tuple[str, str]:
    """Apply both normalizations together — this is the function
    row_mapper should call after splitting a raw spec into
    value/uom."""
    clean_uom = normalize_uom(uom)
    clean_value = value
    if clean_uom in _FRACTION_ELIGIBLE_UOMS:
        clean_value = decimal_to_fraction(value)
    return clean_value, clean_uom