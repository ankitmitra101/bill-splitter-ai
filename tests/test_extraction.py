from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from google.genai.errors import APIError

from config import config
from schemas.extracted import ExtractedReceipt, ExtractedLineItem
from stages.extraction import extract_receipt, _rupees_to_paise, LLMExtractedReceipt, LLMLineItem


def test_rupees_to_paise():
    """Verify standard float-to-int conversion behaves safely for money."""
    assert _rupees_to_paise(None) is None
    assert _rupees_to_paise(150.50) == 15050
    assert _rupees_to_paise(0.0) == 0
    assert _rupees_to_paise(9.99) == 999
    assert _rupees_to_paise(1.005) == 100


@patch("stages.extraction.genai.Client")
@patch("stages.extraction.config")
def test_extract_receipt_success(mock_config, mock_genai_client):
    """Test successful extraction with native SDK parsed output."""
    mock_config.GEMINI_API_KEY = "fake-key"
    mock_config.GEMINI_MODEL = "gemini-2.5-flash"
    mock_config.GEMINI_TEMPERATURE = 0.0
    mock_config.MAX_RETRIES = 1
    mock_config.RETRY_BACKOFF_FACTOR = 0.0
    
    # Mock the parsed Pydantic object (what google-genai sets on response.parsed)
    mock_parsed = LLMExtractedReceipt(
        restaurant_name="Test Cafe",
        date="2026-06-06",
        items=[
            LLMLineItem(name="Coffee", qty=2, amount=250.50),
            LLMLineItem(name="Cake", qty=1, amount=None)
        ],
        subtotal=250.50,
        grand_total=260.00,
        confidence_score=0.95
    )
    
    mock_response = MagicMock()
    mock_response.parsed = mock_parsed
    
    mock_models = MagicMock()
    mock_models.generate_content.return_value = mock_response
    
    mock_client_instance = MagicMock()
    mock_client_instance.models = mock_models
    mock_genai_client.return_value = mock_client_instance
    
    result = extract_receipt(b"fake_image_bytes")
    
    assert isinstance(result, ExtractedReceipt)
    assert result.restaurant_name == "Test Cafe"
    assert result.subtotal == 25050
    assert result.grand_total == 26000
    assert result.confidence_score == 0.95
    
    assert len(result.items) == 2
    assert result.items[0].name == "Coffee"
    assert result.items[0].amount == 25050


@patch("stages.extraction.genai.Client")
@patch("stages.extraction.config")
def test_extract_receipt_retry_then_success(mock_config, mock_genai_client):
    """Test that a transient failure triggers a retry which succeeds."""
    mock_config.GEMINI_API_KEY = "fake-key"
    mock_config.GEMINI_MODEL = "gemini-2.5-flash"
    mock_config.GEMINI_TEMPERATURE = 0.0
    mock_config.MAX_RETRIES = 3
    mock_config.RETRY_BACKOFF_FACTOR = 0.01
    
    # First response fails to parse
    fail_response = MagicMock()
    fail_response.parsed = None # SDK returns None on parsing failure
    
    success_response = MagicMock()
    success_response.parsed = LLMExtractedReceipt(
        restaurant_name="Retry Cafe",
        items=[LLMLineItem(name="Tea", amount=50.0)]
    )
    
    mock_models = MagicMock()
    mock_models.generate_content.side_effect = [fail_response, success_response]
    
    mock_client_instance = MagicMock()
    mock_client_instance.models = mock_models
    mock_genai_client.return_value = mock_client_instance
    
    result = extract_receipt(b"bytes")
    
    assert result.restaurant_name == "Retry Cafe"
    assert result.items[0].amount == 5000
    assert mock_models.generate_content.call_count == 2


@patch("stages.extraction.genai.Client")
@patch("stages.extraction.config")
def test_extract_receipt_max_retries_exhausted(mock_config, mock_genai_client):
    """Test that exhausting retries raises a RuntimeError."""
    mock_config.GEMINI_API_KEY = "fake-key"
    mock_config.GEMINI_MODEL = "gemini-2.5-flash"
    mock_config.GEMINI_TEMPERATURE = 0.0
    mock_config.MAX_RETRIES = 2
    mock_config.RETRY_BACKOFF_FACTOR = 0.01
    
    # Mocking an APIError which inherits from Exception and is caught by the retry loop
    mock_models = MagicMock()
    mock_models.generate_content.side_effect = ValueError("Some transient validation or parsing error")
    
    mock_client_instance = MagicMock()
    mock_client_instance.models = mock_models
    mock_genai_client.return_value = mock_client_instance
    
    with pytest.raises(RuntimeError) as exc_info:
        extract_receipt(b"bytes")
        
    assert "Failed to extract receipt after 2 attempts" in str(exc_info.value)
    assert mock_models.generate_content.call_count == 2


@patch("stages.extraction.config")
def test_extract_receipt_no_api_key(mock_config):
    """Test that a missing API key fails fast."""
    mock_config.GEMINI_API_KEY = ""
    
    with pytest.raises(ValueError, match="GEMINI_API_KEY is not configured"):
        extract_receipt(b"bytes")
