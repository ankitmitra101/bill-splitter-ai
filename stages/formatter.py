"""Stage 8 — Response Formatter.

Converts internal pipeline representations (exact Fractions in paise)
into the final API response (whole rupees, exact JSON contract).

This stage does NO arithmetic beyond converting paise to rupees.
The reconciled totals from Stage 5 are authoritative.
"""

from __future__ import annotations

from fractions import Fraction

from schemas.api import (
    ItemShare,
    PersonBreakdown,
    ReconciliationResult,
    SettleUpEntry,
    SplitResponse,
)
from stages.calculator import CalculatorResult, PersonComponents
from utils.money import standard_round


# ── Helpers ──────────────────────────────────────────────────


def _fraction_to_rupees(paise: Fraction) -> int:
    """Convert exact paise Fraction to nearest whole rupee."""
    return standard_round(paise / Fraction(100))


def _format_person(
    comp: PersonComponents,
    reconciled_total: int,
) -> PersonBreakdown:
    """Build one PersonBreakdown from exact components + authoritative total.

    Each component (subtotal, tax, service, discount) is independently
    rounded to rupees for display.  The `total` field uses the
    reconciled value from Stage 5 — it is NOT the sum of the rounded
    components (that sum may differ by ±₹1 due to independent rounding).

    To keep the breakdown internally consistent, we adjust the largest
    component so that subtotal + tax + service + discount == total.
    """
    subtotal = _fraction_to_rupees(comp.subtotal_paise)
    tax = _fraction_to_rupees(comp.tax_share_paise)
    service = _fraction_to_rupees(comp.service_share_paise)
    discount = _fraction_to_rupees(comp.discount_share_paise)

    # Force consistency: adjust subtotal so components sum to total.
    component_sum = subtotal + tax + service + discount
    if component_sum != reconciled_total:
        subtotal += reconciled_total - component_sum

    items = [
        ItemShare(
            name=item.name,
            amount=_fraction_to_rupees(item.amount_paise),
        )
        for item in comp.items
    ]

    return PersonBreakdown(
        name=comp.name,
        items=items,
        subtotal=subtotal,
        tax_share=tax,
        service_share=service,
        discount_share=discount,
        total=reconciled_total,
    )


# ── Public API ───────────────────────────────────────────────


def format_response(
    calc_result: CalculatorResult,
    reconciliation: ReconciliationResult,
    settle_up: list[SettleUpEntry],
    payer: str | None,
    all_assumptions: list[str],
    all_flags: list[str],
) -> SplitResponse:
    """Assemble the final SplitResponse from all stage outputs.

    This is a pure formatting function — no arithmetic, no LLM calls.
    """
    per_person = [
        _format_person(comp, calc_result.final_totals[comp.name])
        for comp in calc_result.components
    ]

    return SplitResponse(
        per_person=per_person,
        grand_total=calc_result.grand_total_rupees,
        reconciliation=reconciliation,
        paid_by=payer,
        settle_up=settle_up,
        assumptions=all_assumptions,
        flags=all_flags,
    )
