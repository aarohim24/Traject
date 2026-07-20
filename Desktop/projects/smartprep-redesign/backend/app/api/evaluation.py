"""
SmartPrep AI - Answer Evaluation API
POST /api/v1/evaluate-answer
"""
from fastapi import APIRouter, HTTPException
from app.models.schemas import AnswerEvaluationRequest, EvaluationResponse, RubricScores
from app.services.rag_service import rag_service
from app.services.llm_service import llm_service
from app.services.session_store import session_store
from app.utils.logger import setup_logger
from app.utils.scoring import score_to_grade
from app.utils.telemetry import telemetry

logger = setup_logger(__name__)
router = APIRouter()


@router.post("/evaluate-answer", response_model=EvaluationResponse)
async def evaluate_answer(request: AnswerEvaluationRequest):
    """
    Evaluate a candidate's answer using hybrid RAG-grounded context:
    1. Optionally rewrite query for multi-part answers
    2. Retrieve relevant resume chunks via hybrid retrieval (FAISS + BM25 + reranker)
    3. Send to LLM with 4-dimension rubric + confidence + provenance
    4. Return structured scoring and feedback
    """
    session = await session_store.get(request.session_id)
    if not session:
        raise HTTPException(404, "Session not found. Please upload your resume first.")

    mode = (request.mode.value if request.mode else None) or "behavioral"

    # Query rewriting for multi-part answers
    extra_queries = None
    try:
        if len(request.user_answer) > 200:
            extra_queries = await llm_service.rewrite_query_for_retrieval(request.user_answer)
    except Exception as e:
        logger.warning(f"Query rewriting failed (non-fatal): {e}")

    # Hybrid retrieval
    try:
        context, precision = await rag_service.retrieve_for_evaluation(
            request.session_id,
            request.question,
            extra_queries=extra_queries,
        )
    except Exception as e:
        logger.warning(f"Hybrid RAG retrieval failed for evaluation, using raw resume: {e}")
        context = ""
        precision = 0.0

    if not context:
        context = session.get("resume_text", "")[:2000]

    # Evaluate with mode-aware rubric
    try:
        with telemetry.timer("evaluate_answer"):
            result = await llm_service.evaluate_answer(
                question=request.question,
                user_answer=request.user_answer,
                resume_context=context,
                category=request.category or "General",
                mode=mode,
                speech_metrics=request.speech_metrics,
            )
        # Record token usage if available in result metadata
        usage = result.get("_usage", {})
        if usage:
            telemetry.record_tokens(
                "evaluate_answer",
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            )
    except Exception as e:
        logger.error(f"Evaluation failed: {e}", exc_info=True)
        raise HTTPException(500, "Failed to evaluate answer. Please try again.")

    score = float(result.get("score", 5.0))
    score = max(0.0, min(10.0, score))
    grade = result.get("grade") or score_to_grade(score)

    # Rubric sub-scores
    rubric_raw = result.get("rubric_scores", {})
    rubric_scores = None
    if rubric_raw:
        try:
            rubric_scores = RubricScores(
                correctness=max(0.0, min(10.0, float(rubric_raw.get("correctness", score)))),
                completeness=max(0.0, min(10.0, float(rubric_raw.get("completeness", score)))),
                communication=max(0.0, min(10.0, float(rubric_raw.get("communication", score)))),
                problem_solving=max(0.0, min(10.0, float(rubric_raw.get("problem_solving", score)))),
            )
        except Exception as e:
            logger.warning(f"Rubric score parsing failed: {e}")

    confidence_score = float(result.get("confidence_score", 0.8))
    confidence_score = max(0.0, min(1.0, confidence_score))
    low_confidence_flag = bool(result.get("low_confidence_flag", False)) or confidence_score < 0.6

    provenance = result.get("provenance", [])
    if not isinstance(provenance, list):
        provenance = []

    logger.info(
        f"Evaluation complete — score={score}, grade={grade}, "
        f"confidence={confidence_score:.2f}, low_conf={low_confidence_flag}, "
        f"precision@k={precision:.2f}"
    )

    return EvaluationResponse(
        score=round(score, 1),
        grade=grade,
        rubric_scores=rubric_scores,
        confidence_score=round(confidence_score, 2),
        low_confidence_flag=low_confidence_flag,
        provenance=provenance[:3],
        strengths=result.get("strengths", []),
        improvements=result.get("improvements", []),
        ideal_answer_points=result.get("ideal_answer_points", []),
        follow_up_question=result.get("follow_up_question"),
        detailed_feedback=result.get("detailed_feedback", ""),
    )
