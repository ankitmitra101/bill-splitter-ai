"""Unit tests for utils/money.py.

Every test in this file exercises pure deterministic arithmetic.
No LLM calls, no I/O, no mocking required.

The critical invariants we verify throughout:
  sum(distribute_proportionally(total, ratios)) == total
  sum(reconcile_to_grand_total(…)) == grand_total_rupees
"""

import pytest
from fractions import Fraction

from utils.money import (
    _standard_round,
    distribute_proportionally,
    reconcile_to_grand_total,
    to_paise,
    to_rupees,
)



# ═══════════════════════════════════════════════════════════════
# to_paise
# ═══════════════════════════════════════════════════════════════


class TestToPaise:
    """Verify rupee → paise conversion."""

    def test_integer_rupees(self):
        assert to_paise(54) == 5400

    def test_float_rupees(self):
        assert to_paise(54.60) == 5460

    def test_zero(self):
        assert to_paise(0) == 0

    def test_small_fraction(self):
        # 0.40 rupees = 40 paise — guards against float artifacts
        assert to_paise(0.40) == 40

    def test_large_amount(self):
        assert to_paise(1_00_000) == 1_00_000_00  # ₹1 lakh

    def test_negative_rupees(self):
        # Discounts can be negative
        assert to_paise(-20) == -2000

    def test_known_float_artifact(self):
        # 0.1 + 0.2 = 0.30000000000000004 in IEEE 754.
        # to_paise must still produce 30.
        assert to_paise(0.1 + 0.2) == 30


# ═══════════════════════════════════════════════════════════════
# to_rupees
# ═══════════════════════════════════════════════════════════════


class TestToRupees:
    """Verify paise → whole-rupee conversion with standard rounding."""

    def test_exact_conversion(self):
        assert to_rupees(5400) == 54

    def test_round_down(self):
        # 5449 paise = 54.49 rupees → rounds to 54
        assert to_rupees(5449) == 54

    def test_round_up(self):
        # 5450 paise = 54.50 rupees → rounds to 55 (standard, not banker's)
        assert to_rupees(5450) == 55

    def test_round_up_high_fraction(self):
        assert to_rupees(5499) == 55

    def test_zero(self):
        assert to_rupees(0) == 0

    def test_negative_round_down(self):
        # -5449 paise = -54.49 → rounds to -54
        assert to_rupees(-5449) == -54

    def test_negative_round_up(self):
        # -5450 paise = -54.50 → rounds to -55 (away from zero)
        assert to_rupees(-5450) == -55

    def test_banker_rounding_avoided(self):
        # Python's round(2.5) = 2 (banker's rounding).
        # We want 250 paise → 3 rupees (standard rounding).
        assert to_rupees(250) == 3

    def test_small_amount(self):
        # 49 paise → 0 rupees
        assert to_rupees(49) == 0

    def test_small_amount_rounds_up(self):
        # 50 paise → 1 rupee
        assert to_rupees(50) == 1


# ═══════════════════════════════════════════════════════════════
# distribute_proportionally
# ═══════════════════════════════════════════════════════════════


class TestDistributeProportionally:
    """Verify the largest-remainder distribution.

    The ONE invariant that must never break:
        sum(result) == total_paise
    """

    # ── Basic cases ──────────────────────────────────────────

    def test_exact_three_way_split(self):
        # 900 / [1,1,1] = 300 each, no remainder
        result = distribute_proportionally(900, [1, 1, 1])
        assert result == [300, 300, 300]
        assert sum(result) == 900

    def test_exact_weighted_split(self):
        # 600 / [1,2,3] = 100, 200, 300
        result = distribute_proportionally(600, [1, 2, 3])
        assert result == [100, 200, 300]
        assert sum(result) == 600

    def test_single_person(self):
        assert distribute_proportionally(5000, [1]) == [5000]

    # ── Remainder distribution ───────────────────────────────

    def test_remainder_one_paisa(self):
        # 10 / [1,1,1]: ideal = 3.333 each, floor = 3 each = 9
        # 1 leftover → goes to first slot (all remainders equal)
        result = distribute_proportionally(10, [1, 1, 1])
        assert sum(result) == 10
        assert result == [4, 3, 3]

    def test_remainder_two_paise(self):
        # 100 / [1,1,1]: ideal = 33.333 each, floor = 33 each = 99
        # 1 leftover → first slot
        result = distribute_proportionally(100, [1, 1, 1])
        assert sum(result) == 100
        assert result == [34, 33, 33]

    def test_remainder_goes_to_largest_fractional(self):
        # 10 / [1,2]: ideal = 3.333, 6.666
        # floor = 3, 6 = 9.  Remainder: 0.333, 0.666
        # 1 leftover → index 1 (larger fractional part)
        result = distribute_proportionally(10, [1, 2])
        assert sum(result) == 10
        assert result == [3, 7]

    def test_many_slots_large_remainder(self):
        # 100 / 7 slots of equal weight
        result = distribute_proportionally(100, [1, 1, 1, 1, 1, 1, 1])
        assert sum(result) == 100
        # 100 / 7 = 14.2857..., floor = 14 each = 98, leftover = 2
        assert result.count(15) == 2
        assert result.count(14) == 5

    def test_odd_among_two(self):
        result = distribute_proportionally(7, [1, 1])
        assert sum(result) == 7
        assert result == [4, 3]

    # ── Weighted with remainder ──────────────────────────────

    def test_weighted_with_remainder(self):
        # 1000 / [3,2,1]: total_ratio=6
        # ideal = 500, 333.33, 166.66
        # floor = 500, 333, 166 = 999.  Leftover = 1
        # remainders = 0, 0.33, 0.66 → index 2 gets extra
        result = distribute_proportionally(1000, [3, 2, 1])
        assert sum(result) == 1000
        assert result == [500, 333, 167]

    def test_realistic_three_person_bill(self):
        # ₹1147 bill (114700 paise) split by pre-tax subtotals
        # Ravi: 440, Neha: 320, Sameer: 280 → ratios [440, 320, 280]
        total = 114700
        ratios = [440, 320, 280]
        result = distribute_proportionally(total, ratios)
        assert sum(result) == total

    # ── Edge cases ───────────────────────────────────────────

    def test_zero_total(self):
        assert distribute_proportionally(0, [1, 2, 3]) == [0, 0, 0]

    def test_empty_ratios(self):
        assert distribute_proportionally(100, []) == []

    def test_all_zero_ratios_equal_fallback(self):
        # When nobody has a subtotal, fall back to equal distribution
        result = distribute_proportionally(100, [0, 0, 0])
        assert sum(result) == 100
        assert result == [34, 33, 33]

    def test_one_zero_ratio_gets_nothing(self):
        # Person with 0 consumption gets 0 tax/service allocation
        result = distribute_proportionally(100, [1, 0, 1])
        assert sum(result) == 100
        assert result[1] == 0
        assert result == [50, 0, 50]

    def test_single_nonzero_ratio_among_zeros(self):
        # Only one person consumed anything
        result = distribute_proportionally(500, [0, 0, 3])
        assert result == [0, 0, 500]

    # ── Negative total (discount allocation) ─────────────────

    def test_negative_total(self):
        # Distributing a -2000 paise discount
        result = distribute_proportionally(-2000, [1, 1])
        assert sum(result) == -2000
        assert result == [-1000, -1000]

    def test_negative_total_with_remainder(self):
        result = distribute_proportionally(-10, [1, 1, 1])
        assert sum(result) == -10
        # Mirrors the positive case: [-4, -3, -3]
        assert result == [-4, -3, -3]

    # ── Validation ───────────────────────────────────────────

    def test_negative_ratio_raises(self):
        with pytest.raises(ValueError, match="ratios must be >= 0"):
            distribute_proportionally(100, [1, -1, 1])

    # ── Scale-equivalent ratios ──────────────────────────────

    def test_scaled_ratios_produce_same_result(self):
        # [1,2,3] and [10,20,30] must produce identical splits
        a = distribute_proportionally(1000, [1, 2, 3])
        b = distribute_proportionally(1000, [10, 20, 30])
        assert a == b

    # ── Stress: exact sum invariant under many configurations ─

    @pytest.mark.parametrize(
        "total,ratios",
        [
            (1, [1, 1]),
            (1, [1, 1, 1, 1, 1]),
            (99, [1, 1, 1]),
            (9999, [3, 5, 7, 11]),
            (100_000, [1]),
            (1, [1]),
            (3, [1, 1]),
        ],
    )
    def test_sum_invariant(self, total, ratios):
        result = distribute_proportionally(total, ratios)
        assert sum(result) == total
        assert len(result) == len(ratios)
        assert all(x >= 0 for x in result)


# ═══════════════════════════════════════════════════════════════
# _standard_round  (Fraction → int, half away from zero)
# ═══════════════════════════════════════════════════════════════


class TestStandardRound:
    """Verify that _standard_round avoids banker's rounding."""

    def test_positive_half_rounds_up(self):
        # 54.5 → 55  (banker's would give 54)
        assert _standard_round(Fraction(109, 2)) == 55

    def test_positive_below_half(self):
        assert _standard_round(Fraction(5449, 100)) == 54

    def test_positive_above_half(self):
        assert _standard_round(Fraction(5451, 100)) == 55

    def test_negative_half_rounds_away_from_zero(self):
        # -54.5 → -55
        assert _standard_round(Fraction(-109, 2)) == -55

    def test_negative_below_half(self):
        # -54.49 → -54
        assert _standard_round(Fraction(-5449, 100)) == -54

    def test_zero(self):
        assert _standard_round(Fraction(0)) == 0

    def test_exact_integer(self):
        assert _standard_round(Fraction(100, 1)) == 100

    def test_banker_rounding_case_250(self):
        # Fraction(5, 2) = 2.5 → should be 3 (not 2 as banker's gives)
        assert _standard_round(Fraction(5, 2)) == 3

    def test_banker_rounding_case_350(self):
        # Fraction(7, 2) = 3.5 → should be 4 (not 4 as banker's also gives)
        assert _standard_round(Fraction(7, 2)) == 4

    def test_one_third(self):
        # 0.333... → 0
        assert _standard_round(Fraction(1, 3)) == 0

    def test_two_thirds(self):
        # 0.666... → 1
        assert _standard_round(Fraction(2, 3)) == 1


# ═══════════════════════════════════════════════════════════════
# reconcile_to_grand_total  (Protocol Steps 3–5)
# ═══════════════════════════════════════════════════════════════


class TestReconcileToGrandTotal:
    """Verify the full reconciliation protocol.

    The ONE invariant:
        sum(final_totals.values()) == grand_total_rupees
    """

    # ── Zero delta (perfect reconciliation) ──────────────────

    def test_exact_match_no_assumptions(self):
        # 3 people, each exactly ₹100 in paise → grand total ₹300
        totals = {
            "Aman": Fraction(10000),
            "Priya": Fraction(10000),
            "Karan": Fraction(10000),
        }
        result, assumptions = reconcile_to_grand_total(totals, 300)
        assert result == {"Aman": 100, "Priya": 100, "Karan": 100}
        assert sum(result.values()) == 300
        assert assumptions == []

    # ── Positive delta (rounding left money on the table) ────

    def test_positive_delta_one_rupee(self):
        # Each person's exact paise rounds DOWN, leaving +1 delta.
        # Aman: 33.33 rupees → 33, Priya: 33.33 → 33, Karan: 33.33 → 33
        # Sum = 99, grand total = 100, delta = +1
        third = Fraction(10000, 3)  # 3333.33 paise = ₹33.33
        totals = {"Aman": third, "Priya": third, "Karan": third}
        result, assumptions = reconcile_to_grand_total(totals, 100)

        assert sum(result.values()) == 100
        # Delta +1 goes to the lowest-total person.
        # All are 33, alphabetical tie-break → Aman gets +1.
        assert result["Aman"] == 34
        assert result["Priya"] == 33
        assert result["Karan"] == 33
        assert len(assumptions) == 1
        assert "+₹1" in assumptions[0]
        assert "Aman" in assumptions[0]

    def test_positive_delta_two_rupees(self):
        # Contrived: 5 people each at 1990 paise (₹19.90 → 20 each = 100)
        # but grand total is 102 → delta = +2
        totals = {
            "Aman": Fraction(1990),
            "Bina": Fraction(1990),
            "Charu": Fraction(1990),
            "Diya": Fraction(1990),
            "Esha": Fraction(1990),
        }
        result, assumptions = reconcile_to_grand_total(totals, 102)
        assert sum(result.values()) == 102
        assert len(assumptions) == 1
        assert "+₹2" in assumptions[0]

    # ── Negative delta (rounding overshot) ───────────────────

    def test_negative_delta_one_rupee(self):
        # Aman: 6666.66 paise = ₹66.67 → 67
        # Priya: 3333.33 paise = ₹33.33 → 33
        # Sum = 100, grand total = 99, delta = -1
        totals = {
            "Aman": Fraction(20000, 3),   # 6666.67 paise
            "Priya": Fraction(10000, 3),  # 3333.33 paise
        }
        result, assumptions = reconcile_to_grand_total(totals, 99)
        assert sum(result.values()) == 99
        # Delta -1 goes to lowest-total person (Priya at 33).
        assert result["Priya"] == 32
        assert result["Aman"] == 67
        assert len(assumptions) == 1
        assert "subtracting" in assumptions[0]
        assert "Priya" in assumptions[0]

    # ── Large delta safety ───────────────────────────────────────

    def test_positive_large_delta(self):
        # Grand total is +120 over the sum.  Delta is 120, > len(people)
        totals = {
            "Aman": Fraction(10000),
            "Priya": Fraction(10000),
        }
        # Provisional = Aman 100, Priya 100. Sum = 200.
        result, assumptions = reconcile_to_grand_total(totals, 320)
        
        # Must NOT distribute.
        assert result["Aman"] == 100
        assert result["Priya"] == 100
        assert len(assumptions) == 1
        assert "A large discrepancy of ₹120 was detected" in assumptions[0]

    def test_negative_large_delta(self):
        # Grand total is 100 under the sum.
        totals = {
            "Aman": Fraction(20000),
            "Priya": Fraction(10000),
        }
        # Provisional = Aman 200, Priya 100. Sum = 300.
        result, assumptions = reconcile_to_grand_total(totals, 200)
        
        # Must NOT distribute.
        assert result["Aman"] == 200
        assert result["Priya"] == 100
        assert len(assumptions) == 1
        assert "A large discrepancy of ₹100 was detected" in assumptions[0]

    # ── Single person ────────────────────────────────────────

    def test_single_person_exact(self):
        totals = {"Solo": Fraction(114700)}
        result, assumptions = reconcile_to_grand_total(totals, 1147)
        assert result == {"Solo": 1147}
        assert assumptions == []

    def test_single_person_with_delta(self):
        # 114733 paise = ₹1147.33 → provisional 1147
        # grand total = 1148 → delta = +1
        totals = {"Solo": Fraction(114733)}
        result, assumptions = reconcile_to_grand_total(totals, 1148)
        assert result == {"Solo": 1148}
        assert sum(result.values()) == 1148

    # ── Empty input ──────────────────────────────────────────

    def test_empty_dict(self):
        result, assumptions = reconcile_to_grand_total({}, 0)
        assert result == {}
        assert assumptions == []

    # ── Tie-breaking: alphabetical order ─────────────────────

    def test_alphabetical_tiebreak(self):
        # Two people with identical provisional totals.
        # Delta = +1 → should go to the alphabetically-first name.
        totals = {
            "Zara": Fraction(5000),   # ₹50
            "Aman": Fraction(5000),   # ₹50
        }
        result, assumptions = reconcile_to_grand_total(totals, 101)
        assert sum(result.values()) == 101
        # Both provisionals are 50.  Alphabetically, Aman < Zara.
        assert result["Aman"] == 51
        assert result["Zara"] == 50

    # ── Assumption message format ────────────────────────────

    def test_assumption_message_positive(self):
        totals = {
            "Aman": Fraction(3300),
            "Priya": Fraction(6600),
        }
        # Aman: 33, Priya: 66, sum = 99, grand = 100, delta = +1
        _, assumptions = reconcile_to_grand_total(totals, 100)
        assert len(assumptions) == 1
        msg = assumptions[0]
        assert "fractional rounding" in msg
        assert "+₹1" in msg
        assert "adding" in msg
        assert "Aman" in msg
        assert "lowest payer" in msg

    def test_assumption_message_negative(self):
        totals = {
            "Aman": Fraction(3350),  # ₹33.5 → 34 (standard)
            "Priya": Fraction(6650),  # ₹66.5 → 67 (standard)
        }
        # Sum = 101, grand = 100, delta = -1
        _, assumptions = reconcile_to_grand_total(totals, 100)
        assert len(assumptions) == 1
        msg = assumptions[0]
        assert "subtracting" in msg
        assert "₹1" in msg

    # ── Sum invariant across many configurations ─────────────

    @pytest.mark.parametrize(
        "totals_paise,grand",
        [
            ({"A": Fraction(10000, 3), "B": Fraction(10000, 3),
              "C": Fraction(10000, 3)}, 100),
            ({"X": Fraction(1)}, 1),
            ({"A": Fraction(7777), "B": Fraction(3333)}, 111),
            ({"A": Fraction(0), "B": Fraction(10000)}, 100),
        ],
    )
    def test_sum_always_equals_grand_total(self, totals_paise, grand):
        result, _ = reconcile_to_grand_total(totals_paise, grand)
        assert sum(result.values()) == grand

