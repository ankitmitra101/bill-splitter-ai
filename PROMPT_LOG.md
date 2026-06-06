# Prompt Log & Iteration History

This document tracks the evolution of the LLM prompts used in this project, specifically detailing how the Natural Language Understanding (NLU) component was refined to handle edge cases safely.

## Prompt Iterations for the Description Parser

1. **V1 (Initial Attempt):** Extract a flat list of people, items, and the payer. *(Result: Too unstructured, difficult to map to receipt).*
2. **V2 (Schema Enforcement):** Enforced a strict Pydantic JSON schema so the Python code wouldn't break on parsing. *(Result: Better, but still hallucinated items).*
3. **V3 (Banned Receipt Matching):** Prevented the LLM from trying to map natural language directly to receipt items. *(Result: Moved matching strictly into deterministic Python, greatly improving accuracy).*
4. **V4 (Uncertainty Tracking):** Added `ambiguities` and `assumptions` arrays to the JSON schema so the model could surface confusion instead of silently guessing.
5. **V5 (Pronoun Restrictions):** Banned the LLM from trying to invent placeholder names when encountering pronouns ("we", "everyone"), enforcing phantom-item tracking instead.
6. **V6 (Unequal Sharing Support):** Forced the model to group consumers of the same item into a single assignment array with specific mathematical `weights` (e.g. "Aman ate 2, Priya ate 1") rather than creating disjointed, overlapping claims.
7. **V7 (Explicit Group Sizing):** Added a `group_size` extraction rule to handle phrases like "split among the 3 of us", allowing the Python backend to dynamically generate missing placeholder participants.

---

## Architectural Decision: AI vs. Code

**Question:** *Did you let the model do the arithmetic, or extract structured data and compute the totals in code? Why?*

**Answer:** I explicitly **extracted structured data and computed the totals purely in Python code**. 

**Why?** Language models are probabilistic pattern matchers, not calculators. They are notoriously bad at precise arithmetic, especially when dealing with floating-point currencies, proportional tax distribution, and Banker's Rounding. By restricting the Gemini LLM exclusively to Natural Language Understanding (NLU)—extracting intent, structure, and entity relationships—I eliminated the risk of hallucinated math. All financial calculations happen deterministically in `calculator.py`. This guarantees that the sum of the individual splits will always equal the exact grand total printed on the receipt, ensuring 100% financial accuracy and strict auditability.
