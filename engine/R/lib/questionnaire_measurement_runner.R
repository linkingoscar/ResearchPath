run_questionnaire_measurement <- function() {
  model_type <- spec$modelType
  item_scale <- if (is.null(spec$itemScale)) "continuous" else spec$itemScale
  estimator <- if (is.null(spec$estimator)) "ML" else spec$estimator
  rotation <- if (is.null(spec$rotation)) "promax" else spec$rotation
  extraction_method <- if (is.null(spec$extractionMethod)) "ml" else spec$extractionMethod
  required_packages <- unique(c(
    if (model_type %in% c("reliability", "cfa", "measurement_invariance", "bifactor", "esem_bifactor_irt", "ulmc", "common_method_bias")) "lavaan" else character(0),
    if (model_type %in% c("reliability", "esem", "esem_bifactor_irt")) "psych" else character(0),
    if (model_type %in% c("irt", "esem_bifactor_irt")) "mirt" else character(0),
    if (model_type %in% c("esem", "esem_bifactor_irt")) "psych" else character(0)
  ))
  missing_packages <- required_packages[!vapply(required_packages, requireNamespace, logical(1), quietly = TRUE)]
  if (length(missing_packages) > 0) stop(paste0("MEASUREMENT_PACKAGE_NOT_INSTALLED: ", paste(missing_packages, collapse = ",")))

  data <- read_analysis_data()
  item_ids <- unique(unlist(spec$itemIds, use.names = FALSE))
  missing_columns <- setdiff(item_ids, names(data))
  if (length(missing_columns) > 0) stop(paste0("MEASUREMENT_COLUMN_NOT_FOUND: ", paste(missing_columns, collapse = ",")))
  constructs <- lapply(spec$constructs, function(construct) {
    list(
      id = construct$id,
      label = construct$label,
      itemIds = as.list(intersect(unlist(construct$itemIds, use.names = FALSE), item_ids)),
      scoreId = if (is.null(construct$scoreId)) NULL else construct$scoreId
    )
  })
  item_frame <- data[, item_ids, drop = FALSE]
  for (item_id in item_ids) item_frame[[item_id]] <- suppressWarnings(as.numeric(item_frame[[item_id]]))
  item_complete_mask <- complete.cases(item_frame)
  item_frame <- item_frame[item_complete_mask, , drop = FALSE]
  if (nrow(item_frame) < 20) stop("MEASUREMENT_INSUFFICIENT_COMPLETE_OBSERVATIONS")

  reliability_result <- NULL
  efa_result <- NULL
  cfa_result <- NULL
  invariance_result <- NULL
  bifactor_result <- NULL
  esem_result <- NULL
  irt_result <- NULL
  cmb_result <- NULL
  if (identical(model_type, "reliability")) {
    reliability_result <- list(
      available = TRUE,
      constructs = lapply(constructs, function(construct) {
        ids <- intersect(unlist(construct$itemIds, use.names = FALSE), names(item_frame))
        metrics <- calc_ordinal_reliability(item_frame, ids)
        item_diag <- calc_item_diagnostics(item_frame, ids)
        c(list(constructId = construct$id, itemIds = as.list(ids), itemAnalysis = item_diag), metrics)
      }),
      structuralMissingness = calc_structural_missingness(data, constructs)
    )
  }
  if (identical(model_type, "efa")) {
    correlation <- if (identical(item_scale, "ordinal")) {
      tryCatch(lavaan::lavCor(item_frame, ordered = names(item_frame)), error = function(error) NULL)
    } else {
      stats::cor(item_frame, use = "pairwise.complete.obs")
    }
    if (is.null(correlation)) stop("MEASUREMENT_CORRELATION_ESTIMATION_FAILED")
    if (any(!is.finite(correlation))) stop("MEASUREMENT_CORRELATION_NOT_FINITE")
    map_result <- run_map_test(correlation)
    factor_count <- min(as.integer(spec$factorCount), ncol(item_frame) - 1L)
    efa_res <- tryCatch(
      run_efa_with_method(
        data = item_frame,
        correlation = correlation,
        n_obs = nrow(item_frame),
        factor_count = factor_count,
        method = extraction_method,
        rotation = rotation,
        item_scale = item_scale
      ),
      error = function(e) stop(paste0("MEASUREMENT_EFA_ESTIMATION_FAILED: ", conditionMessage(e)))
    )
    loading_matrix <- efa_res$loadings
    factor_correlations <- efa_res$factorCorrelations
    # Parallel analysis runs in the same correlation world as the main
    # EFA (polychoric for ordinal items, Pearson for continuous), so ordinal
    # data never silently falls back to a Pearson null distribution.
    parallel_analysis <- if (nrow(item_frame) >= 10 && ncol(item_frame) >= 3) {
      run_parallel_analysis(
        item_frame,
        as.integer(spec$parallelIterations),
        spec$seed,
        correlation_type = efa_res$correlationType
      )
    } else {
      NULL
    }
    efa_result <- list(
      available = TRUE,
      method = efa_res$extractionMethod,
      correlationType = efa_res$correlationType,
      requestedCorrelationType = efa_res$requestedCorrelationType,
      executedCorrelationType = efa_res$executedCorrelationType,
      requestedExtractionMethod = efa_res$requestedExtractionMethod,
      executedExtractionMethod = efa_res$executedExtractionMethod,
      requestedRotation = efa_res$requestedRotation,
      executedRotation = efa_res$executedRotation,
      requestedFactorCount = as.integer(spec$factorCount),
      factorCount = factor_count,
      rotation = rotation,
      map = map_result,
      parallelAnalysis = parallel_analysis,
      loadings = lapply(seq_len(nrow(loading_matrix)), function(index) list(itemId = rownames(loading_matrix)[[index]], loadings = as.list(as.numeric(loading_matrix[index, ])))),
      factorCorrelations = mat_to_list(factor_correlations),
      # Numerical fallbacks surface inside the result document
      # (diagnostics.numericalFallbacks), never only in a log line.
      diagnostics = list(
        items = efa_res$diagnostics,
        numericalFallbacks = efa_res$numericalFallbacks
      ),
      splitValidation = run_split_validation(
        item_frame, factor_count, rotation, spec$seed,
        method = extraction_method, item_scale = item_scale,
        primary_execution = efa_res
      )
    )
  }
  if (identical(model_type, "cfa")) {
    ordered_items <- if (identical(item_scale, "ordinal")) item_ids else NULL
    cfa_result <- fit_lavaan_cfa(item_frame, constructs, estimator = estimator, ordered_items = ordered_items)
    if (!isTRUE(cfa_result$available)) stop(paste0("MEASUREMENT_CFA_ESTIMATION_FAILED: ", cfa_result$reason))
    validity_bundle <- tryCatch(calc_cfa_validity_bundle(cfa_result, constructs, item_frame), error = function(e) list(available = FALSE, reason = conditionMessage(e)))
    cfa_result$validity <- validity_bundle
  }
  if (identical(model_type, "measurement_invariance")) {
    group_id <- spec$groupVariableId
    if (is.null(group_id) || !group_id %in% names(data)) stop("MEASUREMENT_INVARIANCE_GROUP_REQUIRED")
    invariance_data <- data[, unique(c(item_ids, group_id)), drop = FALSE]
    for (item_id in item_ids) invariance_data[[item_id]] <- suppressWarnings(as.numeric(invariance_data[[item_id]]))
    syntax <- paste(vapply(constructs, function(construct) paste0("F_", construct$id, " =~ ", paste(unlist(construct$itemIds, use.names = FALSE), collapse = " + ")), character(1)), collapse = "\n")
    group_partial <- if (is.null(spec$partialReleasedParameters)) NULL else unlist(spec$partialReleasedParameters, use.names = FALSE)
    invariance_result <- run_measurement_invariance(invariance_data, syntax, group_id, estimator = estimator, group_partial = group_partial)
    if (!isTRUE(invariance_result$available)) stop(paste0("MEASUREMENT_INVARIANCE_ESTIMATION_FAILED: ", invariance_result$reason))
    selected_levels <- unique(unlist(spec$invarianceLevels, use.names = FALSE))
    invariance_result$models <- invariance_result$models[names(invariance_result$models) %in% selected_levels]
    invariance_result$comparisons <- invariance_result$comparisons[names(invariance_result$comparisons) %in% selected_levels]
  }
  if (model_type %in% c("bifactor", "esem_bifactor_irt")) {
    bifactor_result <- tryCatch(
      fit_bifactor_model(
        item_frame,
        constructs,
        estimator = estimator,
        item_scale = item_scale
      ),
      error = function(error) list(available = FALSE, reason = conditionMessage(error))
    )
  }
  if (model_type %in% c("esem", "esem_bifactor_irt")) {
    esem_result <- tryCatch(
      fit_esem_model(
        item_frame,
        constructs,
        factor_count = as.integer(spec$factorCount),
        rotation = rotation,
        extraction_method = extraction_method,
        item_scale = item_scale
      ),
      error = function(error) list(available = FALSE, reason = conditionMessage(error))
    )
  }
  if (model_type %in% c("irt", "esem_bifactor_irt")) {
    group_values <- if (!is.null(spec$groupVariableId) && spec$groupVariableId %in% names(data)) {
      data[[spec$groupVariableId]][item_complete_mask]
    } else {
      NULL
    }
    requested_irt_model <- if (is.null(spec$irtModel)) "auto" else spec$irtModel
    irt_result <- tryCatch(
      fit_irt_dif_model(item_frame, constructs, group_values, requested_irt_model),
      error = function(error) list(available = FALSE, reason = conditionMessage(error))
    )
  }
  if (model_type %in% c("common_method_bias", "marker_variable", "ulmc")) {
    marker_result <- if (model_type %in% c("common_method_bias", "marker_variable")) {
      tryCatch(calc_marker_variable_cmb(data, spec$markerVariableId, constructs), error = function(error) list(available = FALSE, reason = conditionMessage(error)))
    } else NULL
    ulmc_result <- if (model_type %in% c("common_method_bias", "ulmc")) {
      tryCatch(fit_ulmc_cmb_model(item_frame, constructs), error = function(error) list(available = FALSE, reason = conditionMessage(error)))
    } else NULL
    cmb_result <- list(markerVariable = marker_result, ulmc = ulmc_result)
  }

  warnings <- list(message_entry("MEASUREMENT_COMPLETE_CASES", "info", "高级测量结果使用声明题项的完整案例；题项级缺失计数保留在样本流中。"))
  if (!is.null(reliability_result)) {
    for (construct_result in reliability_result$constructs) {
      if (identical(
        construct_result$reliabilityWarning,
        "TWO_ITEM_NONPOSITIVE_CORRELATION_REQUIRES_CODING_REVIEW"
      )) {
        warnings[[length(warnings) + 1L]] <- message_entry(
          "TWO_ITEM_NONPOSITIVE_CORRELATION",
          "warning",
          paste0(
            "构念 ", construct_result$constructId,
            " 的两个题项相关为非正；Spearman-Brown 按标准 2r/(1+r) 计算，",
            "正式解释前必须核对反向题、编码和单维性。"
          )
        )
      }
      if (!isTRUE(construct_result$ordinalReliabilityAvailable)) {
        warnings[[length(warnings) + 1L]] <- message_entry(
          "ORDINAL_RELIABILITY_UNAVAILABLE",
          "warning",
          paste0(
            "构念 ", construct_result$constructId,
            " 的 polychoric 信度不可用：", construct_result$ordinalReliabilityReason,
            "。未以 Pearson 结果冒充 ordinal α/ω。"
          )
        )
      }
    }
  }
  append_unavailable_warning <- function(result, code, recommendation) {
    if (!is.null(result) && !isTRUE(result$available)) {
      reason <- if (is.null(result$reason)) "未返回可用诊断" else result$reason
      warnings[[length(warnings) + 1L]] <<- message_entry(
        code,
        "warning",
        paste0(reason, "。", recommendation)
      )
    }
  }
  append_unavailable_warning(
    bifactor_result,
    "MEASUREMENT_BIFACTOR_UNAVAILABLE",
    "Bifactor \u6307\u6807\u4e0d\u53ef\u7528\u4e8e\u6b63\u5f0f\u7ed3\u8bba\uff1b\u8bf7\u68c0\u67e5\u9898\u9879\u6570\u3001\u6837\u672c\u91cf\u3001\u6a21\u578b\u8bc6\u522b\u4e0e\u6536\u655b\u8bca\u65ad\u3002"
  )
  append_unavailable_warning(
    esem_result,
    "MEASUREMENT_ESEM_UNAVAILABLE",
    "\u8bf7\u68c0\u67e5\u9898\u9879\u53d8\u5f02\u3001\u56e0\u5b50\u6570\u4e0e\u76f8\u5173\u77e9\u9635\u540e\u91cd\u8bd5\uff1b\u4e0d\u8981\u4ee5\u7f3a\u5931\u7684 ESEM \u8f93\u51fa\u66ff\u4ee3\u7ed3\u6784\u8bc1\u636e\u3002"
  )
  append_unavailable_warning(
    irt_result,
    "MEASUREMENT_IRT_UNAVAILABLE",
    "请核对题项类别编码、请求的 2PL/GRM 模型、样本量和 mirt 可用性。"
  )
  if (!is.null(efa_result)) {
    for (fallback in efa_result$diagnostics$numericalFallbacks) {
      warnings[[length(warnings) + 1L]] <- message_entry(
        "MEASUREMENT_EFA_NUMERICAL_FALLBACK",
        "warning",
        paste0(
          "EFA 阶段 ", fallback$stage, " 请求 ", fallback$requested,
          "，实际使用 ", fallback$used, "：", fallback$reason,
          "。该结果不得按原始方法的完全等价估计解释。"
        )
      )
    }
    if (identical(efa_result$parallelAnalysis$recommendedFactorCount, 0L)) {
      warnings[[length(warnings) + 1L]] <- message_entry(
        "MEASUREMENT_PARALLEL_ANALYSIS_ZERO_FACTORS",
        "warning",
        paste0(
          "平行分析未支持保留任何共同因子；当前 ", efa_result$factorCount,
          " 因子模型来自用户显式规格，不是平行分析建议。"
        )
      )
    }
    if (identical(efa_result$splitValidation$reason, "split_validation_execution_mismatch")) {
      warnings[[length(warnings) + 1L]] <- message_entry(
        "MEASUREMENT_SPLIT_VALIDATION_EXECUTION_MISMATCH",
        "warning",
        "完整样本、训练样本与留出样本的实际相关矩阵、提取法或旋转不一致；不报告跨样本稳定性系数。"
      )
    }
  }
  if (!is.null(cmb_result)) warnings[[length(warnings) + 1L]] <- message_entry("COMMON_METHOD_DIAGNOSTIC", "warning", "共同方法偏差检验是诊断证据，不自动等同于结论失效。")
  list(
    sampleFlow = list(original = nrow(data), included = nrow(item_frame), excluded = nrow(data) - nrow(item_frame), missingMethod = "complete_cases"),
    estimates = list(),
    diagnostics = list(message_entry("MEASUREMENT_RUN_COMPLETED", "info", sprintf("Completed questionnaire measurement slice %s", model_type))),
    warnings = warnings,
    provenance = list(
      engine = "ResearchPath R questionnaire measurement engine",
      engineVersion = "0.1.0",
      softwareVersions = as.list(c(jsonlite = as.character(packageVersion("jsonlite")), setNames(vapply(required_packages, function(package) as.character(packageVersion(package)), character(1)), required_packages))),
      estimand = "declared questionnaire measurement structure and item-level diagnostics",
      degreesOfFreedomMethod = "model-specific"
    ),
    familyResult = list(
      family = family,
      modelType = model_type,
      sampleSize = nrow(item_frame),
      itemCount = length(item_ids),
      constructCount = length(constructs),
      reliability = reliability_result,
      efa = efa_result,
      cfa = cfa_result,
      invariance = invariance_result,
      bifactor = bifactor_result,
      esem = esem_result,
      irt = irt_result,
      commonMethodBias = cmb_result
    )
  )
}
