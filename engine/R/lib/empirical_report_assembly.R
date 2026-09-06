write_progress("assembling_report", 0.96)
check_cancel()
warnings <- researchpath_build_empirical_warnings(list(
  procedure = procedure,
  multiplicity_family_id = multiplicity_family_id, nested_context = nested_context,
  repeated_context = repeated_context, passes_confirmatory_guardrail = passes_confirmatory_guardrail,
  item_complete = item_complete, estimated_parameter_count = estimated_parameter_count,
  cases_per_parameter = cases_per_parameter, longitudinal_panel = longitudinal_panel,
  diary_multilevel = diary_multilevel, parallel_fallback_reason = parallel_fallback_reason,
  factor_method = factor_method, parallel_res = parallel_res,
  hierarchical_regression = hierarchical_regression, partial_undefined_pairs = partial_undefined_pairs,
  htmt_undefined_pairs = htmt_undefined_pairs, htmt_available = htmt_available,
  htmt_reason = htmt_reason, kmo_skipped_reason = kmo_skipped_reason,
  group_comparison = group_comparison, htmt_ci = htmt_ci, efa = efa, cfa = cfa,
  validity = validity, construct_validity = construct_validity
))

publication_reasons <- character(0)
if (nested_context || repeated_context) publication_reasons <- c(publication_reasons, "DEPENDENCE_AWARE_INFERENCE_REQUIRED")
if (isTRUE(cfa$requiresManualReview)) publication_reasons <- c(publication_reasons, unlist(cfa$publicationEligibilityReasons))
if (isTRUE(validity$methodExecution$fallbackApplied)) publication_reasons <- c(publication_reasons, "VALIDITY_NUMERICAL_FALLBACK")
if (!is.null(hierarchical_regression) && isTRUE(hierarchical_regression$requiresManualReview)) {
  publication_reasons <- c(publication_reasons, unlist(hierarchical_regression$publicationEligibilityReasons))
}
publication_reasons <- unique(publication_reasons[nzchar(publication_reasons)])
if (
  !is.null(study_plan_multiplicity) &&
  isTRUE(global_multiplicity$executionDerivedFamily)
) {
  publication_reasons <- unique(c(publication_reasons, "EXECUTION_DERIVED_MULTIPLICITY_FAMILY"))
}
if (
  isTRUE(global_multiplicity$declarationStatus == "typed") &&
  length(global_multiplicity$missingDeclaredEstimandIds) > 0L
) {
  publication_reasons <- unique(c(publication_reasons, "DECLARED_MULTIPLICITY_ESTIMAND_NOT_OBSERVED"))
}
if (
  isTRUE(global_multiplicity$declarationStatus == "typed") &&
  length(global_multiplicity$incompletePrimaryFamilyIds) > 0L
) {
  publication_reasons <- unique(c(publication_reasons, "PRIMARY_MULTIPLICITY_FAMILY_INCOMPLETE"))
}
if (
  isTRUE(global_multiplicity$declarationStatus == "typed") &&
  length(global_multiplicity$duplicateFamilyMembers) > 0L
) {
  publication_reasons <- unique(c(publication_reasons, "DECLARED_MULTIPLICITY_ESTIMAND_IN_MULTIPLE_FAMILIES"))
}
publication_eligible <- length(publication_reasons) == 0L
