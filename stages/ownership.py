import time
from typing import Any
from pydantic import BaseModel, Field, ValidationError

from google import genai
from google.genai import types

from config import config
from schemas.extracted import ParsedDescription, ExtractedReceipt, ItemAssignment
from schemas.internal import OwnershipMap, OwnershipEntry
from utils.fuzzy_match import match_item, normalize_text

class SemanticMatchResult(BaseModel):
    user_reference: str
    receipt_item_id: int | None = Field(description="The integer ID of the matched receipt item, or null if no match.")
    ambiguous: bool = Field(default=False, description="Set to true if multiple receipt items plausibly match this reference.")

class SemanticBatchResponse(BaseModel):
    matches: list[SemanticMatchResult]

SEMANTIC_PROMPT = """
You are a semantic resolution agent for a bill-splitting application.
Your job is to match a list of user-provided informal item names to a list of available receipt items.

Rules:
1. Only match items if there is a clear semantic link (e.g. "dessert" -> "Chocolate Brownie", "drinks" -> "Diet Coke").
2. If an informal name doesn't logically match any available receipt item, set receipt_item_id to null.
3. If an informal name could plausibly match MULTIPLE available receipt items, set ambiguous to true and receipt_item_id to null. Do NOT silently guess one.
4. You must output valid JSON.
"""

def build_ownership_graph(parsed: ParsedDescription, receipt: ExtractedReceipt) -> OwnershipMap:
    """
    Transforms natural language assignments into a deterministic OwnershipMap.
    Follows a strict 4-stage resolution pipeline: Exact -> Fuzzy -> Semantic -> Phantom.
    """
    entries: list[OwnershipEntry] = []
    unresolved_items: list[str] = []
    phantom_items: list[str] = []
    assumptions: list[str] = parsed.assumptions.copy()
    flags: list[str] = parsed.ambiguities.copy() + parsed.warnings.copy()

    # We track indices to handle duplicate line items perfectly
    available_indices = list(range(len(receipt.items)))
    unresolved_assignments = list(parsed.item_assignments)

    # Helper to convert ItemAssignment to OwnershipEntry
    def create_entry(assignment: ItemAssignment, idx: int, match_method: str):
        item = receipt.items[idx]
        
        # Default weights if None
        weights = assignment.quantity_per_person
        if weights is None:
            weights = {p: 1.0 for p in assignment.assigned_to}
            
        entry = OwnershipEntry(
            item_name=item.name,
            item_index=idx,
            item_amount=item.amount if item.amount is not None else 0,
            owners=assignment.assigned_to,
            weights=weights,
            match_method=match_method,
            note=None
        )
        entries.append(entry)
        
        if assignment.ownership_incomplete:
            if assignment.unallocated_fraction is not None:
                allocated_pct = round((1.0 - assignment.unallocated_fraction) * 100)
                flags.append(f"Ownership incomplete for item '{item.name}'. Only {allocated_pct}% explicitly allocated. Resulting share calculation may not reflect actual consumption.")
            else:
                flags.append(f"Ownership incomplete for item '{item.name}'. Explicit weights used. Resulting share calculation may not reflect actual consumption.")

    # ────────────────────────────────────────────────────────
    # Stage 1: Exact Match
    # ────────────────────────────────────────────────────────
    pending_fuzzy = []
    for assignment in unresolved_assignments:
        norm_ref = normalize_text(assignment.item_ref)
        matched_idx = None
        for idx in available_indices:
            if norm_ref == normalize_text(receipt.items[idx].name):
                matched_idx = idx
                break
                
        if matched_idx is not None:
            available_indices.remove(matched_idx)
            create_entry(assignment, matched_idx, "exact")
        else:
            pending_fuzzy.append(assignment)
            
    # ────────────────────────────────────────────────────────
    # Stage 2: Fuzzy Match
    # ────────────────────────────────────────────────────────
    pending_semantic = []
    for assignment in pending_fuzzy:
        if not available_indices:
            pending_semantic.append(assignment)
            continue
            
        available_names = [receipt.items[i].name for i in available_indices]
        match_result = match_item(assignment.item_ref, available_names)
        
        if match_result.ambiguous:
            flags.append(f"Fuzzy match for '{assignment.item_ref}' was ambiguous among: {match_result.candidate_matches}")
            pending_semantic.append(assignment)
        elif match_result.matched_item:
            # Find the FIRST index matching this name
            matched_idx = None
            for idx in available_indices:
                if receipt.items[idx].name == match_result.matched_item:
                    matched_idx = idx
                    break
            
            if matched_idx is not None:
                available_indices.remove(matched_idx)
                create_entry(assignment, matched_idx, "fuzzy")
            else:
                pending_semantic.append(assignment)
        else:
            pending_semantic.append(assignment)

    # ────────────────────────────────────────────────────────
    # Stage 3: Semantic Match (Gemini)
    # ────────────────────────────────────────────────────────
    semantic_calls_made = 0
    if pending_semantic and available_indices:
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        
        user_refs = [a.item_ref for a in pending_semantic]
        receipt_inventory = [{"id": i, "name": receipt.items[i].name} for i in available_indices]
        
        prompt_content = (
            f"User references to resolve: {user_refs}\n\n"
            f"Available receipt items: {receipt_inventory}"
        )
        
        generation_config = types.GenerateContentConfig(
            temperature=0.0,
            system_instruction=SEMANTIC_PROMPT,
            response_mime_type="application/json",
            response_schema=SemanticBatchResponse,
        )
        
        semantic_result: SemanticBatchResponse | None = None
        try:
            semantic_calls_made += 1
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[prompt_content],
                config=generation_config
            )
            semantic_result = response.parsed
        except Exception as e:
            flags.append(f"Semantic resolution failed due to API error: {e}")
            
        if semantic_result and semantic_result.matches:
            # Map user_ref back to the assignment object
            assignment_map = {a.item_ref: a for a in pending_semantic}
            
            for match in semantic_result.matches:
                assignment = assignment_map.get(match.user_reference)
                if not assignment:
                    continue
                    
                if match.ambiguous:
                    flags.append(f"Semantic match for '{match.user_reference}' was ambiguous.")
                    phantom_items.append(assignment.item_ref)
                elif match.receipt_item_id is not None:
                    idx = match.receipt_item_id
                    if idx in available_indices:
                        available_indices.remove(idx)
                        create_entry(assignment, idx, "semantic")
                        flags.append(f"Semantically matched '{assignment.item_ref}' to '{receipt.items[idx].name}'.")
                    else:
                        flags.append(f"Semantic match returned invalid/already-claimed ID {idx} for '{match.user_reference}'.")
                        phantom_items.append(assignment.item_ref)
                else:
                    phantom_items.append(assignment.item_ref)
                    flags.append(f"No semantic match found for '{assignment.item_ref}'.")
        else:
            # If API fails or returns no matches, they all become phantoms
            for a in pending_semantic:
                phantom_items.append(a.item_ref)
                flags.append(f"No semantic match found for '{a.item_ref}'.")
    else:
        # If no available items left, they all become phantoms
        for a in pending_semantic:
            phantom_items.append(a.item_ref)
            if not available_indices:
                flags.append(f"No receipt items available to match '{a.item_ref}'.")

    # ────────────────────────────────────────────────────────
    # Stage 4: Global Rules & Unresolved Items
    # ────────────────────────────────────────────────────────
    if parsed.shared_with_all:
        for idx in available_indices:
            item = receipt.items[idx]
            weights = {p: 1.0 for p in parsed.people}
            
            entry = OwnershipEntry(
                item_name=item.name,
                item_index=idx,
                item_amount=item.amount if item.amount is not None else 0,
                owners=parsed.people,
                weights=weights,
                match_method=None,
                note="Assigned via global sharing rule."
            )
            entries.append(entry)
        available_indices.clear()
        
    for idx in available_indices:
        unresolved_items.append(receipt.items[idx].name)

    return OwnershipMap(
        entries=entries,
        unresolved_items=unresolved_items,
        phantom_items=phantom_items,
        assumptions=assumptions,
        flags=flags,
        ai_calls=semantic_calls_made
    )
