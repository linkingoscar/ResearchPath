# 独立加载（测试/复用）时引导 seed 工具；入口脚本已先行 source。
if (!exists("researchpath_seed", mode = "function", inherits = TRUE)) {
  if (file.exists(file.path("engine", "R", "lib", "seed_utils.R"))) {
    source(file.path("engine", "R", "lib", "seed_utils.R"))
  }
}

# ----------------------------------------------------
# SEM 分析支线
# ----------------------------------------------------
args_all <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("--file=", args_all, value = TRUE)
script_dir <- if (length(file_arg) > 0) {
  dirname(substring(file_arg[1], 8))
} else {
  "engine/R"
}
source(file.path(script_dir, "r_sem_helpers.R"))
source(file.path(script_dir, "lib", "output_contract.R"))
source(file.path(script_dir, "lib", "sem_invariance_helpers.R"))
source(file.path(script_dir, "lib", "sem_failure.R"), local = environment())

write_progress("fitting_sem", 0.30)

model_syntax <- payload$lavaanSyntax
raw <- read.csv(payload$dataPath, check.names = FALSE, na.strings = c("", "NA"), fileEncoding = "UTF-8")

required_vars <- unique(unlist(payload$requiredVariables))
analysis_data <- raw[, required_vars, drop = FALSE]

group_var <- spec$estimation$groupVariableId
group_var_col <- NULL
if (!is.null(group_var)) {
  group_var_col <- group_var
  for (node in spec$nodes) {
    if (identical(node$id, group_var)) {
      if (!is.null(node$variableId)) {
        group_var_col <- node$variableId
      }
      break
    }
  }
}

for (col in names(analysis_data)) {
  if (!identical(col, group_var_col)) {
    analysis_data[[col]] <- as.numeric(analysis_data[[col]])
  }
}

estimator <- spec$estimation$estimator
if (is.null(estimator)) estimator <- "ML"

missing_method <- spec$estimation$missing
missing_param <- if (estimator %in% c("ML", "MLR") && identical(missing_method, "fiml")) "fiml" else "listwise"
original_n <- nrow(analysis_data)
model_columns <- setdiff(names(analysis_data), group_var_col)
variable_missing_counts <- as.list(vapply(
  analysis_data[, model_columns, drop = FALSE],
  function(values) sum(is.na(values)),
  integer(1)
))
missing_pattern_labels <- apply(
  is.na(analysis_data[, model_columns, drop = FALSE]),
  1,
  function(flags) paste0(as.integer(flags), collapse = "")
)
missing_pattern_table <- sort(table(missing_pattern_labels), decreasing = TRUE)
missing_patterns <- lapply(names(missing_pattern_table), function(pattern) {
  list(pattern = pattern, count = as.integer(missing_pattern_table[[pattern]]))
})
if (identical(missing_param, "fiml")) {
  informative <- rowSums(!is.na(analysis_data[, model_columns, drop = FALSE])) > 0
  if (!is.null(group_var_col) && group_var_col %in% names(analysis_data)) {
    informative <- informative & !is.na(analysis_data[[group_var_col]])
  }
  analysis_data <- analysis_data[informative, , drop = FALSE]
} else {
  analysis_data <- analysis_data[complete.cases(analysis_data), , drop = FALSE]
}
included_n <- nrow(analysis_data)

if (included_n < 10) stop("Fewer than 10 usable cases remain for SEM analysis")

ordered_vars <- if (identical(estimator, "WLSMV")) unlist(payload$orderedVariables) else NULL

requested_standard_errors <- if (
  is.null(spec$estimation$standardErrors) ||
    !is.character(spec$estimation$standardErrors) ||
    length(spec$estimation$standardErrors) != 1L
) {
  "classical"
} else {
  spec$estimation$standardErrors
}
se_param <- spec$estimation$standardErrors
if (is.null(se_param) || se_param == "classical") se_param <- "standard"
if (se_param == "hc3") se_param <- "robust"
# 实际执行的 se 设置（lavaan se= 参数），provenance 直接记录该值，
# 不由稳健卡方是否存在反推。
se_executed <- switch(se_param,
  "bootstrap" = "bootstrap",
  "robust" = "robust",
  "standard"
)

bootstrap_args <- list()
if (identical(se_param, "bootstrap")) {
  reps <- as.integer(spec$estimation$bootstrap$replicates)
  bootstrap_args$bootstrap <- reps
  set.seed(researchpath_seed(spec$estimation$bootstrap$seed))
}

resource_replicates <- if (identical(se_param, "bootstrap")) reps else 1L
compare_structural_paths <- isTRUE(spec$estimation$multiGroup$compareStructuralPaths)
resource_fit_multiplier <- if (isTRUE(spec$estimation$invariance)) {
  if (compare_structural_paths) 6L else 5L
} else {
  1L
}
researchpath_budget_sem(
  included_n,
  length(model_columns),
  resource_replicates,
  resource_fit_multiplier
)

sem_args <- list(
  model = model_syntax,
  data = analysis_data,
  estimator = estimator,
  missing = missing_param,
  ordered = ordered_vars,
  se = se_param
)
if (identical(estimator, "WLSMV")) sem_args$parameterization <- "theta"
sem_args <- c(sem_args, bootstrap_args)

fit <- tryCatch({
  do.call(sem, sem_args)
}, error = function(error) {
  NULL
})
if (is.null(fit)) write_sem_failure("SEM_FIT_FAILED", "lavaan 拟合失败；已生成不可发布的失败结果并要求人工复核。")
fit_nobs <- tryCatch(lavInspect(fit, "nobs"), error = function(error) included_n)
included_n <- sum(as.numeric(fit_nobs))
if (!isTRUE(tryCatch(lavInspect(fit, "converged"), error = function(error) FALSE))) {
  write_sem_failure("SEM_NOT_CONVERGED", "lavaan 模型未收敛；已生成不可发布的失败结果并要求人工复核。")
}

sem_warnings <- list()
parameter_table <- tryCatch(parameterEstimates(fit), error = function(error) NULL)
if (!is.null(parameter_table)) {
  negative_variances <- parameter_table[
    parameter_table$op == "~~" & parameter_table$lhs == parameter_table$rhs &
      is.finite(parameter_table$est) & parameter_table$est < 0,
    ,
    drop = FALSE
  ]
  if (nrow(negative_variances) > 0) {
    sem_warnings[[length(sem_warnings) + 1]] <- list(
      code = "SEM_NEGATIVE_VARIANCE",
      severity = "warning",
      message = paste0(
        "检测到负方差（Heywood case）：",
        paste(unique(negative_variances$lhs), collapse = "、"),
        "。请检查模型设定、题项质量和样本量。"
      )
    )
  }
}
latent_covariance <- tryCatch(lavInspect(fit, "cov.lv"), error = function(error) NULL)
if (!is.null(latent_covariance) && nrow(latent_covariance) > 1) {
  latent_eigenvalues <- tryCatch(eigen(latent_covariance, symmetric = TRUE, only.values = TRUE)$values, error = function(error) numeric(0))
  if (length(latent_eigenvalues) > 0 && any(latent_eigenvalues <= 1e-8)) {
    sem_warnings[[length(sem_warnings) + 1]] <- list(
      code = "SEM_NON_POSITIVE_DEFINITE_LATENT_COVARIANCE",
      severity = "warning",
      message = "潜变量协方差矩阵非正定或近奇异；路径与区分效度结论需要谨慎解释。"
    )
  }
}

write_progress("building_sem_results", 0.60)

fit_indices <- get_fit_indices(fit)
higher_order_ids <- vapply(
  Filter(function(latent) identical(latent$level, "higher_order"), spec$latents),
  function(latent) latent$id,
  character(1)
)
confidence_level <- suppressWarnings(as.numeric(spec$estimation$confidenceLevel))
if (length(confidence_level) != 1L || !is.finite(confidence_level)) confidence_level <- 0.95
sem_params <- get_sem_parameters(fit, higher_order_ids, confidence_level)
reliability_bundle <- calc_latent_reliability(fit, analysis_data, spec$latents)
reliability <- reliability_bundle$reliability
sem_warnings <- c(sem_warnings, reliability_bundle$warnings)

sem_result <- list(
  fitIndices = fit_indices,
  loadings = sem_params$loadings,
  paths = sem_params$paths,
  reliability = reliability,
  modelStructure = list(
    firstOrderLatents = as.list(vapply(
      Filter(function(latent) !identical(latent$level, "higher_order"), spec$latents),
      function(latent) latent$id,
      character(1)
    )),
    higherOrderLatents = as.list(higher_order_ids)
  )
)
# 可靠性诊断类警告只抑制具体信度指标（CR/ω 置 null），不代表模型估计
# 失败或异常解；路径、拟合与样本流证据不受影响，因此不得把整个结果
# 标记为不可发布。Heywood、非正定与不收敛仍走同一检查。
reliability_diagnostic_codes <- c("SEM_CR_SUPPRESSED_CORRELATED_RESIDUALS")
sem_publication_reasons <- unique(vapply(
  Filter(
    function(warning) !warning$code %in% reliability_diagnostic_codes,
    sem_warnings
  ),
  function(warning) warning$code,
  character(1)
))
sem_result$publicationEligible <- length(sem_publication_reasons) == 0L
sem_result$requiresManualReview <- length(sem_publication_reasons) > 0L
sem_result$publicationEligibilityReasons <- as.list(sem_publication_reasons)
sem_result$numericReferenceMatrix <- list(
  execution = list(
    requestedEstimator = estimator,
    executedEstimator = estimator,
    requestedStandardErrors = requested_standard_errors,
    executedStandardErrors = se_executed,
    requestedMissing = missing_method,
    executedMissing = missing_param,
    fixtureId = "sem-numeric-reference-v1",
    tolerancePolicy = "locked fixture values with explicit absolute tolerances"
  ),
  continuous = list(
    estimator = "ML",
    robustEstimator = "MLR",
    missing = "FIML when estimation.missing=fiml; otherwise listwise",
    standardErrors = "standard or robust",
    status = "reference"
  ),
  ordinal = list(
    estimator = "WLSMV",
    missing = "listwise",
    standardErrors = "robust/scaled as provided by lavaan",
    status = "reference"
  ),
  invariance = list(
    sequence = "configural → metric → scalar/threshold → strict",
    releasePolicy = "partial releases require explicit rationale",
    status = "reference"
  ),
  failureStates = list(
    heywood = "publicationEligible=false; requiresManualReview=true",
    nonPositiveDefinite = "publicationEligible=false; requiresManualReview=true",
    nonConvergence = "results are not published"
  )
)

invariance_result <- NULL
group_var <- spec$estimation$groupVariableId
run_invariance <- isTRUE(spec$estimation$invariance)

group_var_col <- NULL
if (!is.null(group_var)) {
  group_var_col <- group_var
  for (node in spec$nodes) {
    if (identical(node$id, group_var)) {
      if (!is.null(node$variableId)) {
        group_var_col <- node$variableId
      }
      break
    }
  }
}

if (run_invariance && !is.null(group_var_col) && group_var_col %in% names(analysis_data)) {
  write_progress("running_invariance", 0.75)

  safe_sem <- function(group_equal = NULL, group_partial = NULL) {
    invariance_args <- list(
      model = model_syntax,
      data = analysis_data,
      estimator = estimator,
      missing = missing_param,
      ordered = ordered_vars,
      group = group_var_col,
      se = "standard",
      meanstructure = TRUE
    )
    if (identical(estimator, "WLSMV")) invariance_args$parameterization <- "theta"
    if (!is.null(group_equal)) invariance_args$group.equal <- group_equal
    if (!is.null(group_partial) && length(group_partial) > 0) {
      invariance_args$group.partial <- group_partial
    }
    invariance_args <- c(invariance_args, bootstrap_args)
    tryCatch(do.call(sem, invariance_args), error = function(e) NULL)
  }

  # 先拟合 configural：WLSMV 部分等值的阈值参数名必须与模型实际自由阈值
  # 一致。以数据 unique 值数近似会在类别缺失时拼错 group.partial，
  # 因此阈值计数取自 configural 拟合的 parameterTable。
  fit_conf <- safe_sem(NULL, NULL)
  conf_param_table <- tryCatch(parameterTable(fit_conf), error = function(e) NULL)
  count_free_thresholds <- function(indicator_id) {
    if (is.null(conf_param_table)) return(NA_integer_)
    rows <- conf_param_table[
      conf_param_table$op == "|" & conf_param_table$lhs == indicator_id &
        conf_param_table$free > 0,
      ,
      drop = FALSE
    ]
    as.integer(sum(rows$free > 0))
  }

  release_requests <- spec$estimation$multiGroup$partialInvarianceReleases
  if (is.null(release_requests)) release_requests <- list()
  loading_releases <- character(0)
  scalar_releases <- character(0)
  strict_releases <- character(0)
  expanded_release_rows <- list()
  for (release in release_requests) {
    indicator_id <- release$indicatorId
    lavaan_parameters <- character(0)
    if (identical(release$constraint, "loading")) {
      lavaan_parameters <- paste0(release$latentId, "=~", indicator_id)
      loading_releases <- c(loading_releases, lavaan_parameters)
    } else if (identical(release$constraint, "intercept_or_threshold")) {
      if (identical(estimator, "WLSMV")) {
        threshold_count <- count_free_thresholds(indicator_id)
        # configural 失败等极端情形下退回数据分布近似，并保持旧行为可用。
        if (is.na(threshold_count)) {
          threshold_count <- max(length(unique(na.omit(analysis_data[[indicator_id]]))) - 1L, 0L)
        }
        if (threshold_count > 0L) {
          lavaan_parameters <- paste0(indicator_id, "|t", seq_len(threshold_count))
        }
      } else {
        lavaan_parameters <- paste0(indicator_id, "~1")
      }
      scalar_releases <- c(scalar_releases, lavaan_parameters)
    } else if (identical(release$constraint, "residual")) {
      lavaan_parameters <- paste0(indicator_id, "~~", indicator_id)
      strict_releases <- c(strict_releases, lavaan_parameters)
    }
    expanded_release_rows[[length(expanded_release_rows) + 1]] <- list(
      stage = release$stage,
      constraint = release$constraint,
      latentId = release$latentId,
      indicatorId = indicator_id,
      rationale = release$rationale,
      lavaanParameters = as.list(lavaan_parameters)
    )
  }
  metric_partial <- unique(loading_releases)
  scalar_partial <- unique(c(metric_partial, scalar_releases))
  strict_partial <- unique(c(scalar_partial, strict_releases))

  scalar_constraints <- if (identical(estimator, "WLSMV")) c("loadings", "thresholds") else c("loadings", "intercepts")
  strict_constraints <- c(scalar_constraints, "residuals")
  # configural 已在阈值计数阶段先行拟合，此处只跑 metric/scalar/strict。
  fit_specs <- list(
    list(equal = c("loadings"), partial = metric_partial),
    list(equal = scalar_constraints, partial = scalar_partial),
    list(equal = strict_constraints, partial = strict_partial)
  )
  configured_workers <- suppressWarnings(as.integer(getOption("researchpath.future.workers", 1L)))
  use_parallel_invariance <-
    !is.na(configured_workers) &&
    configured_workers > 1L &&
    requireNamespace("future.apply", quietly = TRUE)
  fit_one_spec <- function(fit_spec) safe_sem(fit_spec$equal, fit_spec$partial)
  invariance_fits_rest <- if (use_parallel_invariance) {
    future.apply::future_lapply(
      fit_specs,
      fit_one_spec,
      future.seed = TRUE,
      future.stdout = FALSE,
      future.packages = "lavaan"
    )
  } else {
    lapply(fit_specs, fit_one_spec)
  }
  fit_metric <- invariance_fits_rest[[1]]
  fit_scalar <- invariance_fits_rest[[2]]
  fit_strict <- invariance_fits_rest[[3]]
  
  fit_m0 <- sem_inv_fit_indices_safe(fit_conf)
  fit_m1 <- sem_inv_fit_indices_safe(fit_metric)
  fit_m2 <- sem_inv_fit_indices_safe(fit_scalar)
  fit_m3 <- sem_inv_fit_indices_safe(fit_strict)

  comp_metric <- sem_inv_test_lrt(fit_metric, fit_conf)
  comp_scalar <- sem_inv_test_lrt(fit_scalar, fit_metric)
  comp_strict <- sem_inv_test_lrt(fit_strict, fit_scalar)

  fit_structural <- if (compare_structural_paths) {
    safe_sem(c(scalar_constraints, "regressions"), scalar_partial)
  } else {
    NULL
  }
  fit_structural_indices <- if (compare_structural_paths) sem_inv_fit_indices_safe(fit_structural) else NULL
  comp_structural <- if (compare_structural_paths) sem_inv_test_lrt(fit_structural, fit_scalar) else NULL
  
  comparison_cfi <- function(indices) {
    if (!is.null(indices$robustCfi) && is.finite(indices$robustCfi)) indices$robustCfi else indices$cfi
  }
  comparison_rmsea <- function(indices) {
    if (!is.null(indices$robustRmsea) && is.finite(indices$robustRmsea)) indices$robustRmsea else indices$rmsea
  }
  cfi_m0 <- comparison_cfi(fit_m0); cfi_m1 <- comparison_cfi(fit_m1)
  cfi_m2 <- comparison_cfi(fit_m2); cfi_m3 <- comparison_cfi(fit_m3)
  rmsea_m0 <- comparison_rmsea(fit_m0); rmsea_m1 <- comparison_rmsea(fit_m1)
  rmsea_m2 <- comparison_rmsea(fit_m2); rmsea_m3 <- comparison_rmsea(fit_m3)

  delta_cfi_m1 <- if (is.finite(cfi_m1) && is.finite(cfi_m0)) cfi_m1 - cfi_m0 else NA_real_
  delta_rmsea_m1 <- if (is.finite(rmsea_m1) && is.finite(rmsea_m0)) rmsea_m1 - rmsea_m0 else NA_real_
  
  delta_cfi_m2 <- if (is.finite(cfi_m2) && is.finite(cfi_m1)) cfi_m2 - cfi_m1 else NA_real_
  delta_rmsea_m2 <- if (is.finite(rmsea_m2) && is.finite(rmsea_m1)) rmsea_m2 - rmsea_m1 else NA_real_
  
  delta_cfi_m3 <- if (is.finite(cfi_m3) && is.finite(cfi_m2)) cfi_m3 - cfi_m2 else NA_real_
  delta_rmsea_m3 <- if (is.finite(rmsea_m3) && is.finite(rmsea_m2)) rmsea_m3 - rmsea_m2 else NA_real_
  
  inv_holds_m1 <- if (is.finite(delta_cfi_m1) && is.finite(delta_rmsea_m1)) (delta_cfi_m1 >= -0.01) && (delta_rmsea_m1 <= 0.015) else NA
  inv_holds_m2 <- if (is.finite(delta_cfi_m2) && is.finite(delta_rmsea_m2)) (delta_cfi_m2 >= -0.01) && (delta_rmsea_m2 <= 0.015) else NA
  inv_holds_m3 <- if (is.finite(delta_cfi_m3) && is.finite(delta_rmsea_m3)) (delta_cfi_m3 >= -0.01) && (delta_rmsea_m3 <= 0.015) else NA

  group_sizes <- as.list(table(analysis_data[[group_var_col]], useNA = "no"))
  group_parameters <- sem_inv_extract_group_parameters(fit_conf, higher_order_ids, confidence_level)
  
  invariance_result <- list(
    models = list(
      list(model = "configural", constraints = list(), fitIndices = fit_m0),
      list(model = "metric", constraints = as.list(c("loadings")), fitIndices = fit_m1, releasedParameters = as.list(metric_partial)),
      list(model = "scalar", constraints = as.list(scalar_constraints), fitIndices = fit_m2, releasedParameters = as.list(scalar_partial)),
      list(model = "strict", constraints = as.list(strict_constraints), fitIndices = fit_m3, releasedParameters = as.list(strict_partial))
    ),
    comparisons = list(
      list(
        comparison = "metric_vs_configural",
        deltaChiSquare = comp_metric$chisq_diff,
        deltaDf = as.integer(comp_metric$df_diff),
        pValue = comp_metric$p_val,
        deltaCfi = delta_cfi_m1,
        deltaRmsea = delta_rmsea_m1,
        invarianceHolds = inv_holds_m1,
        evaluationStatus = if (is.na(inv_holds_m1)) "not_evaluable" else if (inv_holds_m1) "pass" else "fail"
      ),
      list(
        comparison = "scalar_vs_metric",
        deltaChiSquare = comp_scalar$chisq_diff,
        deltaDf = as.integer(comp_scalar$df_diff),
        pValue = comp_scalar$p_val,
        deltaCfi = delta_cfi_m2,
        deltaRmsea = delta_rmsea_m2,
        invarianceHolds = inv_holds_m2,
        evaluationStatus = if (is.na(inv_holds_m2)) "not_evaluable" else if (inv_holds_m2) "pass" else "fail"
      ),
      list(
        comparison = "strict_vs_scalar",
        deltaChiSquare = comp_strict$chisq_diff,
        deltaDf = as.integer(comp_strict$df_diff),
        pValue = comp_strict$p_val,
        deltaCfi = delta_cfi_m3,
        deltaRmsea = delta_rmsea_m3,
        invarianceHolds = inv_holds_m3,
        evaluationStatus = if (is.na(inv_holds_m3)) "not_evaluable" else if (inv_holds_m3) "pass" else "fail"
      )
    ),
    estimator = estimator,
    groupSizes = group_sizes,
    groupParameters = group_parameters,
    pathComparisons = sem_inv_extract_path_comparisons(group_parameters, confidence_level),
    predictionPlots = sem_inv_build_prediction_plots(fit_conf, spec$nodes, group_var_col, analysis_data, confidence_level),
    partialInvarianceReleases = expanded_release_rows,
    latentMeans = sem_inv_extract_latent_means(
      fit_scalar,
      isTRUE(spec$estimation$multiGroup$estimateLatentMeans),
      spec$latents
    ),
    structuralComparison = if (compare_structural_paths) list(
      model = "structural",
      constraints = as.list(c(scalar_constraints, "regressions")),
      fitIndices = fit_structural_indices,
      deltaChiSquare = comp_structural$chisq_diff,
      deltaDf = as.integer(comp_structural$df_diff),
      pValue = comp_structural$p_val
    ) else NULL
  )
}

result <- list(
  schemaVersion = "0.3.0",
  run = list(
    id = payload$runId,
    status = "succeeded",
    modelId = spec$modelId,
    modelHash = payload$modelHash,
    modelVersionId = if (is.null(payload$modelVersionId)) "demo" else payload$modelVersionId,
    template = "sem",
    durationMilliseconds = as.integer((proc.time()[[3]] - started_at) * 1000)
  ),
  sampleFlow = list(
    original = original_n,
    selected = original_n,
    included = included_n,
    excluded = original_n - included_n,
    missingRows = original_n - included_n,
    finalN = included_n,
    missingMethod = spec$estimation$missing,
    variableMissingCounts = variable_missing_counts,
    missingPatterns = missing_patterns
  ),
  equations = list(),
  diagnostics = list(),
  effects = list(),
  probes = list(),
  johnsonNeyman = NULL,
  moderator = NULL,
  semResult = sem_result,
  publicationEligible = isTRUE(sem_result$publicationEligible),
  requiresManualReview = isTRUE(sem_result$requiresManualReview),
  publicationEligibilityReasons = as.list(sem_publication_reasons),
  claimBoundary = list(
    claimMode = if (identical(spec$design$timeStructure, "experimental")) "experimental_effect" else "association",
    causalLanguageAllowed = identical(spec$design$timeStructure, "experimental") && identical(spec$design$claimMode, "causal_with_assumptions"),
    temporalPrecedenceEstablished = spec$design$timeStructure %in% c("longitudinal", "experimental"),
    experimentalEffectEstablished = identical(spec$design$timeStructure, "experimental")
  ),
  invarianceResult = invariance_result,
  warnings = sem_warnings,
  provenance = list(
    engine = "researchpath-r",
    engineVersion = "0.3.0",
    rVersion = R.version.string,
    jsonliteVersion = as.character(packageVersion("jsonlite")),
    dataSha256 = payload$dataSha256,
    standardErrors = se_executed,
    confidenceLevel = confidence_level,
    estimator = estimator,
    missingMethodExecuted = missing_param,
    bootstrapReplicates = if (identical(se_param, "bootstrap")) as.integer(spec$estimation$bootstrap$replicates) else 0L,
    # 仅在 bootstrap 实际执行时报告种子；否则为 null（NA 经 na="null" 序列化），
    # 不使用固定占位值误导复现消费者。
    seed = if (identical(se_param, "bootstrap")) researchpath_seed(spec$estimation$bootstrap$seed) else NA_integer_
  )
)

researchpath_write_result(result, output_path)
write_progress("succeeded", 1.0, 0L, 0L)
q(save = "no")
