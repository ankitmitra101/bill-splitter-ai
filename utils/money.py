"""Deterministic paise-based arithmetic for money calculations.

The assignment FORBIDS the LLM from doing any arithmetic.
Every financial computation flows through this module so that:
  1. All intermediate values are integers (paise) or exact Fractions.
  2. Rounding is explicit — never silent.
  3. Sums are always exact — distribute_proportionally and
     reconcile_to_grand_total both guarantee it.

1 rupee = 100 paise.
"""

import math
from fractions import Fraction


# ── Conversion ───────────────────────────────────────────────


def to_paise(rupees: float | int) -> int:
    """Convert a rupee amount to paise.

    Uses round() to neutralize floating-point artifacts.
    Example: to_paise(54.60) → 5460  (not 5459 or 5461)
    """
    return round(float(rupees) * 100)


def to_rupees(paise: int) -> int:
    """Convert paise to the nearest whole rupee.

    Uses standard rounding (½ rounds away from zero):
      150 paise →  2 rupees
     -150 paise → -2 rupees
      149 paise →  1 rupee

    Python's built-in round() uses banker's rounding (½ rounds to
    even), which we avoid here for predictability.
    """
    if paise >= 0:
        return math.floor(paise / 100 + 0.5)
    return -math.floor(-paise / 100 + 0.5)


# ── Proportional distribution ────────────────────────────────


def distribute_proportionally(
    total_paise: int,
    ratios: list[float],
) -> list[int]:
    """Split total_paise into integer parts whose sum is EXACTLY total_paise.

    Uses the largest-remainder method:
      1. Compute each slot's ideal (fractional) share.
      2. Floor every share to get an initial integer allocation.
      3. The remaining paise go one-by-one to the slots with the
         largest fractional remainders.

    This guarantees sum(result) == total_paise for any input.

    Args:
        total_paise: The amount to distribute (can be negative for
                     discounts — handled by negating, distributing,
                     and negating back).
        ratios:      Relative weights. Only the proportions matter —
                     [1, 2, 3] and [10, 20, 30] give the same split.
                     All values must be >= 0.

    Returns:
        A list of integers, same length as ratios, summing to
        total_paise exactly.

    Raises:
        ValueError: If any ratio is negative.

    Examples:
        >>> distribute_proportionally(100, [1, 1, 1])
        [34, 33, 33]
        >>> distribute_proportionally(10, [1, 2])
        [3, 7]
    """
    if not ratios:
        return []

    if any(r < 0 for r in ratios):
        raise ValueError(f"All ratios must be >= 0, got {ratios}")

    # Handle negative totals (e.g. discount allocation) by symmetry
    if total_paise < 0:
        positive = distribute_proportionally(-total_paise, ratios)
        return [-x for x in positive]

    # Handle zero total — nothing to distribute
    if total_paise == 0:
        return [0] * len(ratios)

    total_ratio = sum(ratios)

    # If all ratios are zero, fall back to equal distribution
    if total_ratio == 0:
        base, leftover = divmod(total_paise, len(ratios))
        result = [base] * len(ratios)
        for i in range(leftover):
            result[i] += 1
        return result

    # Step 1: Compute ideal fractional shares
    ideal = [(r / total_ratio) * total_paise for r in ratios]

    # Step 2: Floor each share
    floored = [math.floor(x) for x in ideal]

    # Step 3: Compute how many paise are left over
    leftover = total_paise - sum(floored)

    # Step 4: Distribute leftovers to slots with the largest remainders.
    #         On ties, earlier indices win (deterministic).
    remainders = [ideal[i] - floored[i] for i in range(len(ratios))]
    ranked = sorted(
        range(len(ratios)),
        key=lambda i: remainders[i],
        reverse=True,
    )

    for i in range(leftover):
        floored[ranked[i]] += 1

    return floored


# ── Fraction-based rounding (Protocol Steps 3–5) ────────────


def _standard_round(value: Fraction) -> int:
    """Round a Fraction to the nearest integer, half away from zero.

    Python's built-in round() uses banker's rounding (half to even),
    which we deliberately avoid for predictability.

    Examples (as Fractions):
        54.5  →  55   (not 54 as banker's would give)
        54.49 →  54
       -54.5  → -55   (away from zero)
    """
    if value >= 0:
        return int(value + Fraction(1, 2))
    return -int(-value + Fraction(1, 2))


def reconcile_to_grand_total(
    exact_totals_paise: dict[str, Fraction],
    grand_total_rupees: int,
) -> tuple[dict[str, int], list[str]]:
    """Steps 3–5 of the Fair Split Mathematical Protocol.

    Takes each person's exact total in paise (as a Fraction — no
    precision lost) and the printed grand total in whole rupees.
    Returns per-person totals in whole rupees whose sum is
    EXACTLY grand_total_rupees.

    Protocol:
        Step 3  — Convert each person's exact paise to a provisional
                  whole-rupee total via standard rounding.
        Step 4  — Delta = grand_total_rupees − sum(provisionals).
        Step 5  — Distribute delta ₹1 at a time to the people with
                  the lowest provisional totals first.

    Args:
        exact_totals_paise: {person_name: exact paise as Fraction}
        grand_total_rupees: The printed grand total in whole rupees.

    Returns:
        (final_totals, assumptions)
        final_totals: {person_name: whole-rupee total} — sum equals
                      grand_total_rupees exactly.
        assumptions:  List of strings describing any rounding
                      adjustments that were made (empty if delta == 0).
    """
    if not exact_totals_paise:
        return {}, []

    # ── Step 3: Provisional rounding ──────────────────────────
    # Divide exact paise by 100 → exact rupees (Fraction).
    # Then standard-round to the nearest whole rupee.
    provisional: dict[str, int] = {}
    for person, paise in exact_totals_paise.items():
        exact_rupees = paise / Fraction(100)
        provisional[person] = _standard_round(exact_rupees)

    # ── Step 4: Delta ─────────────────────────────────────────
    delta = grand_total_rupees - sum(provisional.values())

    if delta == 0:
        return provisional, []

    # ── Guardrail for Massive Discrepancies ───────────────────
    # If delta is strictly larger than the number of people, it is mathematically
    # impossible for it to be a pure fractional rounding artifact.
    # It must be unassigned items, extraction errors, or tax/service mismatches.
    if abs(delta) > len(provisional):
        assumption = (
            f"A large discrepancy of ₹{abs(delta)} was detected "
            "(likely unassigned receipt items). No redistribution was performed."
        )
        return provisional, [assumption]

    # ── Step 5: Fair distribution of delta ────────────────────
    # Sort by provisional total ascending (lowest payers absorb
    # the discrepancy first).  Ties broken alphabetically for
    # determinism.
    sorted_people = sorted(
        provisional.keys(),
        key=lambda p: (provisional[p], p),
    )

    step = 1 if delta > 0 else -1
    adjusted_people: list[str] = []

    remaining = abs(delta)
    idx = 0
    while remaining > 0:
        person = sorted_people[idx % len(sorted_people)]
        provisional[person] += step
        adjusted_people.append(person)
        remaining -= 1
        idx += 1

    # ── Build assumption string ───────────────────────────────
    sign = "+" if delta > 0 else ""
    verb = "adding" if delta > 0 else "subtracting"

    from collections import Counter
    adjustments = Counter(adjusted_people)
    
    parts = []
    # preserve order of first appearance
    seen = set()
    for p in adjusted_people:
        if p not in seen:
            parts.append(f"₹{adjustments[p]} to {p}'s total")
            seen.add(p)

    if len(parts) == 1:
        detail = f"{verb} {parts[0]}"
        qualifier = "(the lowest payer)"
    else:
        detail = f"{verb} " + " and ".join(parts)
        qualifier = "(the lowest payers)"

    assumption = (
        f"Due to fractional rounding or unclaimed items, a {sign}₹{abs(delta)} "
        f"discrepancy was distributed by {detail} {qualifier}."
    )

    return provisional, [assumption]

