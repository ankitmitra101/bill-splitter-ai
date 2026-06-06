import base64
import logging
import time
import uuid
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, status, Depends

from schemas.api import (
    SplitRequest,
    SplitResponse,
    PersonBreakdown,
    ItemShare,
    ReconciliationResult,
    Telemetry,
)
from schemas.internal import Severity
from stages.extraction import extract_receipt
from stages.description_parser import parse_description
from stages.ownership import build_ownership_graph
from stages.validation import validate_pipeline
from stages.calculator import calculate_splits
from stages.settlement import generate_settlement
from utils.money import _standard_round

logger = logging.getLogger("fair_split.api")
logging.basicConfig(level=logging.INFO)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="Fair Split API")

# Allow requests from all origins (useful for local development/file:// testing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MIN_RECEIPT_CONFIDENCE = 0.2

class PipelineError(Exception):
    pass

class ReceiptExtractionError(PipelineError):
    pass

class ValidationError(PipelineError):
    pass

class OwnershipError(PipelineError):
    pass

@contextmanager
def timing_log(stage_name: str, req_id: str):
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    logger.info(f"[{req_id}] Stage '{stage_name}' completed in {elapsed:.3f}s")


class PipelineRunner:
    """Encapsulates the execution sequence to keep the route handler clean."""
    
    def execute(self, request: SplitRequest, req_id: str) -> SplitResponse:
        # 1. Decode Image
        with timing_log("decode_image", req_id):
            try:
                image_bytes = base64.b64decode(request.receipt_base64, validate=True)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid base64 encoding for receipt image."
                ) from e
                
        # 2. Extract Receipt
        with timing_log("extract_receipt", req_id):
            try:
                receipt = extract_receipt(image_bytes)
                extraction_flags = []
            except Exception as e:
                logger.error(f"[{req_id}] Extraction failed: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Unexpected error during receipt extraction."
                ) from e
                
            # 422 Detection
            if receipt.confidence_score < MIN_RECEIPT_CONFIDENCE:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Image does not appear to be a receipt (confidence too low)."
                )
            if len(receipt.items) == 0 and receipt.grand_total is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Image does not appear to be a receipt (no items or total found)."
                )
                
        # 3. Parse Description
        with timing_log("parse_description", req_id):
            parsed = parse_description(request.description)
            
        # 4. Build Ownership
        with timing_log("build_ownership", req_id):
            ownership = build_ownership_graph(parsed, receipt)
            
        # 5. Validate Pipeline
        with timing_log("validate_pipeline", req_id):
            validation_res = validate_pipeline(receipt, parsed, ownership)
            if not validation_res.is_valid:
                critical_errors = [
                    f.message for f in validation_res.flags if f.severity == Severity.CRITICAL
                ]
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Pipeline validation failed due to critical errors: {critical_errors}"
                )
                
        # 6. Calculate Splits
        with timing_log("calculate_splits", req_id):
            calc_res = calculate_splits(receipt, ownership, parsed.people)
            
        # 7. Generate Settlement
        with timing_log("generate_settlement", req_id):
            settle_up_entries, settlement_flags = generate_settlement(calc_res.final_totals, parsed.payer)
            
        # 8. Build Response
        with timing_log("build_response", req_id):
            return self._build_response(
                calc_res=calc_res,
                validation_res=validation_res,
                extraction_flags=extraction_flags,
                settlement_flags=settlement_flags,
                settle_up_entries=settle_up_entries,
                payer=parsed.payer,
                receipt_ai_calls=receipt.ai_calls,
                parser_ai_calls=parsed.ai_calls,
                ownership_ai_calls=ownership.ai_calls
            )

    def _build_response(self, calc_res, validation_res, extraction_flags, settlement_flags, settle_up_entries, payer, receipt_ai_calls, parser_ai_calls, ownership_ai_calls) -> SplitResponse:
        per_person = []
        for pc in calc_res.components:
            items = [
                ItemShare(name=i.name, amount=_standard_round(i.amount_paise / 100))
                for i in pc.items
            ]
            person_total = calc_res.final_totals.get(pc.name, 0)
            pb = PersonBreakdown(
                name=pc.name,
                items=items,
                subtotal=_standard_round(pc.subtotal_paise / 100),
                tax_share=_standard_round(pc.tax_share_paise / 100),
                service_share=_standard_round(pc.service_share_paise / 100),
                discount_share=_standard_round(pc.discount_share_paise / 100),
                total=person_total
            )
            per_person.append(pb)
            
        sum_of_totals = sum(calc_res.final_totals.values())
        reconciliation = ReconciliationResult(
            sum_of_person_totals=sum_of_totals,
            matches_bill=(sum_of_totals == calc_res.grand_total_rupees),
            discrepancies=[]
        )
        
        if len(per_person) == 0:
            reconciliation.discrepancies.append("No people identified in description to absorb the bill.")
            
        if sum_of_totals != calc_res.grand_total_rupees:
            reconciliation.discrepancies.append(f"₹{abs(calc_res.grand_total_rupees - sum_of_totals)} of receipt value remains unassigned.")
            
        all_assumptions = list(dict.fromkeys(validation_res.assumptions + calc_res.assumptions))
        
        formatted_flags = [f"{f.severity.upper()}: {f.source}: {f.message}" for f in validation_res.flags]
        all_flags = extraction_flags + formatted_flags + calc_res.flags + settlement_flags
        
        bill_matches = (sum_of_totals == calc_res.grand_total_rupees)
        settlement_status = "final" if bill_matches else "provisional"
        
        if not bill_matches:
            all_flags.append(
                "WARNING: settlement: Settlement is provisional because not all receipt items have been assigned."
            )
        
        telemetry = Telemetry(
            receipt_extraction_calls=receipt_ai_calls,
            description_parsing_calls=parser_ai_calls,
            semantic_matching_calls=ownership_ai_calls,
            total_ai_calls=receipt_ai_calls + parser_ai_calls + ownership_ai_calls
        )

        return SplitResponse(
            per_person=per_person,
            grand_total=calc_res.grand_total_rupees,
            reconciliation=reconciliation,
            paid_by=payer,
            settle_up=settle_up_entries,
            settlement_status=settlement_status,
            assumptions=all_assumptions,
            flags=all_flags,
            telemetry=telemetry
        )

def get_pipeline_runner() -> PipelineRunner:
    return PipelineRunner()

@app.get("/health")
def health_check():
    return {"status": "ok"}

# Mount the static directory for CSS/JS/Assets (if any)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def serve_frontend():
    """Serves the single-page application frontend."""
    import os
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    return FileResponse(index_path)

@app.post("/split", response_model=SplitResponse)
def split_bill(request: SplitRequest, runner: PipelineRunner = Depends(get_pipeline_runner)):
    req_id = str(uuid.uuid4())
    logger.info(f"[{req_id}] Received POST /split request")
    
    try:
        response = runner.execute(request, req_id)
        logger.info(f"[{req_id}] Successfully generated SplitResponse")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{req_id}] Unhandled exception during pipeline execution")
        
        # Graceful handling of Gemini 429 Resource Exhausted / Quota Limits
        error_msg = str(e).lower()
        if "429" in error_msg and ("resource_exhausted" in error_msg or "quota" in error_msg):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI quota temporarily exhausted. Please retry in 15 seconds."
            )
            
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred."
        ) from e
