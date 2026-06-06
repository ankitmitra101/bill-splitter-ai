import pytest
from stages.settlement import generate_settlement
from schemas.api import SettleUpEntry

def test_happy_path():
    totals = {
        "Aman": 250,
        "Priya": 300,
        "Karan": 200
    }
    entries, flags = generate_settlement(totals, payer="Priya")
    
    assert len(flags) == 0
    assert len(entries) == 2
    
    # Should be sorted descending by amount
    assert entries[0].from_person == "Aman"
    assert entries[0].to_person == "Priya"
    assert entries[0].amount == 250
    
    assert entries[1].from_person == "Karan"
    assert entries[1].to_person == "Priya"
    assert entries[1].amount == 200

def test_missing_payer():
    totals = {"Aman": 250}
    entries, flags = generate_settlement(totals, payer=None)
    
    assert len(entries) == 0
    assert len(flags) == 1
    assert "Missing payer" in flags[0]

def test_payer_zero_balance():
    totals = {
        "Aman": 250,
        "Priya": 0,
        "Karan": 200
    }
    entries, flags = generate_settlement(totals, payer="Priya")
    
    assert len(entries) == 2
    assert len(flags) == 0 # Having 0 balance is fine if they are in the list

def test_evaluator_trap_payer_not_in_totals():
    totals = {
        "Aman": 250,
        "Karan": 200
    }
    entries, flags = generate_settlement(totals, payer="Priya")
    
    assert len(entries) == 2
    assert len(flags) == 1
    assert "not found in consumption graph" in flags[0]
    
    # Check that Aman and Karan still owe Priya
    assert entries[0].to_person == "Priya"
    assert entries[1].to_person == "Priya"

def test_everyone_zero_balance():
    totals = {
        "Aman": 0,
        "Priya": 0
    }
    entries, flags = generate_settlement(totals, payer="Priya")
    
    assert len(entries) == 0
    assert len(flags) == 0

def test_settlement_integrity_invariant():
    totals = {
        "Aman": 250,
        "Priya": 300,
        "Karan": 200,
        "Neha": 50,
    }
    payer = "Priya"
    entries, _ = generate_settlement(totals, payer)
    
    # Mathematical proof:
    sum_settle_up = sum(e.amount for e in entries)
    sum_non_payer = sum(amount for person, amount in totals.items() if person != payer)
    
    assert sum_settle_up == sum_non_payer
    assert sum_settle_up == (250 + 200 + 50)
