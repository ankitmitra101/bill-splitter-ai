"""Internal pipeline models.

These flow between stages inside the pipeline and are NEVER
serialized to the API response.  All monetary fields are in PAISE.
"""

from pydantic import BaseModel, Field

from schemas.extracted import ExtractedLineItem, ExtractedReceipt


from enum import Enum

class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class ValidationFlag(BaseModel):
    message: str
    severity: Severity
    source: str

class ValidationResult(BaseModel):
    is_valid: bool
    flags: list[ValidationFlag] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

# ── Stage 2 output: Validated receipt ────────────────────────


class ValidatedReceipt(BaseModel):
    """Receipt after deterministic arithmetic validation.

    The original extracted data is preserved untouched in `receipt`.
    Computed values and discrepancies are stored separately so
    nothing is silently overwritten.
    """

    receipt: ExtractedReceipt

    # Fields we can compute ourselves from line items
    computed_subtotal: int                    # paise — sum of item amounts
    computed_service: int | None = None       # paise — from pct × subtotal
    computed_gst: int | None = None           # paise — from pct × base
    computed_grand_total: int | None = None   # paise — full recomputation

    validation_flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


# ── Stage 4A output: Item matching ───────────────────────────


class MatchedItem(BaseModel):
    """A description's item_ref resolved to a specific receipt line item.

    Stage 4A performs fuzzy matching only — it does not determine
    ownership or weights.
    """

    description_ref: str       # the informal name, e.g. "pasta"
    receipt_item_name: str     # the exact receipt name, e.g. "Penne Arrabiata"
    receipt_item_index: int    # position in ExtractedReceipt.items
    match_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Fuzzy-match confidence. Below 0.5 triggers a flag.",
    )


# ── Stage 4B output: Ownership resolution ────────────────────


class OwnershipEntry(BaseModel):
    """A receipt line item mapped to its consumers with weights.

    `weights` expresses how the item's cost is divided.
    Equal sharing:   {"Aman": 1.0, "Priya": 1.0}
    Weighted sharing: {"Aman": 2.0, "Priya": 1.0}  (2:1 ratio)

    The calculator stage normalizes these weights into ratios
    and distributes the item's amount in paise accordingly.
    """

    item_name: str
    item_index: int       # position in ExtractedReceipt.items
    item_amount: int      # paise — total amount for this line item
    owners: list[str]
    weights: dict[str, float] = Field(
        ...,
        description=(
            "Consumption weights per person. Values are relative — "
            "{A: 1, B: 1} and {A: 5, B: 5} both mean 50/50."
        ),
    )
    match_method: str | None = Field(
        default=None,
        description="How this item was resolved: 'exact', 'fuzzy', or 'semantic'. None for global rules."
    )
    note: str | None = None


class OwnershipMap(BaseModel):
    """Complete ownership resolution across all receipt line items."""

    entries: list[OwnershipEntry] = Field(default_factory=list)

    unresolved_items: list[str] = Field(
        default_factory=list,
        description="Receipt items that no one in the description claimed.",
    )
    phantom_items: list[str] = Field(
        default_factory=list,
        description="Items mentioned in the description but not on the receipt.",
    )

    assumptions: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    ai_calls: int = 0


# ── Stage 5 output: Per-person split in paise ────────────────


class ItemSharePaise(BaseModel):
    """One item's cost share for a single person, in paise."""

    name: str
    amount_paise: int


class PersonSplitPaise(BaseModel):
    """Full per-person financial breakdown in paise.

    This is the internal representation.  The formatter stage
    converts it to whole rupees for the API response.
    """

    name: str
    items: list[ItemSharePaise] = Field(default_factory=list)
    subtotal_paise: int        # sum of item shares
    tax_share_paise: int       # proportional GST
    service_share_paise: int   # proportional service charge
    discount_share_paise: int  # proportional discount (negative or zero)
    total_paise: int           # subtotal + tax + service + discount
