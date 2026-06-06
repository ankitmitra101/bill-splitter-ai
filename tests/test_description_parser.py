from unittest.mock import MagicMock, patch
import pytest

from stages.description_parser import parse_description, LLMParsedDescription, LLMOwnership, LLMConsumerWeight
from schemas.extracted import ParsedDescription


def test_empty_description_short_circuits():
    result = parse_description("")
    assert isinstance(result, ParsedDescription)
    assert result.people == []
    assert result.payer is None
    assert "Description is empty" in result.warnings[0]


@patch("stages.description_parser.genai.Client")
@patch("stages.description_parser.config")
def test_parse_description_success(mock_config, mock_genai_client):
    mock_config.GEMINI_API_KEY = "fake-key"
    mock_config.GEMINI_MODEL = "gemini-2.5-flash"
    mock_config.GEMINI_TEMPERATURE = 0.0
    mock_config.RETRY_BACKOFF_FACTOR = 0.0
    
    mock_parsed = LLMParsedDescription(
        participants=["Aman", "Priya"],
        payer="Priya",
        ownerships=[
            LLMOwnership(
                item_reference="Pasta", 
                consumers=["Aman"], 
                weights=[LLMConsumerWeight(name="Aman", weight=0.5)],
                ownership_incomplete=True,
                unallocated_fraction=0.5
            )
        ],
        global_rules=[],
        warnings=["Pasta ownership is incomplete"]
    )
    
    mock_response = MagicMock()
    mock_response.parsed = mock_parsed
    
    mock_models = MagicMock()
    mock_models.generate_content.return_value = mock_response
    
    mock_client_instance = MagicMock()
    mock_client_instance.models = mock_models
    mock_genai_client.return_value = mock_client_instance
    
    desc_text = "Aman had half the Pasta. Priya paid."
    result = parse_description(desc_text)
    
    assert isinstance(result, ParsedDescription)
    assert result.item_assignments[0].item_ref == "Pasta"
    assert result.item_assignments[0].assigned_to == ["Aman"]
    assert result.item_assignments[0].quantity_per_person == {"Aman": 0.5}
    assert result.item_assignments[0].ownership_incomplete is True
    assert result.item_assignments[0].unallocated_fraction == 0.5
    assert "Pasta ownership is incomplete" in result.warnings


@patch("stages.description_parser.genai.Client")
@patch("stages.description_parser.config")
def test_parse_description_retry_logic(mock_config, mock_genai_client):
    mock_config.GEMINI_API_KEY = "fake-key"
    mock_config.GEMINI_MODEL = "gemini-2.5-flash"
    mock_config.GEMINI_TEMPERATURE = 0.0
    mock_config.RETRY_BACKOFF_FACTOR = 0.0
    
    mock_models = MagicMock()
    mock_models.generate_content.side_effect = ValueError("Schema format error")
    
    mock_client_instance = MagicMock()
    mock_client_instance.models = mock_models
    mock_genai_client.return_value = mock_client_instance
    
    with pytest.raises(RuntimeError):
        parse_description("Aman paid.")
        
    assert mock_models.generate_content.call_count == 2
