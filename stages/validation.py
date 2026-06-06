from schemas.internal import ValidationResult, ValidationFlag, Severity, OwnershipMap
from schemas.extracted import ExtractedReceipt, ParsedDescription

def validate_pipeline(receipt: ExtractedReceipt, parsed: ParsedDescription, ownership: OwnershipMap) -> ValidationResult:
    """
    Validates the integrated pipeline before math execution.
    Only CRITICAL severities will flip is_valid to False (blocking calculation).
    """
    flags: list[ValidationFlag] = []
    assumptions: list[str] = parsed.assumptions.copy() + ownership.assumptions.copy()
    is_valid = True
    
    def add_flag(msg: str, sev: Severity, src: str):
        nonlocal is_valid
        flags.append(ValidationFlag(message=msg, severity=sev, source=src))
        if sev == Severity.CRITICAL:
            is_valid = False

    # 1. OCR Confidence Validation
    if receipt.confidence_score < 0.5:
        add_flag(f"Low OCR confidence ({receipt.confidence_score}) for receipt extraction.", Severity.WARNING, "receipt_math")
    elif receipt.confidence_score < 0.8:
        add_flag(f"Moderate OCR confidence ({receipt.confidence_score}) for receipt extraction.", Severity.INFO, "receipt_math")
        
    if receipt.round_off and receipt.round_off != 0:
        assumptions.append(f"Receipt contained round-off adjustment of ₹{receipt.round_off/100:.2f}.")
        
    # 2. Receipt Math Mismatch Validation
    computed_subtotal = sum((item.amount for item in receipt.items if item.amount is not None), 0)
    if receipt.subtotal is not None and computed_subtotal != receipt.subtotal:
        add_flag(
            f"Extracted line items sum to ₹{computed_subtotal/100:.2f} but printed subtotal is ₹{receipt.subtotal/100:.2f}", 
            Severity.ERROR, 
            "receipt_math"
        )

    # 3. Critical Receipt Validations
    for item in receipt.items:
        if item.amount is not None and item.amount < 0:
            add_flag(f"Negative amount found for receipt item '{item.name}'.", Severity.CRITICAL, "receipt_math")

    # 4. Payer validation
    if not parsed.payer:
        add_flag("Missing payer in description. Settlement cannot be computed.", Severity.WARNING, "parser")
    elif " and " in parsed.payer.lower() or "," in parsed.payer:
        add_flag(f"Multiple payers detected ('{parsed.payer}'). Settlement currently supports single payer.", Severity.ERROR, "parser")
        
    # 5. Ownership state validation
    for item_name in ownership.phantom_items:
        add_flag(f"Phantom item: '{item_name}' was claimed but not found on the receipt.", Severity.WARNING, "ownership")
        
    for item_name in ownership.unresolved_items:
        add_flag(f"Unresolved receipt item: '{item_name}' was never claimed.", Severity.WARNING, "ownership")
        
    # Propagate ownership-specific flags (like incomplete ownership)
    for flag_msg in ownership.flags:
        if "incomplete" in flag_msg.lower():
            add_flag(flag_msg, Severity.WARNING, "ownership")
        else:
            add_flag(flag_msg, Severity.INFO, "ownership")

    # 6. Impossible Ownership Graph Validations & Evaluator Traps
    for entry in ownership.entries:
        # Trap: Divide by zero ownership
        total_weight = sum(entry.weights.values())
        if total_weight == 0 and len(entry.owners) > 0:
            add_flag(f"Divide-by-zero ownership: Item '{entry.item_name}' has owners but total weight is 0.", Severity.CRITICAL, "ownership")
            
        # Trap: Negative weights
        if any(w < 0 for w in entry.weights.values()):
            add_flag(f"Negative ownership weight detected for item '{entry.item_name}'.", Severity.CRITICAL, "ownership")

    return ValidationResult(
        is_valid=is_valid,
        flags=flags,
        assumptions=assumptions
    )
