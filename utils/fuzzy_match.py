import re
import unicodedata
from pydantic import BaseModel
from rapidfuzz import process, fuzz

class MatchResult(BaseModel):
    matched_item: str | None
    confidence: float
    exact_match: bool
    ambiguous: bool
    candidate_matches: list[str]

def normalize_text(text: str) -> str:
    """Normalizes text for matching by handling case, punctuation, unicode, and simple plurals."""
    if not text:
        return ""
    # Unicode normalize (e.g. café -> cafe)
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = text.lower()
    # Remove punctuation
    text = re.sub(r'[^\w\s]', ' ', text)
    # Simple stemming for plural (remove trailing 's' if length > 3 and doesn't end in 'ss')
    words = []
    for w in text.split():
        if w in ('the', 'a', 'an'):
            continue
        if len(w) > 3 and w.endswith('s') and not w.endswith('ss'):
            words.append(w[:-1])
        else:
            words.append(w)
    return " ".join(words).strip()

def match_item(user_reference: str, receipt_items: list[str], threshold: float = 75.0, ambiguity_margin: float = 5.0) -> MatchResult:
    """
    Deterministically matches a user's informal item reference to exactly one receipt item.
    Returns ambiguous=True if the top candidates are too close.
    """
    if not user_reference or not receipt_items:
        return MatchResult(matched_item=None, confidence=0.0, exact_match=False, ambiguous=False, candidate_matches=[])
        
    norm_user = normalize_text(user_reference)
    if not norm_user:
        return MatchResult(matched_item=None, confidence=0.0, exact_match=False, ambiguous=False, candidate_matches=[])

    # 1. Exact match check (case-insensitive, normalized)
    # This prevents edge cases where rapidfuzz scoring might artificially lower a mathematically exact normalized match.
    exact_candidates = []
    for item in receipt_items:
        if norm_user == normalize_text(item):
            exact_candidates.append(item)
            
    if exact_candidates:
        if len(exact_candidates) > 1:
            return MatchResult(matched_item=None, confidence=100.0, exact_match=True, ambiguous=True, candidate_matches=exact_candidates)
        return MatchResult(matched_item=exact_candidates[0], confidence=100.0, exact_match=True, ambiguous=False, candidate_matches=exact_candidates)

    # 2. Fuzzy Match
    # WRatio combines subset matching (token_set_ratio) and strict ordering.
    # Perfect for "brownie" matching "Chocolate Brownie Sundae".
    results = process.extract(
        norm_user,
        receipt_items,
        processor=normalize_text,
        scorer=fuzz.WRatio,
        limit=None
    )
    
    if not results:
        return MatchResult(matched_item=None, confidence=0.0, exact_match=False, ambiguous=False, candidate_matches=[])
        
    results.sort(key=lambda x: x[1], reverse=True)
    best_match, best_score, _ = results[0]
    
    # 3. Confidence Threshold Guard
    if best_score < threshold:
        return MatchResult(
            matched_item=None,
            confidence=best_score,
            exact_match=False,
            ambiguous=False,
            candidate_matches=[]
        )
        
    # 4. Ambiguity Guard
    # Collect all candidates within `ambiguity_margin` of the best score.
    candidates = []
    for match_str, score, _ in results:
        if score >= threshold and (best_score - score) <= ambiguity_margin:
            candidates.append(match_str)
                
    if len(candidates) > 1:
        return MatchResult(
            matched_item=None,
            confidence=best_score,
            exact_match=False,
            ambiguous=True,
            candidate_matches=candidates
        )
        
    return MatchResult(
        matched_item=best_match,
        confidence=best_score,
        exact_match=False,
        ambiguous=False,
        candidate_matches=[best_match]
    )
