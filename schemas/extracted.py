"""Models for LLM extraction output.

These represent the structured data returned by the two LLM calls:
  1. Receipt image  →  ExtractedReceipt   (Stage 1)
  2. Description    →  ParsedDescription  (Stage 3)

All monetary fields are stored as int in PAISE (1 rupee = 100 paise).
The extraction stage converts the LLM's rupee values to paise before
populating these models.

The LLM must NEVER perform arithmetic — it only reads and interprets.
"""

from pydantic import BaseModel, Field


# ── Stage 1 output: Receipt extraction ───────────────────────


class ExtractedLineItem(BaseModel):
    """A single line item read from the receipt image."""

    name: str
    qty: int | None = None       # null if not printed or unreadable
    amount: int | None = None    # paise — null if unreadable


class ExtractedReceipt(BaseModel):
    """Structured data extracted from a receipt image.

    Null on any field means "not found on the receipt".
    The LLM must return null rather than guess or compute.
    """

    restaurant_name: str | None = None
    date: str | None = None
    bill_number: str | None = None

    items: list[ExtractedLineItem] = Field(default_factory=list)

    subtotal: int | None = None              # paise
    service_charge_pct: float | None = None  # e.g. 5.0 for 5%
    service_charge_amount: int | None = None # paise
    discount_description: str | None = None  # e.g. "WELCOME15"
    discount_pct: float | None = None        # e.g. 15.0 for 15%
    discount_amount: int | None = None       # paise
    gst_pct: float | None = None             # e.g. 5.0 for 5%
    gst_amount: int | None = None            # paise
    round_off: int | None = None             # paise — can be negative
    grand_total: int | None = None           # paise

    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "LLM's self-reported confidence in extraction quality. "
            "Lower values trigger a flag about unreliable OCR."
        ),
    )
    ai_calls: int = 0


# ── Stage 3 output: Description parsing ──────────────────────


class ItemAssignment(BaseModel):
    """One item-to-people mapping extracted from the description.

    item_ref is the informal name used in the description
    (e.g. "pasta") which Stage 4A will fuzzy-match to a receipt item
    (e.g. "Penne Arrabiata").

    quantity_per_person captures unequal consumption when the
    description is explicit — e.g. "Aman ate 2, Priya ate 1"
    becomes {"Aman": 2.0, "Priya": 1.0}.  If null, equal sharing
    is assumed among assigned_to.
    """

    item_ref: str
    assigned_to: list[str]
    quantity_per_person: dict[str, float] | None = None
    ownership_incomplete: bool = False
    unallocated_fraction: float | None = None


class ParsedDescription(BaseModel):
    """Structured data extracted from the natural-language description.

    The LLM extracts intent only — no arithmetic, no prices.
    Uncertainty is reported through the ambiguities and
    assumptions lists, NOT through free-form text.
    """

    people: list[str] = Field(
        ...,
        description="Every person name found in the description.",
    )
    item_assignments: list[ItemAssignment] = Field(default_factory=list)
    shared_with_all: list[str] = Field(
        default_factory=list,
        description=(
            "Item references described as common/shared among everyone."
        ),
    )
    payer: str | None = None
    raw_text: str = Field(
        ...,
        description="The original description string, preserved verbatim.",
    )
    ambiguities: list[str] = Field(
        default_factory=list,
        description=(
            'Anything the LLM could not resolve with confidence. '
            'e.g. "\'the drinks\' could refer to Lime Soda or Craft Beer"'
        ),
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description=(
            "Interpretation choices the LLM made. "
            'e.g. "\'rest of us\' interpreted as Aman, Priya, Karan"'
        ),
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Contradictions, missing critical data, or rule violations.",
    )
    ai_calls: int = 0
