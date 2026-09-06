args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("Usage: run_empirical_analysis.R <input.json> <output.json>")
suppressPackageStartupMessages(library(jsonlite))

payload <- fromJSON(args[[1]], simplifyVector = FALSE)
metadata <- payload$metadata
# Raw-variable procedures intentionally carry no measurement version or constructs.
# Preserve NULL in the result identity; do not invent a measurement artifact.
options <- payload$options
confidence_level <- if (!is.null(options$confidenceLevel)) as.numeric(options$confidenceLevel) else 0.95
if (!is.finite(confidence_level) || confidence_level <= 0.5 || confidence_level >= 1) {
  stop("confidenceLevel 必须位于 (0.5, 1.0) 区间")
}
multiplicity_family_id <- if (!is.null(options$multiplicityFamilyId) && nzchar(as.character(options$multiplicityFamilyId))) {
  as.character(options$multiplicityFamilyId)
} else {
  "cross_sectional_inference"
}
study_plan_multiplicity <- options$studyPlanMultiplicity
nested_context <- identical(options$contextDependenceStructure, "nested")
repeated_context <- options$contextTimeStructure %in% c("panel", "intensive_longitudinal")
non_iid_context <- nested_context || repeated_context
non_iid_reason_prefix <- if (nested_context) "NESTED_ROWS" else "REPEATED_ROWS"
progress_path <- if (is.null(payload$progressPath)) NULL else payload$progressPath
cancel_path <- if (is.null(payload$cancelPath)) NULL else payload$cancelPath

args_all <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("--file=", args_all, value = TRUE)
script_dir <- if (length(file_arg) > 0) dirname(substring(file_arg[1], 8)) else "engine/R"
for (module in c("runtime.R", "parallel.R", "resource_budget.R", "seed_utils.R", "output_contract.R", "diary_utils.R", "centering_utils.R", "time_series_utils.R", "efa.R", "cfa.R", "sample_adequacy.R", "cfa_validity.R", "validity.R", "invariance.R", "cmb.R", "inference_covariance.R", "marginal_effects.R", "regression_reporting.R", "aggregation_diagnostics.R", "empirical_group_reporting.R", "response_surface.R", "relative_importance.R", "missing_data.R", "longitudinal_power.R", "longitudinal_lcm_sr.R", "longitudinal_cmb.R", "longitudinal_latent.R", "longitudinal_panel.R", "diary_esm_evidence.R", "diary_missing.R", "diary_power.R", "diary_glmm.R", "diary_bayesian_diagnostics.R", "diary_bayesian_dsem.R", "diary_multilevel.R", "hierarchical_regression.R", "empirical_diagnostics.R", "empirical_multiplicity.R", "empirical_warnings.R", "empirical_ordinal_efa.R")) {
  source(file.path(script_dir, "lib", module), local = environment())
}
write_progress("loading_data", 0.1)
check_cancel()
data <- read.csv(payload$dataPath, check.names = FALSE, na.strings = c("", "NA"), fileEncoding = "UTF-8")
original_row_count <- nrow(data)

entry_ids <- function(entries, field = "id") vapply(entries, function(entry) entry[[field]], character(1))
source(file.path(script_dir, "lib", "empirical_procedure_scope.R"), local = environment())
variable_ids <- entry_ids(metadata$variables)
variable_lookup <- setNames(metadata$variables, variable_ids)
construct_ids <- entry_ids(metadata$constructs)
construct_lookup <- setNames(metadata$constructs, construct_ids)
scale_ids <- entry_ids(metadata$constructs, "scoreId")
item_ids <- unique(unlist(lapply(metadata$constructs, function(construct) unlist(construct$itemIds)), use.names = FALSE))
ordinal_item_ids <- empirical_ordinal_item_ids(metadata)
label_for <- function(id) {
  scale_match <- Filter(function(construct) identical(construct$scoreId, id), metadata$constructs)
  if (length(scale_match) == 1) return(scale_match[[1]]$label)
  if (!is.null(variable_lookup[[id]])) return(variable_lookup[[id]]$label)
  id
}

numeric_types <- c("continuous", "ordinal", "likert")
numeric_observed <- vapply(
  Filter(function(variable) variable$type %in% numeric_types, metadata$variables),
  function(variable) variable$id, character(1)
)
for (id in unique(c(numeric_observed, scale_ids, item_ids))) {
  if (id %in% names(data)) data[[id]] <- suppressWarnings(as.numeric(data[[id]]))
}
if (!is.null(procedure)) {
  numeric_selected <- unique(c(
    if (procedure %in% c("descriptives", "correlation", "groups")) unlist(options$analysisVariableIds),
    options$outcomeVariableId, unlist(options$predictorVariableIds),
    unlist(options$controlVariableIds), unlist(options$responseSurfacePredictorIds)
  ))
  for (id in intersect(numeric_selected, names(data))) {
    if (!is.null(variable_lookup[[id]]) && identical(variable_lookup[[id]]$type, "binary")) {
      values <- suppressWarnings(as.numeric(data[[id]]))
      if (any(!is.na(data[[id]]) & !is.finite(values))) {
        stop(paste0(label_for(id), " 必须先在数据准备中确认数值编码；不会自动将文本类别转换为数字"))
      }
      data[[id]] <- values
    }
  }
}

nonitem_numeric <- vapply(
  Filter(function(variable) variable$type %in% numeric_types && !isTRUE(variable$isItem), metadata$variables),
  function(variable) variable$id, character(1)
)
descriptive_ids <- if (is.null(procedure)) unique(c(scale_ids, nonitem_numeric)) else if (
  procedure %in% c("descriptives", "correlation")
) unlist(options$analysisVariableIds) else character(0)
sample_analysis_ids <- if (is.null(procedure)) unique(c(variable_ids, scale_ids)) else unique(c(
  unlist(options$analysisVariableIds), if (measurement_requested) item_ids else NULL,
  options$outcomeVariableId, unlist(options$predictorVariableIds), unlist(options$controlVariableIds),
  unlist(options$responseSurfacePredictorIds), options$groupVariableId, options$aggregationVariableId
))
if (requested("longitudinal") && !is.null(options$longitudinalPanel)) {
  panel <- options$longitudinalPanel
  sample_analysis_ids <- unique(c(panel$subjectVariableId, unlist(lapply(panel$waves, function(w) c(
    w$xVariableId, w$yVariableId, unlist(w$xItemIds), unlist(w$yItemIds)
  )))))
}
if (requested("diary") && !is.null(options$diaryMultilevel)) {
  diary <- options$diaryMultilevel
  sample_analysis_ids <- unique(c(diary$subjectVariableId, diary$timeVariableId,
    diary$outcomeVariableId, diary$predictorVariableId, diary$mediatorVariableId,
    unlist(diary$controlVariableIds), unlist(diary$level2CovariateIds)))
}
missing_data_report <- if (requested("missing")) build_missing_data_report(
  data, sample_analysis_ids,
  if (is.null(procedure)) descriptive_ids else intersect(sample_analysis_ids, c(scale_ids, numeric_observed)), label_for
) else NULL
sample_complete <- if (length(sample_analysis_ids) > 0L) {
  complete.cases(data[, intersect(sample_analysis_ids, names(data)), drop = FALSE])
} else {
  rep(TRUE, nrow(data))
}
sample_missing_rows <- sum(!sample_complete)
sample_variable_missing_counts <- setNames(
  vapply(intersect(sample_analysis_ids, names(data)), function(id) sum(is.na(data[[id]])), integer(1)),
  intersect(sample_analysis_ids, names(data))
)
sample_missing_patterns <- if (!is.null(missing_data_report$patterns)) {
  lapply(missing_data_report$patterns, function(pattern) list(
    pattern = paste(as.character(unlist(pattern$missingIds)), collapse = ","),
    count = as.integer(pattern$count)
  ))
} else {
  list()
}
sample_flow <- list(
  original = as.integer(original_row_count),
  selected = as.integer(original_row_count),
  included = as.integer(sum(sample_complete)),
  excluded = as.integer(sample_missing_rows),
  missingRows = as.integer(sample_missing_rows),
  finalN = as.integer(sum(sample_complete)),
  missingMethod = "section-specific complete or pairwise observations",
  variableMissingCounts = as.list(sample_variable_missing_counts),
  missingPatterns = sample_missing_patterns
)
descriptives <- lapply(if (requested("descriptives")) descriptive_ids else character(0), function(id) {
  values <- data[[id]]
  valid <- values[is.finite(values)]
  count <- length(valid)
  deviation <- if (count > 1) sd(valid) else NA_real_
  z <- if (count > 1 && is.finite(deviation) && deviation > 0) abs((valid - mean(valid)) / deviation) else rep(0, count)
  skewness <- if (count > 2 && deviation > 0) {
    (count / ((count - 1) * (count - 2))) * sum(((valid - mean(valid)) / deviation)^3)
  } else {
    NA_real_
  }
  kurtosis <- if (count > 3 && deviation > 0) {
    (count * (count + 1) / ((count - 1) * (count - 2) * (count - 3))) * sum(((valid - mean(valid)) / deviation)^4) - 3 * (count - 1)^2 / ((count - 2) * (count - 3))
  } else {
    NA_real_
  }
  list(
    id = id, label = label_for(id), n = count, missing = sum(!is.finite(values)),
    mean = finite_number(mean(valid)), sd = finite_number(deviation),
    minimum = finite_number(min(valid)), maximum = finite_number(max(valid)),
    skewness = finite_number(skewness), kurtosis = finite_number(kurtosis),
    outlierCount = sum(z > 3.29)
  )
})

frequency_variables <- Filter(
  function(variable) variable$type %in% c("binary", "nominal", "ordinal") && !isTRUE(variable$isItem),
  metadata$variables
)
if (!is.null(procedure)) frequency_variables <- if (requested("frequencies")) {
  lapply(unlist(options$analysisVariableIds), function(id) list(id = id, label = label_for(id)))
} else list()
frequencies <- lapply(frequency_variables, function(variable) {
  values <- data[[variable$id]]
  values <- values[!is.na(values) & as.character(values) != ""]
  counts <- sort(table(as.character(values)), decreasing = TRUE)
  levels <- lapply(seq_along(counts), function(index) list(
    level = names(counts)[index], count = as.integer(counts[[index]]),
    proportion = finite_number(as.numeric(counts[[index]]) / length(values))
  ))
  list(id = variable$id, label = variable$label, validCount = length(values), levels = levels)
})
write_progress("correlations", 0.2)
check_cancel()
correlation_ids <- if (!requested("correlation")) character(0) else descriptive_ids[vapply(descriptive_ids, function(id) {
  values <- data[[id]]
  sum(is.finite(values)) >= 3 && length(unique(values[is.finite(values)])) > 1
}, logical(1))]

correlation_method_name <- if (identical(options$correlationMethod, "spearman")) "spearman" else if (identical(options$correlationMethod, "partial")) "partial" else "pearson"
control_ids <- unlist(options$controlVariableIds)
has_controls <- length(control_ids) > 0 && correlation_method_name == "partial"

correlation_count <- length(correlation_ids)
coefficient_matrix <- matrix(NA_real_, correlation_count, correlation_count)
p_value_matrix <- matrix(NA_real_, correlation_count, correlation_count)
count_matrix <- matrix(0L, correlation_count, correlation_count)
ci_lower_matrix <- matrix(NA_real_, correlation_count, correlation_count)
ci_upper_matrix <- matrix(NA_real_, correlation_count, correlation_count)
partial_undefined_pairs <- list()
fisher_correlation_ci <- function(coefficient, sample_size, control_count = 0L, confidence_level = 0.95) {
  if (!is.finite(coefficient) || sample_size <= control_count + 3L) return(c(NA_real_, NA_real_))
  if (abs(coefficient) >= 1) return(c(coefficient, coefficient))
  standard_error <- 1 / sqrt(sample_size - control_count - 3)
  bounds <- tanh(atanh(coefficient) + c(-1, 1) * qnorm(1 - (1 - confidence_level) / 2) * standard_error)
  pmax(-1, pmin(1, bounds))
}
for (i in seq_len(correlation_count)) {
  coefficient_matrix[i, i] <- 1
  p_value_matrix[i, i] <- if (non_iid_context) NA_real_ else 0
  count_matrix[i, i] <- sum(is.finite(data[[correlation_ids[i]]]))
  ci_lower_matrix[i, i] <- if (non_iid_context) NA_real_ else 1
  ci_upper_matrix[i, i] <- if (non_iid_context) NA_real_ else 1
  if (i < correlation_count) {
    for (j in seq.int(i + 1L, correlation_count)) {
      cols <- unique(c(correlation_ids[i], correlation_ids[j], if (has_controls) control_ids else NULL))
      paired <- data[, cols, drop = FALSE]
      paired <- paired[complete.cases(paired), , drop = FALSE]
      count_matrix[i, j] <- count_matrix[j, i] <- nrow(paired)

      min_rows <- if (has_controls) length(control_ids) + 3 else 3
      if (nrow(paired) >= min_rows && all(vapply(paired[, c(correlation_ids[i], correlation_ids[j]), drop = FALSE], function(column) length(unique(column)) > 1, logical(1)))) {
        if (correlation_method_name == "spearman") {
          coefficient <- finite_number(cor(paired[[1]], paired[[2]], method = "spearman"))
          p_value <- if (non_iid_context) {
            NA_real_
          } else {
            finite_number(suppressWarnings(cor.test(paired[[1]], paired[[2]], method = "spearman")$p.value))
          }
        } else if (has_controls) {
          x_val <- paired[[correlation_ids[i]]]
          y_val <- paired[[correlation_ids[j]]]
          z_mat <- as.matrix(paired[, control_ids, drop = FALSE])
          rx <- residuals(lm(x_val ~ z_mat))
          ry <- residuals(lm(y_val ~ z_mat))
          r <- cor(rx, ry)
          df <- nrow(paired) - 2 - ncol(z_mat)
          if (!is.finite(r) || abs(r) >= 1 - 1e-12) {
            coefficient <- NA_real_
            p_value <- NA_real_
            partial_undefined_pairs[[length(partial_undefined_pairs) + 1L]] <- paste0(correlation_ids[i], " × ", correlation_ids[j])
          } else {
            t_stat <- r * sqrt(df / (1 - r^2))
            p_val <- if (non_iid_context) NA_real_ else 2 * pt(abs(t_stat), df = df, lower.tail = FALSE)
            coefficient <- finite_number(r)
            p_value <- finite_number(p_val)
          }
        } else {
          coefficient <- finite_number(cor(paired[[1]], paired[[2]], method = "pearson"))
          p_value <- if (non_iid_context) {
            NA_real_
          } else {
            finite_number(suppressWarnings(cor.test(paired[[1]], paired[[2]], method = "pearson")$p.value))
          }
        }
      } else {
        coefficient <- NA_real_
        p_value <- NA_real_
      }
      interval <- if (non_iid_context) c(NA_real_, NA_real_) else fisher_correlation_ci(
          coefficient,
          nrow(paired),
          if (has_controls) length(control_ids) else 0L,
          confidence_level
        )
      coefficient_matrix[i, j] <- coefficient_matrix[j, i] <- coefficient
      p_value_matrix[i, j] <- p_value_matrix[j, i] <- p_value
      ci_lower_matrix[i, j] <- ci_lower_matrix[j, i] <- interval[[1]]
      ci_upper_matrix[i, j] <- ci_upper_matrix[j, i] <- interval[[2]]
    }
  }
  if (i %% 10L == 0L) check_cancel()
}
correlation_adjustment <- if (options$correlationPAdjust %in% c("none", "holm", "BH")) {
  options$correlationPAdjust
} else {
  "BH"
}
raw_p_value_matrix <- p_value_matrix
adjusted_p_value_matrix <- p_value_matrix
correlation_family_indices <- which(upper.tri(raw_p_value_matrix) & is.finite(raw_p_value_matrix))
if (length(correlation_family_indices) > 0L && !non_iid_context) {
  adjusted_values <- p.adjust(
    raw_p_value_matrix[correlation_family_indices],
    method = correlation_adjustment
  )
  adjusted_p_value_matrix[correlation_family_indices] <- adjusted_values
  for (index in seq_along(correlation_family_indices)) {
    position <- arrayInd(correlation_family_indices[[index]], dim(raw_p_value_matrix))
    adjusted_p_value_matrix[position[[2]], position[[1]]] <- adjusted_values[[index]]
  }
}
p_value_matrix <- adjusted_p_value_matrix
correlation_coefficients <- lapply(seq_len(correlation_count), function(i) as.list(coefficient_matrix[i, ]))
correlation_p_values <- lapply(seq_len(correlation_count), function(i) as.list(p_value_matrix[i, ]))
correlation_p_values_raw <- lapply(seq_len(correlation_count), function(i) as.list(raw_p_value_matrix[i, ]))
correlation_p_values_adjusted <- lapply(seq_len(correlation_count), function(i) as.list(adjusted_p_value_matrix[i, ]))
correlation_counts <- lapply(seq_len(correlation_count), function(i) as.list(count_matrix[i, ]))
correlation_ci_lower <- lapply(seq_len(correlation_count), function(i) as.list(ci_lower_matrix[i, ]))
correlation_ci_upper <- lapply(seq_len(correlation_count), function(i) as.list(ci_upper_matrix[i, ]))

method_label <- if (correlation_method_name == "spearman") {
  "Spearman rank pairwise complete observations"
} else if (has_controls) {
  paste0("Partial correlation (Pearson, controlling for: ", paste(vapply(control_ids, label_for, character(1)), collapse = ", "), ")")
} else {
  "Pearson pairwise complete observations"
}

correlations <- list(
  variables = lapply(correlation_ids, function(id) list(id = id, label = label_for(id))),
  coefficients = correlation_coefficients,
  pValues = correlation_p_values,
  pValuesRaw = correlation_p_values_raw,
  pValuesAdjusted = correlation_p_values_adjusted,
  pValueDisplay = "adjusted",
  multiplicity = list(
    familyId = "all_unique_off_diagonal_correlations",
    familySize = as.integer(length(correlation_family_indices)),
    adjustment = correlation_adjustment,
    scope = "all finite unique off-diagonal correlations in this report",
    confidenceIntervalsAdjusted = FALSE
  ),
  counts = correlation_counts,
  ciLower = correlation_ci_lower, ciUpper = correlation_ci_upper, confidenceLevel = confidence_level,
  multiplicityFamilyId = multiplicity_family_id,
  confidenceIntervalMethod = if (correlation_method_name == "spearman") {
    "Fisher z approximation for Spearman rank correlation"
  } else if (has_controls) {
    "Fisher z transformation adjusted for the number of control variables"
  } else {
    "Fisher z transformation"
  },
  method = method_label,
  inferenceAvailable = !non_iid_context,
  inferenceReason = if (non_iid_context) {
    paste0(non_iid_reason_prefix, "_REQUIRE_DEPENDENCE_AWARE_CORRELATION_INFERENCE")
  } else {
    NULL
  },
  dependenceStructure = if (nested_context) "nested" else if (repeated_context) "repeated" else "independent"
)

item_complete <- data[, if (measurement_requested) item_ids else character(0), drop = FALSE]
item_complete <- item_complete[complete.cases(item_complete), , drop = FALSE]
usable_items <- names(item_complete)[vapply(item_complete, function(column) length(unique(column)) > 1, logical(1))]
item_complete <- item_complete[, usable_items, drop = FALSE]
item_correlation_info <- if (requested("efa") || requested("common_method")) {
  empirical_build_item_correlation(item_complete, usable_items, ordinal_item_ids)
} else list()
item_correlation <- item_correlation_info$correlation
item_correlation_type <- item_correlation_info$correlationType
item_correlation_reason <- item_correlation_info$reason
eigenvalues <- if (!is.null(item_correlation)) eigen(item_correlation, symmetric = TRUE, only.values = TRUE)$values else numeric(0)
if (requested("common_method")) source(file.path(script_dir, "lib", "empirical_cmb_procedure.R"), local = environment())

if (requested("efa")) factorability <- compute_factorability(item_correlation, item_complete)
if (non_iid_context && !is.null(factorability$bartlett)) {
  factorability$bartlett$pValue <- NA_real_
  factorability$bartlett$inferenceReason <- paste0(non_iid_reason_prefix, "_VIOLATE_IID_BARTLETT_REFERENCE_DISTRIBUTION")
}
kmo_skipped_reason <- factorability$kmoSkippedReason

if (requested("efa")) source(file.path(script_dir, "lib", "empirical_efa_procedure.R"), local = environment())

if (requested("cfa") || requested("validity")) source(file.path(script_dir, "lib", "empirical_cfa_procedure.R"), local = environment())

if (requested("invariance")) source(file.path(script_dir, "lib", "empirical_invariance_procedure.R"), local = environment())

if (requested("validity")) source(file.path(script_dir, "lib", "empirical_validity_procedure.R"), local = environment())

paper_summary_table <- if (is.null(procedure)) build_empirical_paper_summary(
  correlation_ids, descriptives, construct_validity, construct_score_ids,
  count_matrix, coefficient_matrix, p_value_matrix, raw_p_value_matrix,
  adjusted_p_value_matrix, ci_lower_matrix, ci_upper_matrix,
  method_label, correlations$multiplicity, label_for, confidence_level
) else NULL
aggregation_diagnostics <- if (requested("aggregation")) build_empirical_aggregation_diagnostics(
  data, options, metadata$constructs, label_for
) else NULL

group_comparison <- if (requested("groups")) fit_empirical_group_comparison(
  data, options, if (is.null(procedure)) scale_ids else unlist(options$analysisVariableIds), label_for, finite_number, non_iid_context, confidence_level,
  multiplicity_family_id
) else NULL

hierarchical_regression <- NULL
response_surface <- NULL
write_progress("hierarchical_regression", 0.9)
check_cancel()
if ((requested("regression") || requested("relative_importance")) && !non_iid_context && !is.null(options$outcomeVariableId) && options$outcomeVariableId != "" && length(options$predictorVariableIds) > 0) {
  hierarchical_regression <- fit_hierarchical_regression(
    data, options, label_for, confidence_level, multiplicity_family_id
  )
}
if (
  requested("response_surface") && !non_iid_context && !is.null(options$outcomeVariableId) && options$outcomeVariableId != "" &&
  length(options$responseSurfacePredictorIds) == 2L
) {
  response_surface <- fit_polynomial_response_surface(
    data,
    options$outcomeVariableId,
    unlist(options$responseSurfacePredictorIds),
    unlist(options$controlVariableIds),
    label_for,
    confidence_level = confidence_level
  )
}

global_multiplicity <- researchpath_apply_global_multiplicity(
  options, non_iid_context, correlation_family_indices, raw_p_value_matrix, correlation_count,
  correlations, group_comparison, hierarchical_regression, multiplicity_family_id,
  study_plan_multiplicity
)
correlations <- global_multiplicity$correlations
group_comparison <- global_multiplicity$groupComparison
hierarchical_regression <- global_multiplicity$hierarchicalRegression
global_multiplicity_adjustment <- global_multiplicity$adjustment

longitudinal_panel <- NULL
if (requested("longitudinal") && !is.null(options$longitudinalPanel)) {
  write_progress("longitudinal_panel", 0.92)
  check_cancel()
  longitudinal_panel <- fit_longitudinal_panel(
    data,
    options$longitudinalPanel,
    label_for,
    confidence_level = confidence_level
  )
}

diary_multilevel <- NULL
if (requested("diary") && !is.null(options$diaryMultilevel)) {
  write_progress("diary_multilevel", 0.94)
  check_cancel()
  diary_multilevel <- fit_diary_multilevel(
    data,
    options$diaryMultilevel,
    label_for,
    confidence_level = confidence_level
  )
}

if (identical(procedure, "reliability")) source(file.path(script_dir, "lib", "empirical_reliability_procedure.R"), local = environment())
source(file.path(script_dir, "lib", "empirical_report_assembly.R"), local = environment())

result <- list(
  schemaVersion = "1.0.0", reportId = payload$reportId, datasetId = payload$datasetId,
  measurementVersionId = payload$measurementVersionId, createdAt = payload$createdAt,
  sample = list(
    rowCount = nrow(data),
    itemCompleteCases = nrow(item_complete),
    constructCount = length(metadata$constructs),
    measurementAdequacy = measurement_sample_adequacy
  ),
  sampleFlow = sample_flow,
  publicationEligible = publication_eligible,
  requiresManualReview = !publication_eligible,
  publicationEligibilityReasons = as.list(publication_reasons),
  reliability = reliability,
  options = options, descriptives = descriptives, frequencies = frequencies,
  missingDataReport = missing_data_report,
  correlations = correlations, paperSummaryTable = paper_summary_table,
  multiplicity = list(
    familyId = if (identical(global_multiplicity$declarationStatus, "typed")) "declared" else multiplicity_family_id,
    scope = as.list(c("correlations", "group_comparison", "hierarchical_regression")),
    adjustment = global_multiplicity_adjustment,
    globalAdjustmentApplied = global_multiplicity$applied,
    components = as.list(c("correlations", "group_comparison", "hierarchical_regression")),
    declarationStatus = global_multiplicity$declarationStatus,
    executionDerivedFamily = global_multiplicity$executionDerivedFamily,
    declaredFamilySize = global_multiplicity$familySize,
    declaredFamilyLedger = global_multiplicity$ledger$families,
    resultLedger = global_multiplicity$ledger$results,
    unmappedResultKeys = global_multiplicity$unmappedResultKeys,
    missingDeclaredEstimandIds = global_multiplicity$missingDeclaredEstimandIds,
    incompletePrimaryFamilyIds = global_multiplicity$incompletePrimaryFamilyIds,
    primaryFamilyIncomplete = global_multiplicity$primaryFamilyIncomplete,
    hypothesisBoundary = if (identical(global_multiplicity$declarationStatus, "typed")) {
      "只有能映射到冻结声明 estimand 的 primary/exploratory 结果进入 declared multiplicity family；adjustment_covariate 与未声明诊断不进入 family，模型画布上的具名假设由 Evidence Graph 单独绑定。"
    } else {
      "未提供预声明时按已执行结果构造推断族；它不表达冻结的 primary/exploratory intent，且不得达到 publication-ready。"
    }
  ),
  commonMethodBias = common_method, factorability = factorability,
  efa = efa, cfa = cfa, validity = validity, measurementInvariance = measurement_invariance,
  advancedMeasurementBoundary = list(
    executedInBaseReport = FALSE,
    availableThrough = "advanced_workbench",
    sliceId = "questionnaire_measurement.esem_bifactor_irt",
    methods = as.list(c("ESEM", "Bifactor", "IRT", "DIF")),
    requirement = "必须在高级问卷测量工作台显式选择方法、题项尺度、估计器和模型规格后执行。"
  ),
  groupComparison = group_comparison, aggregationDiagnostics = aggregation_diagnostics,
  hierarchicalRegression = hierarchical_regression, responseSurface = response_surface,
  longitudinalPanel = longitudinal_panel,
  diaryMultilevel = diary_multilevel,
  warnings = warnings,
  provenance = list(
    procedure = procedure,
    requestedProcedures = if (is.null(procedure)) "combined_bundle" else procedure,
    dependencies = if (identical(procedure, "validity")) list("cfa") else if (identical(procedure, "relative_importance")) list("regression") else list(),
    engine = "ResearchPath empirical base-R engine", engineVersion = "1.0.0",
    rVersion = R.version.string, jsonliteVersion = as.character(packageVersion("jsonlite")),
    missingPolicy = "section-specific complete or pairwise observations",
    confidenceLevel = confidence_level,
    multiplicityFamilyId = multiplicity_family_id,
    contextTimeStructure = options$contextTimeStructure,
    contextDependenceStructure = options$contextDependenceStructure,
    contextDesign = options$contextDesign,
    applicableCapabilitySlices = options$applicableCapabilitySlices,
    cfaEstimator = if (isTRUE(cfa$available)) cfa$estimator else "not available",
    executionMode = Sys.getenv("RESEARCHPATH_RUNTIME_MODE", "rscript"),
    parallelAnalysis = if (is.null(parallel_res)) NULL else list(
      backend = parallel_res$parallelBackend,
      workers = parallel_res$parallelWorkers,
      rngStrategy = parallel_res$rngStrategy
    ),
    htmtBootstrap = list(
      replicates = htmt_ci$replicates,
      seed = htmt_ci$seed,
      backend = htmt_ci$parallelBackend,
      workers = htmt_ci$parallelWorkers,
      rngStrategy = htmt_ci$rngStrategy
    )
  )
)
researchpath_write_result(result, args[[2]])
write_progress("r_engine_succeeded", 0.97)
