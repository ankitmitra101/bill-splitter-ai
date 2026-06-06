# Fair Split API

A robust, AI-powered bill splitting engine that converts messy natural language descriptions and receipt images into mathematically precise, reconcilable settlements. 

**Live Demo:** [https://bill-splitter-ai-n9ds.onrender.com](https://bill-splitter-ai-n9ds.onrender.com)

## 🏗️ Architecture & Philosophy

The system is designed as a deterministic pipeline. To prevent LLM hallucinations from corrupting monetary calculations, the Gemini model is never asked to perform arithmetic.

### The Pipeline Stages
1. **Extraction (AI)**: `gemini-2.5-flash` analyzes the receipt image and returns a strictly typed `ExtractedReceipt` JSON object containing line items, subtotals, and taxes.
2. **Validation (Code)**: Deterministically checks the extracted numbers. Verifies if `sum(line_items) == subtotal`, flags missing service charges, and ensures the math on the printed receipt is internally consistent.
3. **Parsing (AI)**: Translates messy natural language ("Aman had 2 slices, Priya had the rest") into an `OwnershipMap`. Understands group sizes, global sharing rules, and unassigned items.
4. **Ownership Resolution (Code + AI)**: Maps the informal item names from the description to the exact printed receipt items. Uses exact matching, then fuzzy matching, and finally falls back to AI semantic matching only if necessary.
5. **Calculator (Code)**: Completely deterministic. Distributes proportional tax, discounts, and service charges across each line item based on exactly who ate it. Handles fractional paise rounding (e.g., 3-way splits) safely using remainder-distribution.
6. **Reconciliation (Code)**: Enforces a strict invariant: `sum(person_totals) == grand_total`. If they do not match, it explicitly flags the discrepancy (e.g., "₹120 of receipt value remains unassigned").
7. **Settlement (Code)**: Generates point-to-point payments (e.g., `Priya -> Aman ₹547`). If reconciliation fails, settlement is marked as `provisional`.

## 🚀 Running Locally

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd fair_split
   ```

2. **Set up a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables:**
   Create a `.env` file in the root directory:
   ```env
   GEMINI_API_KEY=your_api_key_here
   ```

### Running the App
The backend serves both the API endpoints and the frontend UI.
```bash
uvicorn main:app --reload
```
Navigate to `http://127.0.0.1:8000` to access the Evaluator Dashboard UI.

## 🧪 Testing
The project features 133 unit tests guaranteeing mathematical correctness across extreme edge cases (like distributing ₹100 among 3 people or handling complex Banker's Rounding scenarios).

To run the test suite:
```bash
pip install -r requirements-dev.txt
pytest -v
```

---
*Developed as an internship assignment demonstrating separation of concerns, defensive programming, and reliable LLM orchestration.*
