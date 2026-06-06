from schemas.api import SettleUpEntry

def generate_settlement(final_totals: dict[str, int], payer: str | None) -> tuple[list[SettleUpEntry], list[str]]:
    """
    Converts per-person final totals into point-to-point SettleUp transactions.
    Assumes a single-payer model.
    """
    flags = []
    
    if not payer:
        flags.append("Missing payer in description. Cannot generate settlement transactions.")
        return [], flags
        
    entries: list[SettleUpEntry] = []
    
    # Clone dict to avoid mutating the original
    working_totals = dict(final_totals)
    
    # Trap: Payer isn't in the consumption graph (they paid but ate nothing)
    if payer not in working_totals:
        flags.append(f"Payer '{payer}' was not found in consumption graph. Adding them with a ₹0 balance.")
        working_totals[payer] = 0
        
    for person, amount in working_totals.items():
        if person == payer:
            continue
            
        if amount > 0:
            entries.append(SettleUpEntry(from_person=person, to_person=payer, amount=amount))
            
    # Sort descending by amount for predictable output
    entries.sort(key=lambda e: e.amount, reverse=True)
    
    return entries, flags
