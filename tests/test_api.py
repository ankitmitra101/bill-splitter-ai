from unittest.mock import patch
from fastapi.testclient import TestClient
import base64

from main import app
from schemas.extracted import ExtractedReceipt, ParsedDescription, ExtractedLineItem, ItemAssignment

client = TestClient(app)

valid_b64 = base64.b64encode(b"fake image data").decode('utf-8')

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_invalid_base64():
    response = client.post("/split", json={
        "receipt_base64": "this is not valid base64!@#$",
        "description": "Aman paid"
    })
    assert response.status_code == 400
    assert "Invalid base64" in response.json()["detail"]

@patch("main.extract_receipt")
def test_422_not_a_receipt(mock_extract):
    # Valid confidence, but no items and no total
    mock_extract.return_value = ExtractedReceipt(confidence_score=0.9)
    response = client.post("/split", json={
        "receipt_base64": valid_b64,
        "description": "Aman paid"
    })
    assert response.status_code == 422
    assert "no items or total found" in response.json()["detail"]
    
@patch("main.extract_receipt")
def test_422_low_confidence(mock_extract):
    # Has items, but confidence is too low
    mock_extract.return_value = ExtractedReceipt(confidence_score=0.1, items=[ExtractedLineItem(name="Dog", amount=1000)])
    response = client.post("/split", json={
        "receipt_base64": valid_b64,
        "description": "Aman paid"
    })
    assert response.status_code == 422
    assert "confidence too low" in response.json()["detail"]

@patch("main.extract_receipt")
@patch("main.parse_description")
def test_happy_path_integration(mock_parse, mock_extract):
    mock_extract.return_value = ExtractedReceipt(
        items=[ExtractedLineItem(name="Pizza", amount=50000)],
        subtotal=50000,
        grand_total=50000,
        confidence_score=0.95
    )
    mock_parse.return_value = ParsedDescription(
        people=["Aman", "Priya"],
        payer="Priya",
        raw_text="Aman had Pizza. Priya paid.",
        item_assignments=[
            ItemAssignment(item_ref="Pizza", assigned_to=["Aman"], quantity_per_person=None)
        ]
    )
    
    response = client.post("/split", json={
        "receipt_base64": valid_b64,
        "description": "Aman had Pizza. Priya paid."
    })
    
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["grand_total"] == 500
    assert data["paid_by"] == "Priya"
    assert len(data["per_person"]) == 2
    
    # Check that Aman was billed 500, Priya 0
    aman = next(p for p in data["per_person"] if p["name"] == "Aman")
    assert aman["total"] == 500
    priya = next(p for p in data["per_person"] if p["name"] == "Priya")
    assert priya["total"] == 0
    
    assert data["reconciliation"]["matches_bill"] is True
    assert data["settlement_status"] == "final"
    
    # Settlement: Aman owes Priya 500
    assert len(data["settle_up"]) == 1
    assert data["settle_up"][0]["from"] == "Aman"
    assert data["settle_up"][0]["to"] == "Priya"
    assert data["settle_up"][0]["amount"] == 500

@patch("main.extract_receipt")
@patch("main.parse_description")
def test_critical_validation_error_400(mock_parse, mock_extract):
    # Setup an impossible ownership graph (negative weight)
    mock_extract.return_value = ExtractedReceipt(
        items=[ExtractedLineItem(name="Pizza", amount=50000)],
        subtotal=50000,
        grand_total=50000,
        confidence_score=0.95
    )
    mock_parse.return_value = ParsedDescription(
        people=["Aman"],
        payer="Aman",
        raw_text="Aman paid.",
        item_assignments=[
            ItemAssignment(item_ref="Pizza", assigned_to=["Aman"], quantity_per_person={"Aman": -1.0}) # Critical error!
        ]
    )
    
    response = client.post("/split", json={
        "receipt_base64": valid_b64,
        "description": "Aman paid."
    })
    
    assert response.status_code == 400
    assert "critical errors" in response.json()["detail"]
    assert "Negative ownership weight" in response.json()["detail"]

@patch("main.extract_receipt")
@patch("main.parse_description")
def test_provisional_settlement_on_unassigned_items(mock_parse, mock_extract):
    """When receipt items are unassigned, settlement_status must be 'provisional'."""
    mock_extract.return_value = ExtractedReceipt(
        items=[
            ExtractedLineItem(name="Pizza", amount=50000),
            ExtractedLineItem(name="Coffee", amount=12000),
        ],
        subtotal=62000,
        grand_total=62000,
        confidence_score=0.95
    )
    mock_parse.return_value = ParsedDescription(
        people=["Aman", "Priya"],
        payer="Priya",
        raw_text="Aman had Pizza. Priya paid.",
        item_assignments=[
            ItemAssignment(item_ref="Pizza", assigned_to=["Aman"])
        ]
    )
    
    response = client.post("/split", json={
        "receipt_base64": valid_b64,
        "description": "Aman had Pizza. Priya paid."
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["reconciliation"]["matches_bill"] is False
    assert data["settlement_status"] == "provisional"
    assert any("unassigned" in d for d in data["reconciliation"]["discrepancies"])
    assert any("provisional" in f.lower() for f in data["flags"])
