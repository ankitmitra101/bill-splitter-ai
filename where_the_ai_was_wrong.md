# Where the AI Was Wrong

While building this project, I learned pretty quickly that you can't just blindly trust a language model. I spent a lot of time testing weird edge cases and confusing inputs to see where the AI would break. 

Here are 3 concrete examples of times the model's first answer was completely wrong, how I caught the mistake, and how I fixed my code to handle it.

---

### 1. The Model Couldn't Handle Unequal Sharing

**What happened:**
I tested the description: *"Aman had 1 pancake. Priya had 2 pancakes."*
The model gave me back two separate, disconnected JSON claims: one saying Aman had a pancake, and another saying Priya had a pancake. 

**Why it broke the app:**
My Python code looked at the first claim, found the "Pancake Stack" on the receipt, and assigned the *entire* cost to Aman. By the time it looked at Priya's claim, the pancakes were already "used up" in the code. So Priya got charged ₹0, and Aman paid for everything!

**How I fixed it:**
I realized the AI wasn't structuring the data in a useful way. I updated the prompt to force the LLM to group all consumers of the same item into a single object with `weights` (e.g., `Aman: 1`, `Priya: 2`). I also added a post-processing loop in Python to manually merge duplicate claims just in case the AI ignored the prompt.

---

### 2. The Model Was Too Literal with Item Names

**What happened:**
The receipt image clearly said `Pancake Stack`, but my test description just said *"Aman had 1 pancake."*

**Why it broke the app:**
The AI extracted the item perfectly as "pancake". But my ownership logic tried to find an exact string match on the receipt and failed. The system threw a warning saying "pancake" was a phantom item, and the actual `Pancake Stack` on the receipt was left completely unpaid for. 

**How I fixed it:**
I realized people almost never use the exact wording printed on a receipt. I wrote a deterministic `fuzzy_match.py` utility that strips out articles ("the", "a"), lowercases everything, and scores word overlap. Now, "pancake" easily matches "Pancake Stack" in pure Python, which is faster and saves an extra API call.

---

### 3. The AI Tried to Hide Missing Data

**What happened:**
I wrote a trick test case: *"Aman had the pasta."* But the receipt only had `Brownie`, `Coffee`, and `Garlic Bread`. There was no pasta at all.

**Why it broke the app:**
Early on, my pipeline was too eager to assign ownership. If I wasn't careful, a loose matching algorithm might try to map "pasta" to "Garlic Bread" just to make sure every item was paid for. It would output a mathematically balanced bill that was completely wrong in reality.

**How I fixed it:**
I decided it's much better to be honest about errors than to hallucinate fake answers. I built a strict Reconciliation stage in Python. Now, if an item is claimed but not on the receipt, it's flagged as a `phantom_item`. If the receipt has items left over, the API returns `matches_bill: false` and explicitly tells the user (e.g., *"₹120 of receipt value remains unassigned"*). 

---

**My Biggest Takeaway:** 
The hardest part of this assignment wasn't the arithmetic—it was turning messy human language into a structured graph. I learned that AI is amazing at understanding *intent*, but you have to build strong, traditional Python guardrails around it to keep the math safe and accurate!
