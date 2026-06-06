import pytest
from utils.fuzzy_match import match_item

RECEIPT_ITEMS = [
    "Penne Arrabiata",
    "Chocolate Brownie Sundae",
    "Garlic Bread Basket",
    "Chicken Dum Biryani",
    "Veg Pizza",
    "Chicken Pizza",
    "Cold Coffee",
    "Diet Coke 330ml",
    "Masala Dosa",
    "Café Latte",
    "French Fries (Large)",
    "Water Bottle 1L"
]

def test_empty_user_input():
    result = match_item("", RECEIPT_ITEMS)
    assert result.matched_item is None
    assert result.confidence == 0.0

def test_empty_receipt_items():
    result = match_item("Pasta", [])
    assert result.matched_item is None

def test_exact_match_exact_casing():
    result = match_item("Cold Coffee", RECEIPT_ITEMS)
    assert result.matched_item == "Cold Coffee"
    assert result.exact_match is True

def test_exact_match_different_casing():
    result = match_item("cold COFFEE", RECEIPT_ITEMS)
    assert result.matched_item == "Cold Coffee"
    assert result.exact_match is True

def test_punctuation_differences():
    result = match_item("French Fries, Large!", RECEIPT_ITEMS)
    assert result.matched_item == "French Fries (Large)"
    assert result.exact_match is True

def test_singular_plural_match():
    # User says singular, receipt is plural
    result = match_item("French Frie", RECEIPT_ITEMS) # Frie normalizes same as Fries
    assert result.matched_item == "French Fries (Large)"

def test_plural_singular_match():
    # User says plural, receipt is singular
    result = match_item("Masala Dosas", RECEIPT_ITEMS)
    assert result.matched_item == "Masala Dosa"

def test_missing_words():
    result = match_item("brownie", RECEIPT_ITEMS)
    assert result.matched_item == "Chocolate Brownie Sundae"
    assert result.exact_match is False
    assert result.ambiguous is False

def test_extra_words():
    result = match_item("I had the garlic bread basket please", RECEIPT_ITEMS)
    assert result.matched_item == "Garlic Bread Basket"

def test_ambiguity_pizza():
    # User says pizza, both Veg Pizza and Chicken Pizza exist
    result = match_item("pizza", RECEIPT_ITEMS)
    assert result.matched_item is None
    assert result.ambiguous is True
    assert set(result.candidate_matches) == {"Veg Pizza", "Chicken Pizza"}

def test_unicode_normalization():
    result = match_item("Cafe Latte", RECEIPT_ITEMS)
    assert result.matched_item == "Café Latte"
    assert result.exact_match is True

def test_below_threshold_fails():
    # Random text should not match anything confidently
    result = match_item("napkins", RECEIPT_ITEMS, threshold=75.0)
    assert result.matched_item is None
    assert result.confidence < 75.0

def test_abbreviation_match():
    # Diet Coke -> DC? WRatio might struggle with heavy abbreviations,
    # but let's test a common partial "Coke"
    result = match_item("Coke", RECEIPT_ITEMS)
    assert result.matched_item == "Diet Coke 330ml"

def test_duplicate_item_names():
    # Receipt has two exact identical items (e.g., billed twice separately)
    duplicate_receipt = ["Veg Pizza", "Veg Pizza", "Coke"]
    result = match_item("pizza", duplicate_receipt)
    # They are the identical string, so it should technically be ambiguous which line it meant.
    # Actually, process.extract returns the unique strings or indices. 
    # If the strings are identical, it's ambiguous which row.
    assert result.ambiguous is True
    assert len(result.candidate_matches) == 2

def test_very_similar_items():
    similar_receipt = ["Coke 330ml", "Coke 500ml"]
    result = match_item("Coke", similar_receipt)
    assert result.ambiguous is True
    assert set(result.candidate_matches) == {"Coke 330ml", "Coke 500ml"}

def test_semantic_mismatch_failure():
    # RapidFuzz cannot do semantic matching. "Pasta" -> "Penne Arrabiata" shares no tokens.
    # WRatio yields about 67.5 due to partial character overlaps, so it fails a 70.0 threshold.
    result = match_item("Pasta", RECEIPT_ITEMS, threshold=70.0)
    assert result.matched_item is None
    assert result.confidence < 70.0

def test_whitespace_variations():
    result = match_item("  Cold   \n Coffee  ", RECEIPT_ITEMS)
    assert result.matched_item == "Cold Coffee"
    assert result.exact_match is True

def test_substring_overlap_no_ambiguity():
    receipt = ["Cheese Pizza", "Cheese"]
    result = match_item("Cheese Pizza", receipt)
    # Should confidently pick Cheese Pizza over Cheese
    assert result.matched_item == "Cheese Pizza"
    assert result.ambiguous is False

def test_high_threshold_strictness():
    # Enforcing a 95% threshold means missing words fail
    result = match_item("brownie", RECEIPT_ITEMS, threshold=95.0)
    assert result.matched_item is None

def test_custom_ambiguity_margin():
    # If we widen the margin, more things become ambiguous
    receipt = ["Sprite", "Spite"]
    # "Sprit" matches both "Sprite" and "Spite" closely. 
    # With a wide margin, it will flag as ambiguous.
    result = match_item("Sprit", receipt, ambiguity_margin=15.0)
    assert result.ambiguous is True
    assert "Spite" in result.candidate_matches
