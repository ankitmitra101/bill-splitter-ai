from unittest.mock import MagicMock, patch
import pytest

from stages.ownership import build_ownership_graph, SemanticBatchResponse, SemanticMatchResult
from schemas.extracted import ParsedDescription, ExtractedReceipt, ExtractedLineItem, ItemAssignment
from schemas.internal import OwnershipMap


@pytest.fixture
def sample_receipt():
    return ExtractedReceipt(
        items=[
            ExtractedLineItem(name="Diet Coke", amount=15000),
            ExtractedLineItem(name="Diet Coke", amount=15000), # Duplicate
            ExtractedLineItem(name="Penne Arrabiata", amount=45000),
            ExtractedLineItem(name="Veg Burger", amount=25000),
            ExtractedLineItem(name="Chocolate Brownie", amount=30000)
        ]
    )

@patch("stages.ownership.genai.Client")
@patch("stages.ownership.config")
def test_exact_and_fuzzy_match(mock_config, mock_client, sample_receipt):
    mock_config.GEMINI_API_KEY = "fake"
    
    parsed = ParsedDescription(
        people=["Aman", "Priya"],
        raw_text="Aman had diet coke and the penne.",
        item_assignments=[
            ItemAssignment(item_ref="Diet Coke", assigned_to=["Aman"]), # Exact
            ItemAssignment(item_ref="penne", assigned_to=["Aman"]) # Fuzzy
        ]
    )
    
    graph = build_ownership_graph(parsed, sample_receipt)
    
    assert len(graph.entries) == 2
    assert graph.entries[0].match_method == "exact"
    assert graph.entries[0].item_index == 0  # Pops the first Diet Coke
    
    assert graph.entries[1].match_method == "fuzzy"
    assert graph.entries[1].item_index == 2  # Penne Arrabiata
    
    # 1 duplicate Diet coke, Burger, Brownie left
    assert len(graph.unresolved_items) == 3
    assert "Diet Coke" in graph.unresolved_items


@patch("stages.ownership.genai.Client")
@patch("stages.ownership.config")
def test_duplicate_receipt_items(mock_config, mock_client, sample_receipt):
    mock_config.GEMINI_API_KEY = "fake"
    
    parsed = ParsedDescription(
        people=["Aman", "Priya"],
        raw_text="Aman had diet coke. Priya had diet coke.",
        item_assignments=[
            ItemAssignment(item_ref="Diet Coke", assigned_to=["Aman"]),
            ItemAssignment(item_ref="Diet Coke", assigned_to=["Priya"]) 
        ]
    )
    
    graph = build_ownership_graph(parsed, sample_receipt)
    
    assert len(graph.entries) == 2
    # Both should map successfully because there are 2 on the receipt
    assert graph.entries[0].item_index == 0
    assert graph.entries[1].item_index == 1
    
    assert len(graph.unresolved_items) == 3


@patch("stages.ownership.genai.Client")
@patch("stages.ownership.config")
def test_semantic_match_and_ambiguity(mock_config, mock_genai_client, sample_receipt):
    mock_config.GEMINI_API_KEY = "fake"
    
    parsed = ParsedDescription(
        people=["Aman", "Priya"],
        raw_text="Aman had dessert. Priya had food.",
        item_assignments=[
            ItemAssignment(item_ref="dessert", assigned_to=["Aman"]), # Should map to Brownie
            ItemAssignment(item_ref="food", assigned_to=["Priya"]) # Ambiguous
        ]
    )
    
    mock_batch_response = SemanticBatchResponse(
        matches=[
            SemanticMatchResult(user_reference="dessert", receipt_item_id=4, ambiguous=False),
            SemanticMatchResult(user_reference="food", receipt_item_id=None, ambiguous=True)
        ]
    )
    
    mock_response = MagicMock()
    mock_response.parsed = mock_batch_response
    mock_models = MagicMock()
    mock_models.generate_content.return_value = mock_response
    
    mock_client_instance = MagicMock()
    mock_client_instance.models = mock_models
    mock_genai_client.return_value = mock_client_instance
    
    graph = build_ownership_graph(parsed, sample_receipt)
    
    assert len(graph.entries) == 1
    assert graph.entries[0].match_method == "semantic"
    assert graph.entries[0].item_index == 4 # Brownie
    assert any("Semantically matched 'dessert'" in f for f in graph.flags)
    
    assert "food" in graph.phantom_items
    assert any("ambiguous" in f for f in graph.flags)


@patch("stages.ownership.genai.Client")
@patch("stages.ownership.config")
def test_everything_else_shared(mock_config, mock_client, sample_receipt):
    mock_config.GEMINI_API_KEY = "fake"
    
    parsed = ParsedDescription(
        people=["Aman", "Priya", "Karan"],
        raw_text="Aman had the burger. The rest was shared.",
        item_assignments=[
            ItemAssignment(item_ref="Veg Burger", assigned_to=["Aman"])
        ],
        shared_with_all=["everything_else"]
    )
    
    graph = build_ownership_graph(parsed, sample_receipt)
    
    assert len(graph.entries) == 5 # 1 explicit, 4 global
    
    # Check the global entries
    global_entries = [e for e in graph.entries if e.match_method is None]
    assert len(global_entries) == 4
    for e in global_entries:
        assert set(e.owners) == {"Aman", "Priya", "Karan"}
        assert e.weights == {"Aman": 1.0, "Priya": 1.0, "Karan": 1.0}
        
    assert len(graph.unresolved_items) == 0


@patch("stages.ownership.genai.Client")
@patch("stages.ownership.config")
def test_weighted_and_incomplete_ownership(mock_config, mock_client, sample_receipt):
    mock_config.GEMINI_API_KEY = "fake"
    
    parsed = ParsedDescription(
        people=["Aman", "Priya"],
        raw_text="Aman had half the burger.",
        item_assignments=[
            ItemAssignment(
                item_ref="Veg Burger", 
                assigned_to=["Aman"],
                quantity_per_person={"Aman": 0.5},
                ownership_incomplete=True
            )
        ]
    )
    
    graph = build_ownership_graph(parsed, sample_receipt)
    
    assert len(graph.entries) == 1
    entry = graph.entries[0]
    
    assert entry.owners == ["Aman"]
    assert entry.weights == {"Aman": 0.5} # Preserves exactly as stated
    assert any("may not reflect actual consumption" in f for f in graph.flags)
