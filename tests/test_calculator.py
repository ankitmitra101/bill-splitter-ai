"""Unit tests for stages/calculator.py (Stage 5).

Tests the full 5-step mathematical protocol end-to-end using
realistic receipt data from the assignment's sample receipts.
"""

import pytest
from fractions import Fraction

from schemas.extracted import ExtractedLineItem, ExtractedReceipt
from schemas.internal import OwnershipEntry, OwnershipMap
from stages.calculator import calculate_splits


# ── Helpers to reduce boilerplate ────────────────────────────


def make_receipt(
    items: list[tuple[str, int, int]],
    subtotal: int,
    service_pct: float | None = None,
    service_amount: int | None = None,
    discount_desc: str | None = None,
    discount_pct: float | None = None,
    discount_amount: int | None = None,
    gst_pct: float | None = None,
    gst_amount: int | None = None,
    round_off: int | None = None,
    grand_total: int | None = None,
) -> ExtractedReceipt:
    """Build a ExtractedReceipt from minimal data.  All amounts in paise."""
    line_items = [
        ExtractedLineItem(name=n, qty=q, amount=a) for n, q, a in items
    ]
    return ExtractedReceipt(
        items=line_items,
        subtotal=subtotal,
        service_charge_pct=service_pct,
        service_charge_amount=service_amount,
        discount_description=discount_desc,
        discount_pct=discount_pct,
        discount_amount=discount_amount,
        gst_pct=gst_pct,
        gst_amount=gst_amount,
        round_off=round_off,
        grand_total=grand_total,
    )


def make_ownership(
    entries: list[tuple[str, int, int, list[str], dict[str, float]]],
) -> OwnershipMap:
    """Build an OwnershipMap from tuples.

    Each tuple: (item_name, item_index, item_amount_paise, owners, weights)
    """
    return OwnershipMap(
        entries=[
            OwnershipEntry(
                item_name=name,
                item_index=idx,
                item_amount=amount,
                owners=owners,
                weights=weights,
            )
            for name, idx, amount, owners, weights in entries
        ]
    )


# ═══════════════════════════════════════════════════════════════
# Basic scenarios
# ═══════════════════════════════════════════════════════════════


class TestCalculatorBasic:
    """Simple cases to verify the pipeline wiring is correct."""

    def test_single_person_gets_everything(self):
        """One diner, one item, no tax/service/discount."""
        receipt = make_receipt(
            items=[("Pizza", 1, 50000)],
            subtotal=50000,
            grand_total=50000,
        )
        ownership = make_ownership([
            ("Pizza", 0, 50000, ["Solo"], {"Solo": 1.0}),
        ])

        result = calculate_splits(receipt, ownership, ["Solo"])

        assert result.final_totals == {"Solo": 500}
        assert result.grand_total_rupees == 500
        assert sum(result.final_totals.values()) == 500

    def test_equal_split_two_people(self):
        """Two people share one item equally."""
        receipt = make_receipt(
            items=[("Pasta", 1, 32000)],
            subtotal=32000,
            grand_total=32000,
        )
        ownership = make_ownership([
            ("Pasta", 0, 32000, ["A", "B"], {"A": 1.0, "B": 1.0}),
        ])

        result = calculate_splits(receipt, ownership, ["A", "B"])
        assert result.final_totals["A"] == 160
        assert result.final_totals["B"] == 160
        assert sum(result.final_totals.values()) == 320

    def test_weighted_split(self):
        """2:1 weighted split of an item."""
        receipt = make_receipt(
            items=[("Beer", 3, 90000)],
            subtotal=90000,
            grand_total=90000,
        )
        ownership = make_ownership([
            ("Beer", 0, 90000, ["Rohit", "Ishan"],
             {"Rohit": 2.0, "Ishan": 1.0}),
        ])

        result = calculate_splits(receipt, ownership, ["Rohit", "Ishan"])
        assert result.final_totals["Rohit"] == 600
        assert result.final_totals["Ishan"] == 300
        assert sum(result.final_totals.values()) == 900


# ═══════════════════════════════════════════════════════════════
# Tax, service, discount allocation
# ═══════════════════════════════════════════════════════════════


class TestCalculatorAllocations:
    """Verify proportional allocation of charges."""

    def test_proportional_tax(self):
        """Tax is allocated proportionally to pre-tax subtotals."""
        receipt = make_receipt(
            items=[("Pizza", 1, 60000), ("Salad", 1, 40000)],
            subtotal=100000,
            gst_amount=5000,  # ₹50 tax
            grand_total=105000,
        )
        ownership = make_ownership([
            ("Pizza", 0, 60000, ["A"], {"A": 1.0}),
            ("Salad", 1, 40000, ["B"], {"B": 1.0}),
        ])

        result = calculate_splits(receipt, ownership, ["A", "B"])

        # A's subtotal = 600, B's = 400 → 60:40 ratio
        # A's tax = 60% of 50 = 30, B's tax = 40% of 50 = 20
        assert sum(result.final_totals.values()) == 1050

        # Verify through components
        comp_a = next(c for c in result.components if c.name == "A")
        comp_b = next(c for c in result.components if c.name == "B")
        assert comp_a.tax_share_paise == Fraction(3000)
        assert comp_b.tax_share_paise == Fraction(2000)

    def test_proportional_discount(self):
        """Discount is allocated proportionally and reduces totals."""
        receipt = make_receipt(
            items=[("A-item", 1, 60000), ("B-item", 1, 40000)],
            subtotal=100000,
            discount_amount=10000,  # ₹100 discount
            grand_total=90000,
        )
        ownership = make_ownership([
            ("A-item", 0, 60000, ["A"], {"A": 1.0}),
            ("B-item", 1, 40000, ["B"], {"B": 1.0}),
        ])

        result = calculate_splits(receipt, ownership, ["A", "B"])
        assert sum(result.final_totals.values()) == 900

        # A gets 60% of discount = -60, B gets 40% = -40
        comp_a = next(c for c in result.components if c.name == "A")
        comp_b = next(c for c in result.components if c.name == "B")
        assert comp_a.discount_share_paise == Fraction(-6000)
        assert comp_b.discount_share_paise == Fraction(-4000)

    def test_no_service_charge_adds_assumption(self):
        """Missing service charge → ₹0, not fabricated 5%."""
        receipt = make_receipt(
            items=[("Item", 1, 100000)],
            subtotal=100000,
            # service_charge_amount is None
            grand_total=100000,
        )
        ownership = make_ownership([
            ("Item", 0, 100000, ["A"], {"A": 1.0}),
        ])

        result = calculate_splits(receipt, ownership, ["A"])

        # Service should be 0, not 5000
        comp = result.components[0]
        assert comp.service_share_paise == Fraction(0)

        # And an assumption should be logged
        assert any("service charge" in a.lower() for a in result.assumptions)


# ═══════════════════════════════════════════════════════════════
# Reconciliation (Steps 3–5 through the calculator)
# ═══════════════════════════════════════════════════════════════


class TestCalculatorReconciliation:
    """Verify the delta distribution works end-to-end."""

    def test_three_way_split_reconciles(self):
        """Classic 3-way split of ₹1000 with remainder."""
        # 100000 paise / 3 = 33333.33 each → provisional 333 each = 999
        # Grand total 1000 → delta +1 → lowest-total person gets +1
        receipt = make_receipt(
            items=[("Shared Meal", 1, 100000)],
            subtotal=100000,
            grand_total=100000,
        )
        ownership = make_ownership([
            ("Shared Meal", 0, 100000, ["A", "B", "C"],
             {"A": 1.0, "B": 1.0, "C": 1.0}),
        ])

        result = calculate_splits(receipt, ownership, ["A", "B", "C"])

        # THE critical invariant
        assert sum(result.final_totals.values()) == 1000

        # One person should have 334, two should have 333
        values = sorted(result.final_totals.values())
        assert values == [333, 333, 334]

    def test_person_with_zero_subtotal(self):
        """Person who consumed nothing still appears with ₹0."""
        receipt = make_receipt(
            items=[("Steak", 1, 80000)],
            subtotal=80000,
            grand_total=80000,
        )
        ownership = make_ownership([
            ("Steak", 0, 80000, ["Eater"], {"Eater": 1.0}),
        ])

        result = calculate_splits(
            receipt, ownership, ["Eater", "Watcher"]
        )

        assert result.final_totals["Eater"] == 800
        assert result.final_totals["Watcher"] == 0
        assert sum(result.final_totals.values()) == 800


# ═══════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════


class TestCalculatorEdgeCases:
    """Unusual inputs that must not crash or produce wrong math."""

    def test_zero_weight_item_flagged(self):
        """Item with all-zero weights should be flagged and skipped."""
        receipt = make_receipt(
            items=[("Ghost", 1, 50000)],
            subtotal=50000,
            grand_total=50000,
        )
        ownership = make_ownership([
            ("Ghost", 0, 50000, ["A"], {"A": 0.0}),
        ])

        result = calculate_splits(receipt, ownership, ["A"])
        assert any("weights are 0" in f for f in result.flags)

    def test_no_grand_total_flags_warning(self):
        """Missing grand total should be computed and flagged."""
        receipt = make_receipt(
            items=[("Item", 1, 50000)],
            subtotal=50000,
            grand_total=None,  # missing!
        )
        ownership = make_ownership([
            ("Item", 0, 50000, ["A"], {"A": 1.0}),
        ])

        result = calculate_splits(receipt, ownership, ["A"])
        assert any("No grand total" in f for f in result.flags)
        # Should still produce a valid total
        assert sum(result.final_totals.values()) == result.grand_total_rupees

    def test_all_items_shared_equally(self):
        """Everyone shared everything — equal per-person totals."""
        receipt = make_receipt(
            items=[("Dish1", 1, 40000), ("Dish2", 1, 60000)],
            subtotal=100000,
            gst_amount=5000,
            grand_total=105000,
        )
        people = ["A", "B"]
        ownership = make_ownership([
            ("Dish1", 0, 40000, people, {"A": 1.0, "B": 1.0}),
            ("Dish2", 1, 60000, people, {"A": 1.0, "B": 1.0}),
        ])

        result = calculate_splits(receipt, ownership, people)
        assert sum(result.final_totals.values()) == 1050
        # Equal shares: each gets 525
        assert result.final_totals["A"] == 525
        assert result.final_totals["B"] == 525
