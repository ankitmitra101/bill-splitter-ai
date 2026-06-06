import time
from typing import Any
from pydantic import BaseModel, Field, ValidationError

from google import genai
from google.genai import types
from google.genai.errors import APIError

from config import config
from schemas.extracted import ParsedDescription, ItemAssignment


DESCRIPTION_PARSER_PROMPT = """
You are a highly analytical natural language processing agent for a bill splitting application.
Your goal is to extract a complete ownership graph from messy natural language while preserving uncertainty.

The parser must NEVER invent facts or invent ownership.
If information is unclear:
- ambiguity -> ambiguities[]
- interpretation -> assumptions[]
- contradiction -> warnings[]
Never silently guess.

Rules:
1. Extract the exact names of the Participants. Only infer participants when explicitly named.
2. Identify the Payer. If no payer is identified, output payer=null and add a warning. If multiple payers are listed, output payer=null and add a warning.
3. Extract explicit or shared ownership assignments mapping an item_reference directly to a list of consumers. IMPORTANT: You MUST group all consumers of the same item into a SINGLE ownership assignment. Never create multiple assignments for the same item_reference.
4. Extract global sharing rules exactly as stated (e.g. "everything_else_shared"). Do NOT expand global rules into item ownerships.
5. Do NOT attempt fuzzy matching of item names. Store the raw item references exactly as they appear in text.
6. Pronouns (I, we, us, them, everyone, rest of us) must generate ambiguity and/or assumption records, rather than blindly expanding to names, unless the context makes it absolutely certain.
7. If contradictory ownerships exist, add a warning. Do not resolve it automatically.
8. IMPORTANT: When a quantity or count is specified (e.g., '2 pancakes', 'Aman had 2, Priya had 1'), extract the base item name ('pancake') as the item_reference and record the quantities in the weights dictionary. NEVER include the quantity or number inside the item_reference string.
9. If ownership is incomplete (e.g., "Aman had half the pizza" and nobody else is assigned the rest), set `ownership_incomplete=true`. Optionally set `unallocated_fraction` (e.g., 0.5) if discernible. Generate a warning when ownership is incomplete. DO NOT invent a sentinel consumer.
10. IMPORTANT: If the description explicitly states a group size (e.g. 'the three of us', 'split among 4 people', 'we are 5'), set group_size to that number. Do NOT invent placeholder names — just set the integer. If no explicit group size is mentioned, leave group_size as null.

Output strict JSON matching the schema.
"""

# ── Internal LLM Schema ───────────────────────────────────────────────────────

class LLMConsumerWeight(BaseModel):
    name: str
    weight: float

class LLMOwnership(BaseModel):
    item_reference: str
    consumers: list[str]
    weights: list[LLMConsumerWeight] | None = Field(
        default=None, 
        description="List of consumer names and their explicitly stated quantity or weight."
    )
    ownership_incomplete: bool = Field(default=False)
    unallocated_fraction: float | None = Field(default=None)

class LLMParsedDescription(BaseModel):
    participants: list[str] = Field(default_factory=list)
    payer: str | None = None
    group_size: int | None = Field(
        default=None,
        description="Explicit group size if stated (e.g. 'the three of us' -> 3). Null if not mentioned."
    )
    ownerships: list[LLMOwnership] = Field(default_factory=list)
    global_rules: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── Main Parser Logic ────────────────────────────────────────────────────────

def parse_description(description: str) -> ParsedDescription:
    """
    Parses a messy natural language description into a structured ParsedDescription graph.
    
    Implements a robust 2-attempt retry loop on JSON/schema failures.
    Delegates all semantic extraction to Gemini 2.5 Flash at Temperature 0.
    """
    if not description or not description.strip():
        return ParsedDescription(
            people=[],
            item_assignments=[],
            shared_with_all=[],
            payer=None,
            raw_text=description,
            ambiguities=[],
            assumptions=[],
            warnings=["Description is empty. No payer or ownership specified."]
        )

    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured.")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    
    generation_config = types.GenerateContentConfig(
        temperature=config.GEMINI_TEMPERATURE,
        system_instruction=DESCRIPTION_PARSER_PROMPT,
        response_mime_type="application/json",
        response_schema=LLMParsedDescription,
    )

    last_exception = None
    max_attempts = 2 
    
    for attempt in range(max_attempts):
        try:
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[f"Description to parse:\n\n{description}"],
                config=generation_config
            )
            
            llm_result: LLMParsedDescription = response.parsed
            
            if llm_result is None:
                raise ValueError("SDK failed to parse the response into the requested schema.")

            from collections import defaultdict
            from utils.fuzzy_match import normalize_text
            
            grouped_owns = defaultdict(list)
            for own in llm_result.ownerships:
                norm = normalize_text(own.item_reference)
                grouped_owns[norm].append(own)

            assignments = []
            for norm, group in grouped_owns.items():
                display_ref = group[0].item_reference
                merged_consumers = []
                merged_weights = {}
                any_incomplete = False
                unallocated = None
                
                for own in group:
                    merged_consumers.extend(own.consumers)
                    if own.weights:
                        for w in own.weights:
                            merged_weights[w.name] = merged_weights.get(w.name, 0.0) + w.weight
                    if own.ownership_incomplete:
                        any_incomplete = True
                    if own.unallocated_fraction is not None:
                        unallocated = own.unallocated_fraction
                        
                merged_consumers = list(dict.fromkeys(merged_consumers))
                
                assignments.append(
                    ItemAssignment(
                        item_ref=display_ref,
                        assigned_to=merged_consumers,
                        quantity_per_person=merged_weights if merged_weights else None,
                        ownership_incomplete=any_incomplete,
                        unallocated_fraction=unallocated
                    )
                )
            
            # ── Post-processing: expand unnamed group members ──────
            people = list(llm_result.participants)
            result_assumptions = list(llm_result.assumptions)
            result_warnings = list(llm_result.warnings)
            
            if llm_result.group_size and llm_result.group_size > len(people):
                unnamed_count = llm_result.group_size - len(people)
                for i in range(1, unnamed_count + 1):
                    people.append(f"Person {i}")
                result_assumptions.append(
                    f"Group size is {llm_result.group_size} but only {len(llm_result.participants)} "
                    f"named. Created {unnamed_count} placeholder(s): "
                    + ", ".join(f"Person {i}" for i in range(1, unnamed_count + 1)) + "."
                )
                # If global sharing rules exist, they will naturally expand to all people.
                # If not, and there are no item assignments, treat as equal split.
                if not assignments and not llm_result.global_rules:
                    result_assumptions.append(
                        "No specific item assignments found. Treating as equal split among all participants."
                    )

            return ParsedDescription(
                people=people,
                item_assignments=assignments,
                shared_with_all=llm_result.global_rules,
                payer=llm_result.payer,
                raw_text=description,
                ambiguities=llm_result.ambiguities,
                assumptions=result_assumptions,
                warnings=result_warnings,
                ai_calls=attempt + 1
            )

        except (ValidationError, ValueError, APIError) as e:
            last_exception = e
            time.sleep(config.RETRY_BACKOFF_FACTOR * (attempt + 1))
        except Exception as e:
            last_exception = e
            time.sleep(config.RETRY_BACKOFF_FACTOR * (attempt + 1))

    raise RuntimeError(
        f"Failed to parse description after {max_attempts} attempts. Last error: {last_exception}"
    ) from last_exception
