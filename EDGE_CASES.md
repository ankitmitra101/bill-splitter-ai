# Edge-Case Handling & Defensive Engineering

During development, we rigorously tested the system to identify edge cases where naive math or simple language models would fail. Below are the key edge cases we identified and how we engineered the Python backend to resolve them.

### 1. Fractional Paisa Rounding (The 1/3 Problem)
**The Problem:** Splitting a ₹100 item equally among 3 people results in ₹33.33 each. `33.33 * 3 = 99.99`. This leaves a ₹0.01 gap, breaking the reconciliation invariant (`sum of parts == grand total`).
**The Solution:** The calculator distributes items internally using integer paise (100 paise = 1 Rupee). The proportional math uses fractions to retain perfect precision until the final step. Any remainder paise (e.g., 1 paisa) are deterministically distributed one by one to the individuals who suffered the largest rounding loss, ensuring the sum perfectly matches the printed total.

### 2. Disconnected Ownership (The Unequal Sharing Problem)
**The Problem:** Given the input *"Aman ate 1 pancake. Priya ate 2 pancakes,"* the LLM would initially generate two separate JSON ownership claims. The Python code would match Aman's claim to the single receipt item, "using it up", and charge Priya nothing.
**The Solution:** We explicitly trained the LLM prompt to group all consumers of the same item into a single array containing relative mathematical `weights` (e.g., Aman: 1, Priya: 2). The Python calculator then splits the single receipt item proportionally (1/3 and 2/3).

### 3. Implicit Group Sizes (The "Three of Us" Problem)
**The Problem:** Input: *"We split it equally among the three of us. Rohit paid."* Because the LLM was restricted from hallucinating names, it only output one participant (`["Rohit"]`) and assigned the entire bill to him.
**The Solution:** We added a `group_size` extraction to the LLM schema. If the LLM returns `group_size: 3` but only names 1 person, a Python post-processing step deterministically generates placeholder profiles (`Person 1`, `Person 2`) so the math divides correctly across the true number of consumers.

### 4. Colloquial Item Naming (The Fuzzy Matching Problem)
**The Problem:** Users rarely use exact receipt names. A user might say "pancake" while the receipt says "Pancake Stack".
**The Solution:** Rather than relying purely on expensive AI semantic matching for every item, we built a fast, deterministic fuzzy-matching utility (`utils/fuzzy_match.py`). It strips articles ("the", "a"), lowercases text, and calculates word overlap. Only if this fails does it escalate to an LLM-driven semantic matching stage.

### 5. Missing / Unclaimed Items (The "Hide the Error" Problem)
**The Problem:** A user forgets to claim an expensive ₹500 item in their description. Early iterations of the code would either try to force a hallucinated match or silently ignore the item, resulting in an unbalanced bill.
**The Solution:** The `reconciliation.py` stage enforces an absolute invariant. If the sum of the people's totals does not equal the receipt's grand total, the API flags a severe warning ("₹500 of receipt value remains unassigned"), explicitly refuses to invent a solution, and marks the settlement array's status as `provisional`. Uncertainty is aggressively surfaced to the UI rather than swept under the rug.
