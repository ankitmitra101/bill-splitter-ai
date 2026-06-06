"""Public API request and response models.

These define the exact JSON contract the assignment requires.
All monetary amounts in the response are in WHOLE RUPEES.
"""

from pydantic import BaseModel, ConfigDict, Field


# ── Request ──────────────────────────────────────────────────


class SplitRequest(BaseModel):
    """Incoming request body for POST /split."""

    receipt_base64: str = Field(
        ...,
        description="Base64-encoded image bytes. No data-URI prefix.",
    )
    description: str = Field(
        ...,
        description="Plain-English description of who had what and who paid.",
    )


# ── Response building blocks ─────────────────────────────────


class ItemShare(BaseModel):
    """One line-item's share attributed to a single person."""

    name: str
    amount: int  # rupees


class PersonBreakdown(BaseModel):
    """Full per-person financial breakdown."""

    name: str
    items: list[ItemShare]
    subtotal: int         # rupees — sum of item amounts for this person
    tax_share: int        # rupees — proportional GST
    service_share: int    # rupees — proportional service charge
    discount_share: int   # rupees — proportional discount (negative or zero)
    total: int            # rupees — subtotal + tax + service + discount


class ReconciliationResult(BaseModel):
    """Independent arithmetic verification."""

    sum_of_person_totals: int       # rupees
    matches_bill: bool              # strict equality, no tolerance
    discrepancies: list[str] = Field(default_factory=list)


class SettleUpEntry(BaseModel):
    """A single money transfer to settle debts.

    Uses Field aliases so the JSON keys are "from" and "to"
    (Python reserves the word `from`).
    """

    model_config = ConfigDict(populate_by_name=True)

    from_person: str = Field(..., alias="from")
    to_person: str = Field(..., alias="to")
    amount: int  # rupees


# ── Top-level response ───────────────────────────────────────


class Telemetry(BaseModel):
    """Tracks AI usage for the evaluator."""
    receipt_extraction_calls: int = 0
    description_parsing_calls: int = 0
    semantic_matching_calls: int = 0
    total_ai_calls: int = 0


class SplitResponse(BaseModel):
    """The complete response returned by POST /split.

    per_person is a LIST (not a dict) — one PersonBreakdown per diner.
    """

    per_person: list[PersonBreakdown]
    grand_total: int  # rupees
    reconciliation: ReconciliationResult
    paid_by: str | None = None
    settle_up: list[SettleUpEntry] = Field(default_factory=list)
    settlement_status: str = Field(
        default="final",
        description="'final' when reconciliation passes, 'provisional' when unassigned items exist.",
    )
    assumptions: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    telemetry: Telemetry | None = None
