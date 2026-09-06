# esem_bifactor.R
# ESEM, Bifactor Model, IRT & DIF Analysis

measurement_execution <- function(
  requested_method,
  executed_method,
  fallback_applied = FALSE,
  fallback_reason = NULL,
  interpretation_boundary = NULL
) {
  list(
    requestedMethod = requested_method,
    executedMethod = executed_method,
    fallbackApplied = isTRUE(fallback_applied),
    fallbackReason = fallback_reason,
    interpretationBoundary = interpretation_boundary
  )
}

bifactor_loading_missing_error <- function(general_loadings, specific_loadings, residual_variances) {
  items <- names(general_loadings)
  specific_matrix <- as.matrix(specific_loadings)
  missing <- items[!is.finite(as.numeric(general_loadings)) |
                     !is.finite(as.numeric(residual_variances)) |
                     !apply(specific_matrix, 1, function(row) any(is.finite(row)))]
  if (length(missing) == 0L) return(NULL)
  paste0("bifactor_loading_matrix_incomplete: ", paste(missing, collapse = ", "))
}

bifactor_total_score_metrics <- function(
  general_loadings,
  specific_loadings,
  residual_variances
) {
  general_loadings <- as.numeric(general_loadings)
  residual_variances <- as.numeric(residual_variances)
  specific_loadings <- as.matrix(specific_loadings)
  if (nrow(specific_loadings) != length(general_loadings) ||
      length(residual_variances) != length(general_loadings)) {
    stop("BIFACTOR_SCORE_VARIANCE_DIMENSION_MISMATCH")
  }

  general_contribution <- sum(general_loadings, na.rm = TRUE)^2
  specific_contributions <- colSums(specific_loadings, na.rm = TRUE)^2
  specific_contribution <- sum(specific_contributions, na.rm = TRUE)
  residual_contribution <- sum(residual_variances, na.rm = TRUE)
  total_score_variance <- general_contribution + specific_contribution + residual_contribution

  list(
    omegaHierarchical = if (total_score_variance > 0) {
      general_contribution / total_score_variance
    } else {
      NA_real_
    },
    totalScoreVariance = total_score_variance,
    generalFactorScoreVariance = general_contribution,
    specificFactorScoreVariance = specific_contribution,
    residualScoreVariance = residual_contribution,
    specificFactorContributions = specific_contributions,
    formula = "(sum(lambda_g))^2 / [(sum(lambda_g))^2 + sum_s(sum(lambda_s))^2 + sum(theta)]"
  )
}

fit_bifactor_model <- function(
  items,
  constructs,
  estimator = "ML",
  item_scale = "continuous"
) {
  if (nrow(items) < 20 || ncol(items) < 4) {
    return(list(available = FALSE, reason = "Bifactor 模型需要至少 20 个案例和 4 个题项"))
  }

  kept_constructs <- list()
  for (construct in constructs) {
    ids <- intersect(unlist(construct$itemIds), names(items))
    if (length(ids) >= 2) {
      kept_constructs[[length(kept_constructs) + 1]] <- list(
        id = construct$id,
        label = construct$label,
        itemIds = ids
      )
    }
  }
  if (length(kept_constructs) < 2) {
    return(list(available = FALSE, reason = "Bifactor 模型需要至少 2 个包含至少 2 个题项的构念"))
  }

  all_item_ids <- unique(unlist(lapply(kept_constructs, function(construct) construct$itemIds)))
  g_syntax <- paste0("G_factor =~ ", paste(all_item_ids, collapse = " + "))
  s_syntax_list <- vapply(kept_constructs, function(construct) {
    paste0("S_", construct$id, " =~ ", paste(construct$itemIds, collapse = " + "))
  }, character(1))
  factor_names <- c(
    "G_factor",
    paste0("S_", vapply(kept_constructs, function(construct) construct$id, character(1)))
  )
  ortho_list <- character(0)
  if (length(factor_names) >= 2L) {
    for (i in seq_len(length(factor_names) - 1L)) {
      for (j in seq.int(i + 1L, length(factor_names))) {
        ortho_list <- c(ortho_list, paste0(factor_names[i], " ~~ 0*", factor_names[j]))
      }
    }
  }
  model_syntax <- paste(c(g_syntax, s_syntax_list, ortho_list), collapse = "\n")

  requested_estimator <- estimator
  executed_estimator <- if (identical(item_scale, "ordinal")) "WLSMV" else estimator
  ordered_items <- if (identical(item_scale, "ordinal")) all_item_ids else NULL
  fit_error <- NULL
  fit <- tryCatch(
    lavaan::cfa(
      model_syntax,
      data = items,
      estimator = executed_estimator,
      ordered = ordered_items,
      bounds = "pos.var"
    ),
    error = function(error) {
      fit_error <<- conditionMessage(error)
      NULL
    }
  )

  if (is.null(fit) || !isTRUE(lavaan::lavInspect(fit, "converged"))) {
    return(list(
      available = FALSE,
      reason = if (is.null(fit_error)) {
        "lavaan Bifactor 模型估计未收敛，建议检查负荷约束或数据变异性"
      } else {
        paste0("lavaan Bifactor 估计失败: ", fit_error)
      },
      methodExecution = measurement_execution(
        paste0(requested_estimator, " bifactor for ", item_scale, " items"),
        paste0(executed_estimator, " lavaan bifactor"),
        interpretation_boundary = "未收敛或估计失败时不报告 Bifactor 结构指标。"
      )
    ))
  }

  measures <- tryCatch(lavaan::fitMeasures(fit), error = function(error) NULL)
  std_sol <- tryCatch(lavaan::standardizedSolution(fit), error = function(error) NULL)
  if (is.null(measures) || is.null(std_sol)) {
    return(list(available = FALSE, reason = "无法提取 Bifactor 模型标准解与拟合指标"))
  }

  get_measure <- function(primary, fallback = NULL) {
    if (!is.null(measures[primary]) && is.finite(measures[primary])) {
      return(as.numeric(measures[primary]))
    }
    if (!is.null(fallback) && !is.null(measures[fallback]) && is.finite(measures[fallback])) {
      return(as.numeric(measures[fallback]))
    }
    NA_real_
  }
  robust <- executed_estimator %in% c("MLR", "WLSMV")
  loadings_df <- std_sol[which(std_sol$op == "=~"), ]
  g_loadings_df <- loadings_df[which(loadings_df$lhs == "G_factor"), ]
  g_loadings <- setNames(rep(NA_real_, length(all_item_ids)), all_item_ids)
  specific_factor_names <- factor_names[factor_names != "G_factor"]
  specific_loadings <- matrix(
    NA_real_,
    nrow = length(all_item_ids),
    ncol = length(specific_factor_names),
    dimnames = list(all_item_ids, specific_factor_names)
  )
  for (id in all_item_ids) {
    general_row <- g_loadings_df[which(g_loadings_df$rhs == id), ]
    if (nrow(general_row) > 0) g_loadings[id] <- general_row$est.std[[1]]
    for (specific_factor in specific_factor_names) {
      specific_row <- loadings_df[
        which(loadings_df$lhs == specific_factor & loadings_df$rhs == id),
      ]
      if (nrow(specific_row) > 0) {
        specific_loadings[id, specific_factor] <- specific_row$est.std[[1]]
      }
    }
  }

  residual_rows <- std_sol[
    which(std_sol$op == "~~" & std_sol$lhs == std_sol$rhs & std_sol$lhs %in% all_item_ids),
  ]
  residuals <- setNames(rep(NA_real_, length(all_item_ids)), all_item_ids)
  for (id in all_item_ids) {
    row <- residual_rows[which(residual_rows$lhs == id), ]
    if (nrow(row) > 0) residuals[id] <- row$est.std[[1]]
  }

  missing_error <- bifactor_loading_missing_error(g_loadings, specific_loadings, residuals)
  if (!is.null(missing_error)) {
    return(list(
      available = FALSE,
      reason = missing_error,
      methodExecution = measurement_execution(
        paste0(requested_estimator, " bifactor for ", item_scale, " items"),
        paste0(executed_estimator, " lavaan bifactor"),
        interpretation_boundary = "载荷、残差或特定因子载荷缺失时不得以 0 补齐并计算 ωh/ECV/PUC。"
      )
    ))
  }

  g_sq <- sum(g_loadings^2)
  s_sq <- sum(specific_loadings^2)
  ecv <- if (g_sq + s_sq > 0) g_sq / (g_sq + s_sq) else NA_real_
  score_metrics <- bifactor_total_score_metrics(
    g_loadings,
    specific_loadings,
    residuals
  )
  item_count <- length(all_item_ids)
  total_pairs <- item_count * (item_count - 1) / 2
  within_pairs <- sum(vapply(kept_constructs, function(construct) {
    length(construct$itemIds) * (length(construct$itemIds) - 1) / 2
  }, numeric(1)))
  puc <- if (total_pairs > 0) (total_pairs - within_pairs) / total_pairs else NA_real_

  list(
    available = TRUE,
    estimator = executed_estimator,
    itemScale = item_scale,
    methodExecution = measurement_execution(
      paste0(requested_estimator, " bifactor for ", item_scale, " items"),
      paste0(executed_estimator, " lavaan bifactor"),
      interpretation_boundary = "ωh、ECV 与 PUC 必须结合模型收敛、拟合和构念理论解释。"
    ),
    fitIndices = list(
      chisq = finite_number(get_measure(if (robust) "chisq.scaled" else "chisq", "chisq")),
      df = finite_number(get_measure(if (robust) "df.scaled" else "df", "df")),
      pValue = finite_number(get_measure(if (robust) "pvalue.scaled" else "pvalue", "pvalue")),
      cfi = finite_number(get_measure(if (robust) "cfi.robust" else "cfi", "cfi")),
      tli = finite_number(get_measure(if (robust) "tli.robust" else "tli", "tli")),
      rmsea = finite_number(get_measure(if (robust) "rmsea.robust" else "rmsea", "rmsea")),
      srmr = finite_number(get_measure("srmr")),
      basis = if (robust) "robust_or_scaled_when_available" else "standard"
    ),
    bifactorMetrics = list(
      ecv = finite_number(ecv),
      omegaHierarchical = finite_number(score_metrics$omegaHierarchical),
      puc = finite_number(puc),
      totalScoreVariance = finite_number(score_metrics$totalScoreVariance),
      generalFactorScoreVariance = finite_number(score_metrics$generalFactorScoreVariance),
      specificFactorScoreVariance = finite_number(score_metrics$specificFactorScoreVariance),
      residualScoreVariance = finite_number(score_metrics$residualScoreVariance),
      specificFactorContributions = lapply(
        score_metrics$specificFactorContributions,
        finite_number
      ),
      omegaHierarchicalFormula = score_metrics$formula,
      scoreVarianceAssumption = "orthogonal bifactor with standardized loadings and item residual variances"
    ),
    itemDetails = lapply(all_item_ids, function(id) list(
      itemId = id,
      generalLoading = finite_number(g_loadings[id]),
      specificLoading = finite_number(sum(specific_loadings[id, ], na.rm = TRUE)),
      specificLoadings = lapply(specific_loadings[id, ], finite_number),
      uniqueness = finite_number(residuals[id])
    ))
  )
}

build_esem_target <- function(all_items, constructs, factor_count) {
  if (factor_count != length(constructs)) {
    stop("ESEM_TARGET_FACTOR_COUNT_MUST_MATCH_CONSTRUCT_COUNT")
  }
  target <- matrix(
    0,
    nrow = length(all_items),
    ncol = factor_count,
    dimnames = list(all_items, vapply(constructs, function(construct) construct$id, character(1)))
  )
  for (factor_index in seq_along(constructs)) {
    ids <- intersect(unlist(constructs[[factor_index]]$itemIds), all_items)
    target[ids, factor_index] <- 1
  }
  if (any(rowSums(target) != 1L)) {
    stop("ESEM_TARGET_REQUIRES_EXACTLY_ONE_DECLARED_PRIMARY_FACTOR_PER_ITEM")
  }
  target
}

fit_esem_model <- function(
  items,
  constructs,
  factor_count = NULL,
  rotation = "target",
  extraction_method = "ml",
  item_scale = "continuous"
) {
  if (nrow(items) < 20 || ncol(items) < 4) {
    return(list(available = FALSE, reason = "ESEM 需要至少 20 个案例和 4 个题项"))
  }
  if (!identical(item_scale, "continuous")) {
    return(list(
      available = FALSE,
      reason = "ORDINAL_ESEM_WLSMV_NOT_IMPLEMENTED",
      methodExecution = measurement_execution(
        "ordinal WLSMV ESEM target rotation",
        "not_executed",
        interpretation_boundary = "有序题项 ESEM 不得静默按 Pearson/连续变量模型执行。"
      )
    ))
  }
  if (!identical(rotation, "target")) {
    return(list(available = FALSE, reason = "ESEM_REQUIRES_TARGET_ROTATION"))
  }

  all_items <- unique(intersect(
    unlist(lapply(constructs, function(construct) unlist(construct$itemIds))),
    names(items)
  ))
  if (length(all_items) < 4) {
    return(list(available = FALSE, reason = "ESEM 需要至少 4 个题项"))
  }
  requested_factors <- if (is.null(factor_count)) length(constructs) else as.integer(factor_count)
  target <- tryCatch(
    build_esem_target(all_items, constructs, requested_factors),
    error = function(error) error
  )
  if (inherits(target, "error")) {
    return(list(available = FALSE, reason = conditionMessage(target)))
  }
  psych_method <- switch(extraction_method, paf = "pa", minres = "minres", "ml")
  captured_warnings <- character(0)
  fit_psych <- tryCatch(
    withCallingHandlers(
      psych::fa(
        items[, all_items, drop = FALSE],
        nfactors = requested_factors,
        rotate = "targetQ",
        Target = target,
        fm = psych_method,
        n.rotations = 1L
      ),
      warning = function(warning) {
        captured_warnings <<- c(captured_warnings, conditionMessage(warning))
        invokeRestart("muffleWarning")
      }
    ),
    error = function(error) NULL
  )
  rotation_failed <- any(grepl(
    "transformat.*failed|Promax was used instead|Target.*must be specified",
    captured_warnings,
    ignore.case = TRUE
  ))
  if (is.null(fit_psych) || is.null(fit_psych$loadings) || rotation_failed) {
    return(list(
      available = FALSE,
      reason = paste(
        c("ESEM_TARGET_ROTATION_FAILED", captured_warnings),
        collapse = ": "
      ),
      methodExecution = measurement_execution(
        paste0(extraction_method, " ESEM targetQ"),
        "not_executed",
        interpretation_boundary = "目标旋转失败时不以 Promax 结果冒充目标旋转。"
      )
    ))
  }

  loadings_mat <- unclass(fit_psych$loadings)
  factor_cors <- if (!is.null(fit_psych$Phi)) unclass(fit_psych$Phi) else diag(requested_factors)
  list(
    available = TRUE,
    factorCount = requested_factors,
    method = "ESEM_targetQ_declared_construct_target",
    correlationType = "pearson",
    requestedRotation = "target",
    executedRotation = "targetQ",
    extractionMethod = extraction_method,
    targetSource = "declared_construct_membership",
    targetMatrix = mat_to_list(target),
    methodExecution = measurement_execution(
      paste0(extraction_method, " ESEM target rotation"),
      paste0(psych_method, " ESEM targetQ with declared target matrix"),
      interpretation_boundary = "ESEM 交叉载荷为探索性结构证据，不替代理论与独立样本验证。"
    ),
    warnings = as.list(captured_warnings),
    loadings = lapply(seq_len(nrow(loadings_mat)), function(index) {
      primary_index <- which.max(abs(loadings_mat[index, ]))
      cross_values <- if (ncol(loadings_mat) > 1L) {
        abs(loadings_mat[index, -primary_index])
      } else {
        numeric(0)
      }
      list(
        itemId = rownames(loadings_mat)[index],
        loadings = as.list(as.numeric(loadings_mat[index, ])),
        crossLoadingMax = finite_number(if (length(cross_values)) max(cross_values) else 0),
        primaryLoading = finite_number(max(abs(loadings_mat[index, ])))
      )
    }),
    factorCorrelations = mat_to_list(factor_cors)
  )
}

prepare_irt_items <- function(sub_df, requested_model = "auto") {
  category_values <- lapply(sub_df, function(column) sort(unique(column)))
  valid_categories <- vapply(category_values, function(values) {
    length(values) >= 2L && all(is.finite(values)) && all(abs(values - round(values)) <= 1e-8)
  }, logical(1))
  if (!all(valid_categories)) stop("IRT_ITEMS_REQUIRE_AT_LEAST_TWO_ORDERED_INTEGER_CATEGORIES")

  recoded <- as.data.frame(lapply(seq_along(sub_df), function(index) {
    match(sub_df[[index]], category_values[[index]]) - 1L
  }))
  names(recoded) <- names(sub_df)
  item_types <- vapply(category_values, function(values) {
    if (length(values) == 2L) "2PL" else "graded"
  }, character(1))
  if (identical(requested_model, "2PL") && any(item_types != "2PL")) {
    stop("IRT_2PL_REQUIRES_BINARY_ITEMS")
  }
  if (identical(requested_model, "GRM") && any(item_types != "graded")) {
    stop("IRT_GRM_REQUIRES_AT_LEAST_THREE_CATEGORIES_PER_ITEM")
  }
  if (identical(requested_model, "2PL")) item_types[] <- "2PL"
  if (identical(requested_model, "GRM")) item_types[] <- "graded"
  list(data = recoded, categoryValues = category_values, itemTypes = item_types)
}

fit_item_dif <- function(response, theta, groups, item_type) {
  if (identical(item_type, "2PL")) {
    reduced <- tryCatch(
      stats::glm(response ~ theta, family = stats::binomial()),
      error = function(error) NULL
    )
    full <- tryCatch(
      stats::glm(response ~ theta * groups, family = stats::binomial()),
      error = function(error) NULL
    )
  } else {
    ordered_response <- ordered(response)
    reduced <- tryCatch(
      MASS::polr(ordered_response ~ theta, method = "logistic", Hess = TRUE),
      error = function(error) NULL
    )
    full <- tryCatch(
      MASS::polr(ordered_response ~ theta * groups, method = "logistic", Hess = TRUE),
      error = function(error) NULL
    )
  }
  if (is.null(reduced) || is.null(full)) {
    return(list(statistic = NA_real_, degreesOfFreedom = NA_real_, pValue = NA_real_))
  }
  reduced_loglik <- stats::logLik(reduced)
  full_loglik <- stats::logLik(full)
  statistic <- 2 * (as.numeric(full_loglik) - as.numeric(reduced_loglik))
  degrees_freedom <- attr(full_loglik, "df") - attr(reduced_loglik, "df")
  p_value <- if (is.finite(statistic) && degrees_freedom > 0) {
    stats::pchisq(max(0, statistic), df = degrees_freedom, lower.tail = FALSE)
  } else {
    NA_real_
  }
  list(
    statistic = finite_number(statistic),
    degreesOfFreedom = finite_number(degrees_freedom),
    pValue = finite_number(p_value)
  )
}

fit_irt_dif_model <- function(
  items,
  constructs,
  group_variable = NULL,
  requested_model = "auto"
) {
  if (nrow(items) < 30 || ncol(items) < 3) {
    return(list(available = FALSE, reason = "IRT 需要至少 30 个案例和 3 个题项"))
  }
  if (!requireNamespace("mirt", quietly = TRUE)) {
    return(list(available = FALSE, reason = "mirt package is required for IRT estimation"))
  }

  all_items <- unique(intersect(
    unlist(lapply(constructs, function(construct) unlist(construct$itemIds))),
    names(items)
  ))
  sub_df <- items[, all_items, drop = FALSE]
  prepared <- tryCatch(
    prepare_irt_items(sub_df, requested_model),
    error = function(error) error
  )
  if (inherits(prepared, "error")) {
    return(list(available = FALSE, reason = conditionMessage(prepared)))
  }

  fit <- tryCatch(
    mirt::mirt(
      prepared$data,
      1L,
      itemtype = unname(prepared$itemTypes),
      verbose = FALSE,
      technical = list(NCYCLES = 1000L)
    ),
    error = function(error) NULL
  )
  if (is.null(fit)) return(list(available = FALSE, reason = "mirt IRT estimation failed"))
  converged <- isTRUE(fit@OptimInfo$converged)
  if (!converged) return(list(available = FALSE, reason = "mirt IRT estimation did not converge"))

  coefficient_matrix <- tryCatch(
    mirt::coef(fit, IRTpars = TRUE, simplify = TRUE)$items,
    error = function(error) NULL
  )
  if (is.null(coefficient_matrix)) {
    return(list(available = FALSE, reason = "Unable to extract IRT item parameters"))
  }
  item_parameters <- lapply(all_items, function(id) {
    difficulty_columns <- grep("^b[0-9]*$", colnames(coefficient_matrix), value = TRUE)
    difficulty_values <- coefficient_matrix[id, difficulty_columns, drop = TRUE]
    difficulty_values <- difficulty_values[is.finite(difficulty_values)]
    list(
      itemId = id,
      itemType = prepared$itemTypes[[id]],
      categoryValues = as.list(as.numeric(prepared$categoryValues[[id]])),
      discrimination = finite_number(coefficient_matrix[id, "a"]),
      discrimination_a = finite_number(coefficient_matrix[id, "a"]),
      difficulties = as.list(as.numeric(difficulty_values)),
      difficulties_b = as.list(as.numeric(difficulty_values))
    )
  })

  dif_results <- list()
  dif_status <- "not_requested"
  dif_method <- NULL
  dif_sample_size <- 0L
  dif_adjustment_method <- "none"
  if (!is.null(group_variable)) {
    if (length(group_variable) != nrow(prepared$data)) {
      return(list(available = FALSE, reason = "DIF_GROUP_ROW_ALIGNMENT_ERROR"))
    }
    dif_mask <- !is.na(group_variable)
    groups <- droplevels(as.factor(group_variable[dif_mask]))
    dif_sample_size <- sum(dif_mask)
    if (nlevels(groups) == 2L && dif_sample_size >= 30L) {
      dif_status <- "available"
      dif_method <- "likelihood_ratio_logistic_with_group_and_theta_interaction"
      theta <- as.numeric(mirt::fscores(fit, method = "EAP")[, 1])[dif_mask]
      dif_results <- lapply(all_items, function(id) {
        result <- fit_item_dif(
          prepared$data[[id]][dif_mask],
          theta,
          groups,
          prepared$itemTypes[[id]]
        )
        c(list(itemId = id, itemType = prepared$itemTypes[[id]]), result)
      })
      raw_p_values <- vapply(dif_results, function(entry) entry$pValue, numeric(1))
      finite_indices <- which(is.finite(raw_p_values))
      adjusted_p_values <- rep(NA_real_, length(raw_p_values))
      if (length(finite_indices)) {
        adjusted_p_values[finite_indices] <- stats::p.adjust(
          raw_p_values[finite_indices],
          method = "holm"
        )
        dif_adjustment_method <- "holm"
      }
      for (index in seq_along(dif_results)) {
        dif_results[[index]]$pValueRaw <- dif_results[[index]]$pValue
        dif_results[[index]]$pValueAdjusted <- finite_number(adjusted_p_values[[index]])
        dif_results[[index]]$difDetected <- isTRUE(adjusted_p_values[[index]] < 0.05)
      }
    } else {
      dif_status <- if (nlevels(groups) != 2L) "requires_exactly_two_groups" else "insufficient_group_complete_cases"
    }
  }

  unique_item_types <- unique(unname(prepared$itemTypes))
  executed_model <- if (length(unique_item_types) == 1L) {
    if (identical(unique_item_types, "2PL")) "2PL" else "GRM"
  } else {
    "mixed_2PL_GRM"
  }
  estimator <- paste0("mirt_MML_", executed_model)
  list(
    available = TRUE,
    estimator = estimator,
    requestedIrtModel = requested_model,
    executedIrtModel = executed_model,
    methodExecution = measurement_execution(
      paste0("mirt ", requested_model, " IRT"),
      paste0(estimator, " with item-specific category coding"),
      interpretation_boundary = "IRT/DIF 参数依赖单维性、局部独立、类别使用和分组可比性；DIF 为 Holm 校正的诊断筛查。"
    ),
    converged = converged,
    sampleSize = nrow(prepared$data),
    itemTypes = as.list(prepared$itemTypes),
    itemParameters = item_parameters,
    difStatus = dif_status,
    difMethod = dif_method,
    difSampleSize = as.integer(dif_sample_size),
    difAnalysis = dif_results,
    difAdjustmentMethod = dif_adjustment_method
  )
}
