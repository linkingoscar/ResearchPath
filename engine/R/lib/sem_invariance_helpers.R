# SEM 多组等值性辅助函数库 (sem_invariance_helpers.R)
#
# SEM 等值性辅助函数，保持与主分析入口一致的结果契约。
# 原为闭包实现，现改为显式参数；调用方在 sem_analysis.R 等值性分支内。

# 收敛失败/空拟合时返回与 get_fit_indices 结构一致的 NA 骨架，
# 保证等值性对比表字段齐全。
sem_inv_fit_indices_safe <- function(fit) {
  if (is.null(fit) || !lavInspect(fit, "converged")) {
    return(list(
      chiSquare = NA_real_,
      df = NA_integer_,
      pValue = NA_real_,
      cfi = NA_real_,
      tli = NA_real_,
      rmsea = NA_real_,
      srmr = NA_real_,
      rmseaCiLower = NA_real_,
      rmseaCiUpper = NA_real_,
      robustChiSquare = NULL,
      robustDf = NULL,
      robustPValue = NULL,
      robustCfi = NULL,
      robustTli = NULL,
      robustRmsea = NULL,
      robustRmseaCiLower = NULL,
      robustRmseaCiUpper = NULL
    ))
  }
  get_fit_indices(fit)
}

# 从 configural 拟合提取各组载荷与结构路径（含 level-driven CI）。
sem_inv_extract_group_parameters <- function(
  group_fit,
  higher_order_ids,
  confidence_level
) {
  if (is.null(group_fit) || !isTRUE(lavInspect(group_fit, "converged"))) return(list())
  estimates <- parameterEstimates(group_fit)
  standardized <- standardizedSolution(group_fit)
  merged <- merge(
    estimates,
    standardized,
    by = c("lhs", "op", "rhs", "group"),
    suffixes = c("", ".std")
  )
  labels <- lavInspect(group_fit, "group.label")
  critical <- qnorm(1 - (1 - confidence_level) / 2)
  nullable_number <- function(value) {
    if (length(value) == 1 && is.finite(value)) as.numeric(value) else NA_real_
  }
  lapply(seq_along(labels), function(group_index) {
    rows <- merged[merged$group == group_index & merged$op %in% c("=~", "~"), , drop = FALSE]
    list(
      group = as.character(labels[[group_index]]),
      loadings = lapply(which(rows$op == "=~"), function(i) list(
        latentId = rows$lhs[i],
        indicatorId = rows$rhs[i],
        level = if (rows$lhs[i] %in% higher_order_ids) "higher_order" else "first_order",
        estimate = as.numeric(rows$est[i]),
        standardError = nullable_number(rows$se[i]),
        pValue = nullable_number(rows$pvalue[i]),
        stdAll = as.numeric(rows$est.std[i]),
        ciLower = if (length(rows$se[i]) == 1 && is.finite(rows$se[i])) as.numeric(rows$est[i] - critical * rows$se[i]) else NA_real_,
        ciUpper = if (length(rows$se[i]) == 1 && is.finite(rows$se[i])) as.numeric(rows$est[i] + critical * rows$se[i]) else NA_real_
      )),
      paths = lapply(which(rows$op == "~"), function(i) list(
        from = rows$rhs[i],
        to = rows$lhs[i],
        estimate = as.numeric(rows$est[i]),
        standardError = nullable_number(rows$se[i]),
        pValue = nullable_number(rows$pvalue[i]),
        stdAll = as.numeric(rows$est.std[i]),
        ciLower = if (length(rows$se[i]) == 1 && is.finite(rows$se[i])) as.numeric(rows$est[i] - critical * rows$se[i]) else NA_real_,
        ciUpper = if (length(rows$se[i]) == 1 && is.finite(rows$se[i])) as.numeric(rows$est[i] + critical * rows$se[i]) else NA_real_
      ))
    )
  })
}

# 组间路径两两 Wald 差检验。configural 无跨组约束，跨组参数渐近独立，
# 差值标准误用 sqrt(seA^2+seB^2)，方法名如实标注独立组假设。
sem_inv_extract_path_comparisons <- function(group_parameters, confidence_level) {
  path_keys <- unique(unlist(lapply(group_parameters, function(group) {
    vapply(group$paths, function(path) paste(path$from, path$to, sep = "\r"), character(1))
  })))
  critical <- qnorm(1 - (1 - confidence_level) / 2)
  comparisons <- list()
  for (path_key in path_keys) {
    parts <- strsplit(path_key, "\r", fixed = TRUE)[[1]]
    rows <- lapply(group_parameters, function(group) {
      match <- Filter(
        function(path) identical(path$from, parts[[1]]) && identical(path$to, parts[[2]]),
        group$paths
      )
      if (length(match) == 0) NULL else list(group = group$group, path = match[[1]])
    })
    rows <- Filter(Negate(is.null), rows)
    if (length(rows) < 2) next
    for (left_index in seq_len(length(rows) - 1L)) {
      for (right_index in seq.int(left_index + 1L, length(rows))) {
        left <- rows[[left_index]]
        right <- rows[[right_index]]
        left_se <- left$path$standardError
        right_se <- right$path$standardError
        if (!is.finite(left_se) || !is.finite(right_se)) next
        difference <- left$path$estimate - right$path$estimate
        difference_se <- sqrt(left_se^2 + right_se^2)
        statistic <- if (difference_se > 0) difference / difference_se else NA_real_
        comparisons[[length(comparisons) + 1]] <- list(
          from = parts[[1]],
          to = parts[[2]],
          groupA = left$group,
          groupB = right$group,
          estimateA = left$path$estimate,
          estimateB = right$path$estimate,
          difference = difference,
          standardError = difference_se,
          statistic = statistic,
          pValue = if (is.finite(statistic)) 2 * pnorm(abs(statistic), lower.tail = FALSE) else NA_real_,
          ciLower = difference - critical * difference_se,
          ciUpper = difference + critical * difference_se,
          method = "Wald difference for independent groups"
        )
      }
    }
  }
  comparisons
}

# 组别预测线图：单一预测变量方程，10-90 分位网格上的均值线 CI。
sem_inv_build_prediction_plots <- function(
  group_fit,
  nodes,
  group_var_col,
  analysis_data,
  confidence_level
) {
  if (is.null(group_fit) || !isTRUE(lavInspect(group_fit, "converged"))) return(list())
  observed_continuous <- unique(vapply(
    Filter(function(node) {
      !identical(node$kind, "latent") && identical(node$dataType, "continuous")
    }, nodes),
    function(node) if (is.null(node$variableId)) node$id else node$variableId,
    character(1)
  ))
  parameter_table <- parameterTable(group_fit)
  covariance <- tryCatch(vcov(group_fit), error = function(e) NULL)
  if (is.null(covariance)) return(list())
  labels <- lavInspect(group_fit, "group.label")
  path_rows <- parameter_table[
    parameter_table$op == "~" &
      parameter_table$lhs %in% observed_continuous &
      parameter_table$rhs %in% observed_continuous,
    ,
    drop = FALSE
  ]
  plots <- list()
  path_pairs <- unique(path_rows[, c("lhs", "rhs"), drop = FALSE])
  for (pair_index in seq_len(nrow(path_pairs))) {
    outcome <- path_pairs$lhs[pair_index]
    predictor <- path_pairs$rhs[pair_index]
    equation_predictors <- unique(parameter_table$rhs[
      parameter_table$op == "~" & parameter_table$lhs == outcome
    ])
    if (length(equation_predictors) != 1L) next
    group_lines <- list()
    for (group_index in seq_along(labels)) {
      slope_row <- parameter_table[
        parameter_table$op == "~" &
          parameter_table$lhs == outcome &
          parameter_table$rhs == predictor &
          parameter_table$group == group_index,
        ,
        drop = FALSE
      ]
      intercept_row <- parameter_table[
        parameter_table$op == "~1" &
          parameter_table$lhs == outcome &
          parameter_table$group == group_index,
        ,
        drop = FALSE
      ]
      if (nrow(slope_row) != 1L || nrow(intercept_row) != 1L) next
      slope_free <- as.integer(slope_row$free[[1]])
      intercept_free <- as.integer(intercept_row$free[[1]])
      if (slope_free < 1L || intercept_free < 1L) next
      group_data <- analysis_data[analysis_data[[group_var_col]] == labels[[group_index]], , drop = FALSE]
      predictor_values <- as.numeric(group_data[[predictor]])
      predictor_values <- predictor_values[is.finite(predictor_values)]
      if (length(unique(predictor_values)) < 3L) next
      limits <- quantile(predictor_values, c(0.1, 0.9), names = FALSE)
      x_values <- seq(limits[[1]], limits[[2]], length.out = 25L)
      estimates <- parameterEstimates(group_fit)
      slope <- estimates$est[
        estimates$op == "~" & estimates$lhs == outcome &
          estimates$rhs == predictor & estimates$group == group_index
      ][[1]]
      intercept <- estimates$est[
        estimates$op == "~1" & estimates$lhs == outcome &
          estimates$group == group_index
      ][[1]]
      variance_slope <- covariance[slope_free, slope_free]
      variance_intercept <- covariance[intercept_free, intercept_free]
      covariance_term <- covariance[intercept_free, slope_free]
      prediction <- intercept + slope * x_values
      prediction_se <- sqrt(pmax(
        variance_intercept + x_values^2 * variance_slope + 2 * x_values * covariance_term,
        0
      ))
      critical <- qnorm(1 - (1 - confidence_level) / 2)
      group_lines[[length(group_lines) + 1]] <- list(
        group = as.character(labels[[group_index]]),
        xValues = as.list(x_values),
        predictedValues = as.list(prediction),
        ciLower = as.list(prediction - critical * prediction_se),
        ciUpper = as.list(prediction + critical * prediction_se)
      )
    }
    if (length(group_lines) >= 2L) {
      plots[[length(plots) + 1]] <- list(
        from = predictor,
        to = outcome,
        predictorLabel = predictor,
        outcomeLabel = outcome,
        confidenceLevel = confidence_level,
        groups = group_lines,
        method = "Model-implied observed-scale line; single-predictor equation; group 10th-90th percentile range"
      )
    }
  }
  plots
}

# 标量等值阶段的潜均值估计（参照组 = 第一组）。
sem_inv_extract_latent_means <- function(
  scalar_fit,
  estimate_latent_means_enabled,
  latents
) {
  if (
    !isTRUE(estimate_latent_means_enabled) ||
    is.null(scalar_fit) ||
    !isTRUE(lavInspect(scalar_fit, "converged"))
  ) return(list())
  estimates <- parameterEstimates(scalar_fit, ci = TRUE)
  labels <- lavInspect(scalar_fit, "group.label")
  latent_ids <- vapply(latents, function(latent) latent$id, character(1))
  rows <- estimates[estimates$op == "~1" & estimates$lhs %in% latent_ids, , drop = FALSE]
  nullable_number <- function(value) {
    if (length(value) == 1 && is.finite(value)) as.numeric(value) else NA_real_
  }
  lapply(seq_len(nrow(rows)), function(i) list(
    group = as.character(labels[[rows$group[i]]]),
    latentId = rows$lhs[i],
    estimate = as.numeric(rows$est[i]),
    standardError = nullable_number(rows$se[i]),
    pValue = nullable_number(rows$pvalue[i]),
    ciLower = nullable_number(rows$ci.lower[i]),
    ciUpper = nullable_number(rows$ci.upper[i]),
    referenceGroup = identical(as.integer(rows$group[i]), 1L)
  ))
}

# 嵌套模型 LRT；任一拟合缺失或不收敛时返回 NA 骨架而不是报错。
sem_inv_test_lrt <- function(m_nested, m_parent) {
  if (is.null(m_nested) || is.null(m_parent) ||
      !lavInspect(m_nested, "converged") || !lavInspect(m_parent, "converged")) {
    return(list(
      chisq_diff = NA_real_,
      df_diff = NA_integer_,
      p_val = NA_real_
    ))
  }
  tryCatch({
    lrt <- lavTestLRT(m_nested, m_parent)
    pval <- lrt$`Pr(>Chisq)`[2]
    chisq_diff <- lrt$`Chisq diff`[2]
    df_diff <- lrt$`Df diff`[2]
    list(
      chisq_diff = chisq_diff,
      df_diff = df_diff,
      p_val = pval
    )
  }, error = function(e) {
    list(
      chisq_diff = NA_real_,
      df_diff = NA_integer_,
      p_val = NA_real_
    )
  })
}
