import pytest
from stages.validation import validate_pipeline
from schemas.internal import Severity, OwnershipMap, OwnershipEntry
from schemas.extracted import ExtractedReceipt, ParsedDescription, ExtractedLineItem

def test_happy_path():
    receipt = ExtractedReceipt(
        items=[ExtractedLineItem(name="Pizza", amount=50000)],
        subtotal=50000,
        confidence_score=0.95
    )
    parsed = ParsedDescription(people=["Aman"], payer="Aman", raw_text="Aman paid.")
    ownership = OwnershipMap(
        entries=[OwnershipEntry(item_name="Pizza", item_index=0, item_amount=50000, owners=["Aman"], weights={"Aman": 1.0})]
    )
    
    result = validate_pipeline(receipt, parsed, ownership)
    
    assert result.is_valid is True
    assert len(result.flags) == 0

def test_math_mismatch_is_error_but_valid():
    receipt = ExtractedReceipt(
        items=[ExtractedLineItem(name="Pizza", amount=50000)],
        subtotal=52000, # Mismatch!
        confidence_score=0.95
    )
    parsed = ParsedDescription(people=["Aman"], payer="Aman", raw_text="")
    ownership = OwnershipMap()
    
    result = validate_pipeline(receipt, parsed, ownership)
    
    assert result.is_valid is True # Does not stop calculator
    
    math_flags = [f for f in result.flags if f.severity == Severity.ERROR]
    assert len(math_flags) == 1
    assert "sum to ₹500.00 but printed subtotal is ₹520.00" in math_flags[0].message

def test_critical_stops_calculator():
    receipt = ExtractedReceipt(
        items=[ExtractedLineItem(name="Pizza", amount=-5000)], # Negative!
        confidence_score=0.95
    )
    parsed = ParsedDescription(people=["Aman"], payer="Aman", raw_text="")
    ownership = OwnershipMap()
    
    result = validate_pipeline(receipt, parsed, ownership)
    
    assert result.is_valid is False
    assert any(f.severity == Severity.CRITICAL and "Negative" in f.message for f in result.flags)

def test_low_confidence_warning():
    receipt = ExtractedReceipt(confidence_score=0.42)
    parsed = ParsedDescription(people=["Aman"], payer="Aman", raw_text="")
    ownership = OwnershipMap()
    
    result = validate_pipeline(receipt, parsed, ownership)
    
    assert result.is_valid is True
    assert any(f.severity == Severity.WARNING and "Low OCR confidence" in f.message for f in result.flags)

def test_payer_validations():
    receipt = ExtractedReceipt(confidence_score=0.9)
    # Missing payer
    parsed1 = ParsedDescription(people=["Aman"], payer=None, raw_text="")
    res1 = validate_pipeline(receipt, parsed1, OwnershipMap())
    assert any(f.severity == Severity.WARNING and "Missing payer" in f.message for f in res1.flags)
    
    # Multiple payers
    parsed2 = ParsedDescription(people=["Aman"], payer="Aman and Priya", raw_text="")
    res2 = validate_pipeline(receipt, parsed2, OwnershipMap())
    assert any(f.severity == Severity.ERROR and "Multiple payers" in f.message for f in res2.flags)
def test_evaluator_trap_divide_by_zero():
    receipt = ExtractedReceipt(confidence_score=0.9)
    parsed = ParsedDescription(people=["Aman"], payer="Aman", raw_text="")
    ownership = OwnershipMap(
        entries=[
            OwnershipEntry(
                item_name="Pasta", 
                item_index=0, 
                item_amount=20000, 
                owners=["Aman"], 
                weights={"Aman": 0.0} # Divide by zero trap!
            )
        ]
    )
    
    result = validate_pipeline(receipt, parsed, ownership)
    assert result.is_valid is False
    assert any(f.severity == Severity.CRITICAL and "Divide-by-zero" in f.message for f in result.flags)
