`%||%` <- function(left, right) if (is.null(left)) right else left

researchpath_as_character_ids <- function(value) {
  if (is.null(value)) return(character(0))
  values <- as.character(unlist(value, use.names = FALSE))
  unique(values[nzchar(values)])
}

researchpath_find_entry <- function(entries, entry_id) {
  if (is.null(entries) || !is.list(entries)) return(NULL)
  matches <- Filter(function(entry) {
    is.list(entry) && identical(as.character(entry$id), as.character(entry_id))
  }, entries)
  if (length(matches) == 0L) NULL else matches[[1]]
}

researchpath_family_estimands <- function(family, hypotheses, analysis_declarations) {
  explicit <- researchpath_as_character_ids(family$memberEstimandIds)
  if (length(explicit) > 0L) return(explicit)

  member_type <- as.character(family$memberType %||% "estimand")
  member_ids <- researchpath_as_character_ids(family$memberIds)
  if (identical(member_type, "estimand")) return(member_ids)

  source_entries <- if (identical(member_type, "hypothesis")) hypotheses else analysis_declarations
  unique(unlist(lapply(member_ids, function(member_id) {
    entry <- researchpath_find_entry(source_entries, member_id)
    if (is.null(entry)) character(0) else researchpath_as_character_ids(entry$estimandIds)
  }), use.names = FALSE))
}

researchpath_family_role <- function(family, estimand_ids, hypotheses) {
  explicit <- as.character(family$role %||% "")
  if (nzchar(explicit)) return(explicit)
  roles <- unique(unlist(lapply(hypotheses, function(hypothesis) {
    if (!is.list(hypothesis)) return(character(0))
    hypothesis_estimands <- researchpath_as_character_ids(hypothesis$estimandIds)
    if (length(intersect(hypothesis_estimands, estimand_ids)) == 0L) character(0) else as.character(hypothesis$analysisRole %||% "")
  }), use.names = FALSE))
  roles <- roles[nzchar(roles)]
  if (length(roles) == 1L) roles[[1]] else "unspecified"
}

researchpath_normalize_multiplicity_declaration <- function(declaration, fallback_adjustment = "BH") {
  if (is.null(declaration) || !is.list(declaration)) {
    return(list(hasPlan = FALSE, typed = FALSE, families = list(), resultBindings = list()))
  }
  hypotheses <- if (is.list(declaration$hypotheses)) declaration$hypotheses else list()
  analysis_declarations <- if (is.list(declaration$analysisDeclarations)) declaration$analysisDeclarations else list()
  raw_families <- if (is.list(declaration$multiplicityFamilies)) declaration$multiplicityFamilies else list()
  families <- lapply(raw_families, function(family) {
    if (!is.list(family)) return(NULL)
    estimand_ids <- researchpath_family_estimands(family, hypotheses, analysis_declarations)
    adjustment <- as.character(family$adjustment %||% family$adjustmentMethod %||% fallback_adjustment)
    if (!(adjustment %in% c("none", "holm", "BH", "bonferroni"))) adjustment <- fallback_adjustment
    list(
      id = as.character(family$id %||% ""),
      label = as.character(family$label %||% ""),
      role = researchpath_family_role(family, estimand_ids, hypotheses),
      adjustment = adjustment,
      estimandIds = unique(estimand_ids[nzchar(estimand_ids)])
    )
  })
  families <- Filter(function(family) !is.null(family) && nzchar(family$id) && length(family$estimandIds) > 0L, families)

  raw_bindings <- if (is.list(declaration$resultBindings)) declaration$resultBindings else list()
  for (analysis in analysis_declarations) {
    parameters <- if (is.list(analysis) && is.list(analysis$parameters)) analysis$parameters else list()
    candidate <- parameters$resultBindings %||% parameters$multiplicityResultBindings
    if (is.list(candidate)) raw_bindings <- c(raw_bindings, candidate)
  }
  result_bindings <- Filter(is.list, raw_bindings)
  bound_analysis <- researchpath_find_entry(
    analysis_declarations,
    if (is.list(declaration$studyPlanBinding)) declaration$studyPlanBinding$analysisDeclarationId else NULL
  )
  list(
    hasPlan = TRUE,
    typed = length(families) > 0L,
    families = families,
    resultBindings = result_bindings,
    estimands = if (is.list(declaration$estimands)) declaration$estimands else list(),
    binding = if (is.list(declaration$studyPlanBinding)) declaration$studyPlanBinding else list(),
    expectedEstimandIds = if (is.null(bound_analysis)) character(0) else researchpath_as_character_ids(bound_analysis$estimandIds)
  )
}

researchpath_normalize_result_component <- function(value) {
  value <- tolower(as.character(value %||% ""))
  if (value %in% c("correlation", "correlations", "correlation_pair")) return("correlation")
  if (value %in% c("group", "group_comparison", "groupcomparison")) return("group")
  if (value %in% c("regression", "regression_coefficient", "regressioncoefficient")) return("regression")
  value
}

researchpath_normalize_result_key <- function(component, key) {
  key <- as.character(key %||% "")
  if (identical(component, "correlation")) {
    parts <- unlist(strsplit(key, ":", fixed = TRUE), use.names = FALSE)
    if (length(parts) == 2L) return(paste(sort(parts), collapse = ":"))
  }
  key
}

researchpath_result_binding_estimand <- function(bindings, component, key) {
  if (!is.list(bindings)) return(NULL)
  normalized_key <- researchpath_normalize_result_key(component, key)
  for (binding in bindings) {
    if (!is.list(binding)) next
    binding_component <- researchpath_normalize_result_component(binding$component %||% binding$resultType)
    binding_key <- binding$key %||% binding$resultKey %||% binding$sourceKey
    if (
      (identical(binding_component, component) || !nzchar(binding_component)) &&
      identical(researchpath_normalize_result_key(component, binding_key), normalized_key)
    ) {
      estimand_id <- as.character(binding$estimandId %||% "")
      if (nzchar(estimand_id)) return(estimand_id)
    }
  }
  NULL
}

researchpath_structural_estimand <- function(estimands, component, key, outcome_id = NULL) {
  if (!is.list(estimands)) return(NULL)
  key_parts <- unlist(strsplit(as.character(key), ":", fixed = TRUE), use.names = FALSE)
  matches <- Filter(function(estimand) {
    if (!is.list(estimand)) return(FALSE)
    outcome <- as.character(estimand$outcomeId %||% "")
    predictor <- as.character(estimand$focalPredictorId %||% "")
    if (identical(component, "regression")) {
      return(identical(predictor, as.character(key)) && (is.null(outcome_id) || identical(outcome, as.character(outcome_id))))
    }
    if (identical(component, "group")) return(identical(as.character(estimand$outcomeId %||% ""), as.character(key)))
    if (identical(component, "correlation") && length(key_parts) == 2L) {
      return(identical(sort(c(outcome, predictor)), sort(key_parts)))
    }
    FALSE
  }, estimands)
  if (length(matches) != 1L) return(NULL)
  as.character(matches[[1]]$id %||% "")
}

researchpath_resolve_result_estimand <- function(
  declaration, component, key, outcome_id = NULL, fallback_estimand = NULL
) {
  explicit <- researchpath_result_binding_estimand(declaration$resultBindings, component, key)
  if (!is.null(explicit)) return(explicit)
  structural <- researchpath_structural_estimand(declaration$estimands, component, key, outcome_id)
  if (!is.null(structural) && nzchar(structural)) return(structural)
  if (!is.null(fallback_estimand) && nzchar(as.character(fallback_estimand))) return(as.character(fallback_estimand))
  NULL
}

researchpath_is_adjustment_covariate <- function(term, options) {
  term <- as.character(term %||% "")
  controls <- researchpath_as_character_ids(options$controlVariableIds)
  if (!nzchar(term) || length(controls) == 0L) return(FALSE)
  any(vapply(controls, function(control) identical(term, control) || startsWith(term, control), logical(1)))
}

researchpath_apply_global_multiplicity <- function(
  options, non_iid_context, correlation_family_indices, raw_p_value_matrix,
  correlation_count, correlations, group_comparison, hierarchical_regression,
  multiplicity_family_id, study_plan_multiplicity = NULL
) {
  fallback_adjustment <- if (!is.null(options$multiplicityPAdjust) && options$multiplicityPAdjust %in% c("none", "holm", "BH")) options$multiplicityPAdjust else "BH"
  declaration <- researchpath_normalize_multiplicity_declaration(study_plan_multiplicity, fallback_adjustment)
  typed <- isTRUE(declaration$typed)
  execution_derived <- !typed
  control_ids <- researchpath_as_character_ids(options$controlVariableIds)
  correlation_ids <- if (is.list(correlations$variables)) {
    vapply(correlations$variables, function(variable) as.character(variable$id), character(1))
  } else {
    as.character(seq_len(correlation_count))
  }
  observations <- list()
  add_observation <- function(component, key, raw, estimand_id = NULL, analysis_role = "hypothesis") {
    if (length(raw) == 0L || !is.finite(as.numeric(raw[[1]]))) return(invisible(NULL))
    observations[[length(observations) + 1L]] <<- list(
      component = component, key = as.character(key), raw = as.numeric(raw[[1]]),
      estimandId = if (is.null(estimand_id)) NULL else as.character(estimand_id),
      analysisRole = analysis_role
    )
    invisible(NULL)
  }

  if (!non_iid_context && length(correlation_family_indices) > 0L) {
    for (position in correlation_family_indices) {
      coordinates <- arrayInd(position, dim(raw_p_value_matrix))
      first <- coordinates[[1]]; second <- coordinates[[2]]
      if (any(c(correlation_ids[[first]], correlation_ids[[second]]) %in% control_ids)) next
      key <- paste(sort(c(correlation_ids[[first]], correlation_ids[[second]])), collapse = ":")
      estimand_id <- researchpath_resolve_result_estimand(
      declaration, "correlation", key,
        fallback_estimand = NULL
      )
      add_observation("correlation", key, raw_p_value_matrix[position], estimand_id)
    }
  }

  if (!is.null(group_comparison)) for (row in group_comparison$results) {
    raw <- if (!is.null(row$pValueRaw)) row$pValueRaw else row$pValue
    estimand_id <- researchpath_resolve_result_estimand(
      declaration, "group", row$id,
      fallback_estimand = NULL
    )
    add_observation("group", row$id, raw, estimand_id)
  }

  if (!is.null(hierarchical_regression)) for (block in hierarchical_regression$blocks) for (coefficient in block$coefficients) {
    term <- as.character(coefficient$term %||% "")
    if (identical(term, "(Intercept)")) next
    if (researchpath_is_adjustment_covariate(term, options)) next
    raw <- if (!is.null(coefficient$pValueRaw)) coefficient$pValueRaw else coefficient$pValue
    estimand_id <- researchpath_resolve_result_estimand(
      declaration, "regression", term,
      outcome_id = options$outcomeVariableId,
      fallback_estimand = NULL
    )
    add_observation("regression", term, raw, estimand_id)
  }

  family_lookup <- list()
  for (family in declaration$families) family_lookup[[family$id]] <- family
  if (execution_derived) {
    family_lookup[[multiplicity_family_id]] <- list(
      id = multiplicity_family_id, label = "execution-derived family", role = "inferred",
      adjustment = fallback_adjustment, estimandIds = character(0)
    )
  }

  family_for_estimand <- list()
  duplicate_family_members <- character(0)
  if (typed) for (family in declaration$families) for (estimand_id in family$estimandIds) {
    if (!is.null(family_for_estimand[[estimand_id]])) duplicate_family_members <- c(duplicate_family_members, estimand_id)
    family_for_estimand[[estimand_id]] <- family$id
  }

  for (index in seq_along(observations)) {
    observation <- observations[[index]]
    if (typed) {
      family_id <- if (!is.null(observation$estimandId)) family_for_estimand[[observation$estimandId]] else NULL
      observation$familyId <- family_id
      observation$declarationStatus <- if (is.null(family_id)) "unmapped" else "declared"
      observation$dedupeKey <- if (is.null(observation$estimandId)) {
        paste(observation$component, observation$key, sep = ":")
      } else {
        paste("estimand", observation$estimandId, sep = ":")
      }
    } else {
      observation$familyId <- multiplicity_family_id
      observation$declarationStatus <- "execution_derived_family"
      observation$dedupeKey <- if (is.null(observation$estimandId)) {
        paste(observation$component, observation$key, sep = ":")
      } else {
        paste("estimand", observation$estimandId, sep = ":")
      }
    }
    observations[[index]] <- observation
  }

  adjustment_lookup <- list()
  family_ledger <- lapply(unname(family_lookup), function(family) {
    family_id <- family$id
    selected <- which(vapply(observations, function(observation) identical(observation$familyId, family_id), logical(1)))
    dedupe_ids <- if (length(selected) == 0L) character(0) else unique(vapply(selected, function(index) observations[[index]]$dedupeKey, character(1)))
    raw_values <- if (length(dedupe_ids) == 0L) numeric(0) else vapply(dedupe_ids, function(dedupe_id) {
      selected_index <- selected[which(vapply(selected, function(index) identical(observations[[index]]$dedupeKey, dedupe_id), logical(1)))[[1]]]
      observations[[selected_index]]$raw
    }, numeric(1))
    declared_ids <- if (typed) family$estimandIds else character(0)
    declared_family_size <- if (typed) length(declared_ids) else length(dedupe_ids)
    adjusted_values <- if (length(raw_values) > 0L) {
      stats::p.adjust(raw_values, method = family$adjustment, n = declared_family_size)
    } else numeric(0)
    for (index in seq_along(dedupe_ids)) adjustment_lookup[[paste(family_id, dedupe_ids[[index]], sep = "\u001f")]] <<- adjusted_values[[index]]
    observed_ids <- if (typed) unique(vapply(Filter(function(index) !is.null(observations[[index]]$estimandId), selected), function(index) observations[[index]]$estimandId, character(1))) else dedupe_ids
    unobserved_ids <- setdiff(declared_ids, observed_ids)
    list(
      id = family_id, label = family$label, role = family$role, adjustment = family$adjustment,
      declaredMemberEstimandIds = as.list(declared_ids), declaredFamilySize = as.integer(declared_family_size),
      adjustmentN = as.integer(declared_family_size),
      observedMemberEstimandIds = as.list(observed_ids), observedMemberCount = as.integer(length(observed_ids)),
      unobservedMemberEstimandIds = as.list(unobserved_ids),
      primaryFamilyIncomplete = identical(family$role, "primary") && length(unobserved_ids) > 0L
    )
  })

  incomplete_primary_family_ids <- vapply(
    Filter(function(record) isTRUE(record$primaryFamilyIncomplete), family_ledger),
    function(record) record$id,
    character(1)
  )

  adjusted_for_observation <- function(observation) {
    if (is.null(observation$familyId)) return(NA_real_)
    key <- paste(observation$familyId, observation$dedupeKey, sep = "\u001f")
    if (is.null(adjustment_lookup[[key]])) NA_real_ else adjustment_lookup[[key]]
  }
  family_record_for <- function(family_id) {
    matches <- Filter(function(record) identical(record$id, family_id), family_ledger)
    if (length(matches) == 0L) NULL else matches[[1]]
  }
  observed_estimand_ids <- unique(vapply(
    Filter(function(observation) !is.null(observation$estimandId), observations),
    function(observation) observation$estimandId,
    character(1)
  ))
  missing_declared_estimand_ids <- setdiff(declaration$expectedEstimandIds, observed_estimand_ids)
  observation_index <- function(component, key) {
    matches <- which(vapply(observations, function(observation) {
      identical(observation$component, component) && identical(as.character(observation$key), as.character(key))
    }, logical(1)))
    if (length(matches) == 0L) integer(0) else matches[[1]]
  }

  global_matrix <- matrix(NA_real_, correlation_count, correlation_count)
  global_raw_matrix <- matrix(NA_real_, correlation_count, correlation_count)
  family_matrix <- matrix(NA_character_, correlation_count, correlation_count)
  for (position in correlation_family_indices) {
    coordinates <- arrayInd(position, dim(raw_p_value_matrix))
    first <- coordinates[[1]]; second <- coordinates[[2]]
    key <- paste(sort(c(correlation_ids[[first]], correlation_ids[[second]])), collapse = ":")
    index <- observation_index("correlation", key)
    if (length(index) == 1L) {
      observation <- observations[[index]]
      adjusted <- adjusted_for_observation(observation)
      global_raw_matrix[position] <- observation$raw
      global_raw_matrix[coordinates[[2]], coordinates[[1]]] <- observation$raw
      if (is.finite(adjusted)) {
        global_matrix[position] <- adjusted
        global_matrix[coordinates[[2]], coordinates[[1]]] <- adjusted
        family_matrix[position] <- observation$familyId
        family_matrix[coordinates[[2]], coordinates[[1]]] <- observation$familyId
      }
    }
  }

  if (!is.null(correlations)) {
    correlations$globalPValuesRaw <- lapply(seq_len(correlation_count), function(i) as.list(global_raw_matrix[i, ]))
    correlations$globalPValues <- lapply(seq_len(correlation_count), function(i) as.list(global_matrix[i, ]))
    correlations$declaredMultiplicityFamilyIds <- lapply(seq_len(correlation_count), function(i) as.list(family_matrix[i, ]))
    correlations$multiplicity$declarationMode <- if (typed) "typed" else "execution_derived_family"
    correlations$multiplicity$declaredFamilyLedger <- family_ledger
    correlations$multiplicity$executionDerivedFamily <- execution_derived
    if (typed) correlations$multiplicity$familyId <- if (length(family_ledger) == 1L) family_ledger[[1]]$id else "declared"
    correlations$multiplicity$globalFamilySize <- as.integer(sum(vapply(family_ledger, function(record) record$declaredFamilySize, integer(1))))
    correlations$multiplicity$globalAdjustment <- if (typed) "declared" else fallback_adjustment
    correlations$multiplicity$globalAdjustmentApplied <- any(is.finite(global_matrix))
  }

  decorate_row <- function(row, component, key, raw_field = "pValueRaw") {
    index <- observation_index(component, key)
    if (length(index) == 1L) {
      observation <- observations[[index]]
      adjusted <- adjusted_for_observation(observation)
      row$declarationStatus <- observation$declarationStatus
      family_record <- family_record_for(observation$familyId)
      row$analysisRole <- if (is.null(family_record)) observation$analysisRole else family_record$role
      if (!is.null(observation$estimandId)) row$estimandId <- observation$estimandId
      row[[raw_field]] <- observation$raw
      pre_adjusted <- row$pValueAdjusted
      pre_component_family <- row$multiplicityFamilyId
      if (is.finite(adjusted)) {
        # Components that already completed their own within-component family
        # adjustment (for example, group comparison across constructs) keeps
        # that component p value; the cross-component global adjustment is
        # recorded in the global* fields. Components without a component
        # adjustment (for example, regression rows) displays the global
        # multiplicity-adjusted p value and keep the raw value in pValueRaw.
        if (typed || is.null(pre_adjusted)) {
          row$pValueAdjusted <- adjusted
          row$pValue <- adjusted
        }
        if (typed || is.null(pre_component_family)) {
          row$multiplicityFamilyId <- observation$familyId
          family_record <- family_record_for(observation$familyId)
          row$multiplicityFamilySize <- if (is.null(family_record)) NA_integer_ else family_record$declaredFamilySize
          row$multiplicityAdjustmentN <- if (is.null(family_record)) NA_integer_ else family_record$adjustmentN
          row$pAdjustMethod <- if (is.null(family_record)) fallback_adjustment else family_record$adjustment
        }
        row$globalPValue <- adjusted
        row$globalMultiplicityFamilyId <- observation$familyId
        family_record <- family_record_for(observation$familyId)
        row$globalMultiplicityFamilySize <- if (is.null(family_record)) NA_integer_ else family_record$declaredFamilySize
        row$globalMultiplicityAdjustmentN <- if (is.null(family_record)) NA_integer_ else family_record$adjustmentN
        row$globalPAdjustMethod <- if (is.null(family_record)) fallback_adjustment else family_record$adjustment
      }
    }
    row
  }

  if (!is.null(group_comparison)) {
    for (index in seq_along(group_comparison$results)) {
      group_comparison$results[[index]] <- decorate_row(group_comparison$results[[index]], "group", group_comparison$results[[index]]$id)
    }
    group_comparison$multiplicity$declarationMode <- if (typed) "typed" else "execution_derived_family"
    group_comparison$multiplicity$declaredFamilyLedger <- family_ledger
    group_comparison$multiplicity$executionDerivedFamily <- execution_derived
    group_comparison$multiplicity$globalAdjustmentApplied <- any(vapply(observations, function(observation) identical(observation$component, "group") && is.finite(adjusted_for_observation(observation)), logical(1)))
  }

  if (!is.null(hierarchical_regression)) {
    for (block_index in seq_along(hierarchical_regression$blocks)) {
      block <- hierarchical_regression$blocks[[block_index]]
      for (coefficient_index in seq_along(block$coefficients)) {
        coefficient <- block$coefficients[[coefficient_index]]
        term <- as.character(coefficient$term %||% "")
        if (identical(term, "(Intercept)")) next
        if (researchpath_is_adjustment_covariate(term, options)) {
          coefficient$analysisRole <- "adjustment_covariate"
          coefficient$declarationStatus <- if (typed) "excluded_adjustment_covariate" else "inferred_excluded_adjustment_covariate"
          block$coefficients[[coefficient_index]] <- coefficient
          next
        }
        block$coefficients[[coefficient_index]] <- decorate_row(coefficient, "regression", term)
      }
      hierarchical_regression$blocks[[block_index]] <- block
    }
    hierarchical_regression$multiplicityFamilyId <- if (typed) "declared" else multiplicity_family_id
    hierarchical_regression$multiplicityFamilySize <- as.integer(sum(vapply(family_ledger, function(record) record$declaredFamilySize, integer(1))))
    hierarchical_regression$multiplicity <- list(
      declarationMode = if (typed) "typed" else "execution_derived_family",
      declaredFamilyLedger = family_ledger,
      executionDerivedFamily = execution_derived
    )
  }

  unmapped <- Filter(function(observation) is.null(observation$familyId), observations)
  ledger_results <- lapply(observations, function(observation) {
    family_record <- family_record_for(observation$familyId)
    adjusted <- adjusted_for_observation(observation)
    list(
      component = observation$component, key = observation$key,
      estimandId = observation$estimandId,
      analysisRole = if (is.null(family_record)) observation$analysisRole else family_record$role,
      declarationStatus = observation$declarationStatus,
      familyId = observation$familyId,
      familySize = if (is.null(family_record)) NULL else family_record$declaredFamilySize,
      adjustmentN = if (is.null(family_record)) NULL else family_record$adjustmentN,
      adjustment = if (is.null(family_record)) NULL else family_record$adjustment,
      pValueRaw = observation$raw, pValueAdjusted = if (is.finite(adjusted)) adjusted else NULL
    )
  })
  list(
    correlations = correlations, groupComparison = group_comparison,
    hierarchicalRegression = hierarchical_regression,
    adjustment = if (typed) "declared" else fallback_adjustment,
    familySize = as.integer(sum(vapply(family_ledger, function(record) record$declaredFamilySize, integer(1)))),
    applied = any(vapply(observations, function(observation) is.finite(adjusted_for_observation(observation)), logical(1))),
    declarationStatus = if (typed) "typed" else "execution_derived_family",
    executionDerivedFamily = execution_derived,
    incompletePrimaryFamilyIds = as.list(incomplete_primary_family_ids),
    primaryFamilyIncomplete = length(incomplete_primary_family_ids) > 0L,
    requiresManualReview = length(incomplete_primary_family_ids) > 0L,
    publicationEligibilityReasons = if (length(incomplete_primary_family_ids) > 0L) {
      list("PRIMARY_MULTIPLICITY_FAMILY_INCOMPLETE")
    } else list(),
    duplicateFamilyMembers = as.list(unique(duplicate_family_members)),
    unmappedResultKeys = as.list(vapply(unmapped, function(observation) paste(observation$component, observation$key, sep = ":"), character(1))),
    missingDeclaredEstimandIds = as.list(missing_declared_estimand_ids),
    ledger = list(
      mode = if (typed) "typed" else "execution_derived_family",
      families = family_ledger, results = ledger_results
    )
  )
}
