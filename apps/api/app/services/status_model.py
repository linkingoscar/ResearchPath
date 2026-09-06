from __future__ import annotations

from app.services.repository_io import JsonObject

_JOB_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}
_INFERENCE_RELIABILITY_CODES = {
    "HC3_UNAVAILABLE",
    "BOOTSTRAP_REPLICATION_DROPPED",
    "SEM_NEGATIVE_VARIANCE",
    "SEM_NON_POSITIVE_DEFINITE_LATENT_COVARIANCE",
}
_BOUNDARY_SOLUTION_CODES = {
    "SEM_NEGATIVE_VARIANCE",
    "SEM_NON_POSITIVE_DEFINITE_LATENT_COVARIANCE",
}


def _codes(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item.get("code"))
        for item in value
        if isinstance(item, dict) and item.get("code")
    ]


def _reason_codes(document: JsonObject) -> list[str]:
    reasons = document.get("publicationEligibilityReasons")
    codes = [str(item) for item in reasons] if isinstance(reasons, list) else []
    codes.extend(_codes(document.get("diagnostics")))
    codes.extend(_codes(document.get("warnings")))
    return list(dict.fromkeys(codes))


def _derive_component_status(
    component: JsonObject,
    reasons: list[str],
) -> tuple[str, str, str]:
    if "REGRESSION_UNDERDETERMINED" in reasons or component.get("underdetermined") is True:
        return "not_run", "not_available", "ineligible"
    if "SEM_FIT_FAILED" in reasons or "ESTIMATION_FAILED" in reasons:
        return "failed", "not_available", "ineligible"
    if "SEM_NOT_CONVERGED" in reasons or "NON_CONVERGED" in reasons:
        return "non_converged", "not_available", "ineligible"
    if component.get("available") is False:
        return "not_run", "not_available", "ineligible"
    if any(code in _BOUNDARY_SOLUTION_CODES for code in reasons):
        return "boundary_solution", "not_reliable", "ineligible"
    if any(code in _INFERENCE_RELIABILITY_CODES for code in reasons):
        return "succeeded", "not_reliable", "ineligible"
    if component.get("validForInterpretation") is False:
        return "succeeded", "needs_review", "ineligible"
    if component.get("requiresManualReview") is True or component.get("publicationEligible") is False:
        return "succeeded", "needs_review", "ineligible"
    if reasons:
        return "succeeded", "needs_review", "ineligible"
    return "succeeded", "reliable", "conditional"


def _job_status(result: JsonObject) -> str:
    run = result.get("run")
    run_status = run.get("status") if isinstance(run, dict) else None
    if run_status == "succeeded":
        return "completed"
    if isinstance(run_status, str) and run_status in _JOB_STATUSES:
        return run_status
    return "completed"


def apply_status_model(result: JsonObject) -> JsonObject:
    """Derive statistical status while preserving the public run.status alias."""
    top_reasons = _reason_codes(result)
    sem_result = result.get("semResult")
    dsem_result = result.get("diaryMultilevel")
    regression_result = result.get("hierarchicalRegression")
    component = next(
        (
            value
            for value in (sem_result, dsem_result, regression_result)
            if isinstance(value, dict)
        ),
        result,
    )
    component_reasons = list(dict.fromkeys(top_reasons + _reason_codes(component)))
    estimation, inference, eligibility = _derive_component_status(
        component, component_reasons
    )
    result.update(
        {
            "jobStatus": _job_status(result),
            "estimationStatus": estimation,
            "inferenceStatus": inference,
            "publicationEligibility": eligibility,
        }
    )
    binding = result.get("studyPlanBinding")
    if isinstance(binding, dict) and (
        binding.get("status") == "stale"
        or binding.get("declarationStatus") == "deviated"
        or binding.get("publicationEligible") is False
    ):
        if estimation not in {"failed", "non_converged", "not_run"}:
            result["inferenceStatus"] = "needs_review"
        result["publicationEligibility"] = "ineligible"
    if isinstance(sem_result, dict):
        sem_result.update(
            {
                "estimationStatus": estimation,
                "inferenceStatus": inference,
                "publicationEligibility": eligibility,
            }
        )
    for nested in (dsem_result, regression_result):
        if isinstance(nested, dict):
            nested_estimation, nested_inference, nested_eligibility = _derive_component_status(
                nested, _reason_codes(nested)
            )
            nested.update(
                {
                    "estimationStatus": nested_estimation,
                    "inferenceStatus": nested_inference,
                    "publicationEligibility": nested_eligibility,
                }
            )
    return result
