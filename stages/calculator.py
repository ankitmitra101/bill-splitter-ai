"""Stage 5 — Fair Split Calculator.

Implements the 5-step Mathematical Protocol:

    Step 1  Paise precision: all item amounts start as integer paise;
            every proportion is computed with fractions.Fraction so
            NO precision is ever lost during intermediate calculations.

    Step 2  Exact person total: each person accumulates an exact
            Fraction of paise for every component (items, tax,
            service charge, discount).  Nothing is rounded yet.

    Step 3  Final rupee rounding: each person's exact paise total is
            divided by 100 and standard-rounded (half away from zero)
            to a provisional whole-rupee figure.

    Step 4  Delta calculation: compare the sum of provisionals to
            the printed grand total.

    Step 5  Fair distribution: distribute the delta ₹1 at a time,
            starting from the person with the lowest provisional
            total, so the final sum is EXACTLY the grand total.

This module calls NO LLM.  Every number that leaves this module
is deterministic and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from schemas.internal import OwnershipMap
from schemas.extracted import ExtractedReceipt
from utils.money import _standard_round, reconcile_to_grand_total, to_rupees


# ── Output data structures ───────────────────────────────────
# Plain dataclasses — not Pydantic — because the intermediate
# Fraction values are not JSON-serializable.  The formatter
# stage converts these into the Pydantic API models.


@dataclass
class ItemShareDetail:
    """One item's cost share for a single person, in exact paise."""

    name: str
    amount_paise: Fraction  # exact — no rounding has occurred


@dataclass
class PersonComponents:
    """All exact fractional components for one person (paise).

    Every field is a Fraction so the calculator can sum across
    items, tax, service, and discount without any rounding.
    The only rounding happens in Step 3, on the final total.
    """

    name: str
    items: list[ItemShareDetail] = field(default_factory=list)
    subtotal_paise: Fraction = field(default_factory=Fraction)
    tax_share_paise: Fraction = field(default_factory=Fraction)
    service_share_paise: Fraction = field(default_factory=Fraction)
    discount_share_paise: Fraction = field(default_factory=Fraction)

    @property
    def total_paise(self) -> Fraction:
        """Exact total before any rounding."""
        return (
            self.subtotal_paise
            + self.tax_share_paise
            + self.service_share_paise
            + self.discount_share_paise
        )


@dataclass
class CalculatorResult:
    """Everything the formatter needs to build the API response.

    components      — exact Fraction breakdowns (for display rounding)
    final_totals    — reconciled whole-rupee totals (authoritative)
    grand_total_rupees — the target the final_totals sum to
    assumptions     — rounding / service-charge assumptions
    flags           — anything suspicious detected during calculation
    """

    components: list[PersonComponents]
    final_totals: dict[str, int]   # person → reconciled ₹
    grand_total_rupees: int
    assumptions: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


# ── The calculator ───────────────────────────────────────────


def calculate_splits(
    receipt: ExtractedReceipt,
    ownership: OwnershipMap,
    people: list[str],
) -> CalculatorResult:
    """Run the 5-step Mathematical Protocol.

    Args:
        receipt:    Stage 1 output — the raw extracted receipt.
        ownership:  Stage 4B output — every receipt item mapped to
                    people with consumption weights.
        people:     The full list of diners (may include someone who
                    consumed nothing but is part of the group).

    Returns:
        CalculatorResult with exact breakdowns and reconciled rupee
        totals whose sum is exactly the printed grand total.
    """
    assumptions: list[str] = []
    flags: list[str] = []

    # ────────────────────────────────────────────────────────────
    # Step 1: Distribute each item's paise among its owners using
    #         exact Fraction arithmetic.
    # ────────────────────────────────────────────────────────────

    person_data: dict[str, PersonComponents] = {
        p: PersonComponents(name=p) for p in people
    }

    for entry in ownership.entries:
        # Skip items with no owners or zero cost
        if not entry.owners or entry.item_amount == 0:
            continue

        total_weight = sum(Fraction(w) for w in entry.weights.values())

        if total_weight == 0:
            flags.append(
                f"Item '{entry.item_name}' has owners but all weights "
                f"are 0; skipped from calculation."
            )
            continue

        item_amount = Fraction(entry.item_amount)

        for person in entry.owners:
            weight = Fraction(entry.weights.get(person, 0))
            if weight == 0:
                continue

            share = (weight / total_weight) * item_amount
            person_data[person].items.append(
                ItemShareDetail(name=entry.item_name, amount_paise=share)
            )
            person_data[person].subtotal_paise += share

    # ────────────────────────────────────────────────────────────
    # Step 2: Allocate tax, service charge, and discount
    #         proportionally to each person's pre-tax subtotal.
    #         All arithmetic stays in exact Fractions.
    # ────────────────────────────────────────────────────────────

    total_subtotal = sum(pc.subtotal_paise for pc in person_data.values())

    tax_paise = Fraction(receipt.gst_amount if receipt.gst_amount is not None else 0)
    service_paise = Fraction(
        receipt.service_charge_amount
        if receipt.service_charge_amount is not None
        else 0
    )
    discount_paise = Fraction(
        receipt.discount_amount if receipt.discount_amount is not None else 0
    )

    # Architecture rule: do NOT fabricate a 5% service charge.
    if receipt.service_charge_amount is None:
        assumptions.append(
            "No service charge line detected on receipt; "
            "service charge treated as ₹0."
        )

    for person in people:
        pc = person_data[person]

        # Compute this person's proportion of the total subtotal.
        if total_subtotal > 0:
            ratio = pc.subtotal_paise / total_subtotal
        elif len(people) > 0:
            # Everyone's subtotal is 0 (e.g. fully comped bill).
            # Fall back to equal shares so tax/service still divides.
            ratio = Fraction(1, len(people))
        else:
            ratio = Fraction(0)

        pc.tax_share_paise = ratio * tax_paise
        pc.service_share_paise = ratio * service_paise
        # Discount reduces the person's total → stored as negative.
        pc.discount_share_paise = -(ratio * discount_paise)

    # ────────────────────────────────────────────────────────────
    # Steps 3–5: Round to rupees and reconcile against the
    #            printed grand total.
    # ────────────────────────────────────────────────────────────

    exact_totals: dict[str, Fraction] = {
        p: pc.total_paise for p, pc in person_data.items()
    }

    # Determine the grand total in rupees.
    if receipt.grand_total is not None:
        grand_total_rupees = to_rupees(receipt.grand_total)
    else:
        # No printed grand total — compute from our exact sums
        # and flag the absence.
        total_exact_paise = sum(exact_totals.values())
        grand_total_rupees = _standard_round(total_exact_paise / Fraction(100))
        flags.append(
            "No grand total found on receipt; using computed total "
            f"of ₹{grand_total_rupees}."
        )

    final_totals, reconcile_assumptions = reconcile_to_grand_total(
        exact_totals, grand_total_rupees
    )
    assumptions.extend(reconcile_assumptions)

    return CalculatorResult(
        components=list(person_data.values()),
        final_totals=final_totals,
        grand_total_rupees=grand_total_rupees,
        assumptions=assumptions,
        flags=flags,
    )
