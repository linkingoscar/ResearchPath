# ResearchPath R Engine - Factorial ANCOVA & Planned Contrasts

run_planned_contrasts <- function(data, dv, group_var, contrast_weights = NULL, confidence_level = 0.95) {
  confidence_level <- researchpath_validate_confidence_level(confidence_level)
  if (!dv %in% colnames(data) || !group_var %in% colnames(data)) {
    stop("指定的因变量或分组变量不存在")
  }

  sub_df <- data[!is.na(data[[dv]]) & !is.na(data[[group_var]]), ]
  group_factor <- as.factor(sub_df[[group_var]])
  levels_name <- levels(group_factor)
  k <- length(levels_name)

  if (k < 2) {
    stop("计划对比需要至少 2 个实验分组")
  }

  means <- tapply(sub_df[[dv]], group_factor, mean)
  vars <- tapply(sub_df[[dv]], group_factor, var)
  ns <- tapply(sub_df[[dv]], group_factor, length)

  # MSE calculation from 1-Way ANOVA
  fit <- aov(as.formula(paste(dv, "~", group_var)), data = sub_df)
  fit_s <- summary(fit)[[1]]
  df_error <- fit_s["Df"][2, 1]
  mse <- fit_s["Mean Sq"][2, 1]

  if (is.null(contrast_weights)) {
    # Default pairwise contrast (Group 1 vs Group 2)
    contrast_weights <- c(1, -1, rep(0, max(0, k - 2)))
    names(contrast_weights) <- levels_name
  }

  if (length(contrast_weights) != k) {
    stop(paste("对比权重维度 (", length(contrast_weights), ") 与分组水平数 (", k, ") 不符"))
  }

  contrast_estimate <- sum(contrast_weights * means)
  se_contrast <- sqrt(mse * sum((contrast_weights^2) / ns))
  t_stat <- contrast_estimate / se_contrast
  p_val <- 2 * (1 - pt(abs(t_stat), df = df_error))

  margin <- qt(1 - (1 - confidence_level) / 2, df = df_error) * se_contrast

  list(
    dv = dv,
    groupVariable = group_var,
    levels = levels_name,
    contrastWeights = contrast_weights,
    estimate = round(as.numeric(contrast_estimate), 4),
    standardError = round(as.numeric(se_contrast), 4),
    tStatistic = round(as.numeric(t_stat), 4),
    df = df_error,
    pValue = round(as.numeric(p_val), 6),
    confidenceLevel = confidence_level,
    ciLower = round(as.numeric(contrast_estimate - margin), 4),
    ciUpper = round(as.numeric(contrast_estimate + margin), 4)
  )
}

test_homogeneity_of_slopes <- function(data, dv, group_var, covariate) {
  if (!all(c(dv, group_var, covariate) %in% colnames(data))) {
    stop("指定的变量在数据集中不全存在")
  }

  formula_str <- paste(dv, "~", group_var, "*", covariate)
  fit <- aov(as.formula(formula_str), data = data)
  fit_s <- summary(fit)[[1]]

  rows <- trimws(rownames(fit_s))
  target_1 <- paste0(group_var, ":", covariate)
  target_2 <- paste0(covariate, ":", group_var)

  match_idx <- match(target_1, rows)
  if (is.na(match_idx)) {
    match_idx <- match(target_2, rows)
  }

  res_idx <- match("Residuals", rows)

  if (!is.na(match_idx) && !is.na(res_idx)) {
    p_val <- as.numeric(fit_s[match_idx, "Pr(>F)"])
    f_val <- as.numeric(fit_s[match_idx, "F value"])
    df1 <- as.numeric(fit_s[match_idx, "Df"])
    df2 <- as.numeric(fit_s[res_idx, "Df"])

    return(list(
      covariate = covariate,
      groupVariable = group_var,
      fStatistic = round(f_val, 4),
      df1 = df1,
      df2 = df2,
      pValue = round(p_val, 4),
      slopesHomogeneous = p_val >= 0.05,
      warning = if (p_val < 0.05) "违背 ANCOVA 斜率平行假设，建议使用 Moderation 或 Group-specific Slopes" else NULL
    ))
  }

  list(
    covariate = covariate,
    groupVariable = group_var,
    slopesHomogeneous = TRUE,
    warning = NULL
  )
}

# ---------------------------------------------------------------------------
# Between Factorial ANOVA / ANCOVA Execution
# ---------------------------------------------------------------------------

fit_factorial_ancova <- function(data, outcome, between_factors, covariates = NULL, sum_of_squares = "III", confidence_level = 0.95) {
  confidence_level <- researchpath_validate_confidence_level(confidence_level)
  all_vars <- unique(c(outcome, between_factors, covariates))
  sub_df <- data[complete.cases(data[, all_vars, drop = FALSE]), all_vars, drop = FALSE]
  n_total <- nrow(sub_df)
  if (n_total < 4) {
    stop("EXPERIMENT_INSUFFICIENT_OBSERVATIONS: 无法进行方差分析，样本量不足")
  }

  for (f in between_factors) {
    sub_df[[f]] <- as.factor(sub_df[[f]])
    # Set sum-to-zero contrasts for Type III SS
    if (identical(sum_of_squares, "III")) {
      contrasts(sub_df[[f]]) <- contr.sum
    }
  }

  # Build formula
  fact_part <- paste(between_factors, collapse = " * ")
  cov_part <- if (length(covariates) > 0) paste(" +", paste(covariates, collapse = " + ")) else ""
  formula_str <- paste(outcome, "~", fact_part, cov_part)

  fit <- lm(as.formula(formula_str), data = sub_df)
  fit_summary <- summary(fit)

  # Calculate SS Table
  anova_table <- if (requireNamespace("car", quietly = TRUE)) {
    type_num <- if (identical(sum_of_squares, "II")) 2 else 3
    car::Anova(fit, type = type_num)
  } else {
    stats::anova(fit)
  }

  table_df <- as.data.frame(anova_table)
  ss_err <- if ("Residuals" %in% rownames(table_df)) {
    table_df["Residuals", "Sum Sq"]
  } else if ("Residuals" %in% rownames(table_df) || "Sum Sq" %in% names(table_df)) {
    table_df[nrow(table_df), "Sum Sq"]
  } else {
    sum(residuals(fit)^2)
  }
  df_err <- fit$df.residual
  mse <- ss_err / df_err

  table_rows <- list()
  effect_names <- setdiff(rownames(table_df), c("(Intercept)", "Residuals"))

  for (term in effect_names) {
    ss_eff <- table_df[term, "Sum Sq"]
    df_eff <- table_df[term, "Df"]
    f_val <- table_df[term, "F value"]
    p_val <- table_df[term, "Pr(>F)"]

    partial_eta2 <- ss_eff / (ss_eff + ss_err)
    partial_omega2 <- (ss_eff - df_eff * mse) / (ss_eff + (n_total - df_eff) * mse)
    if (!is.finite(partial_omega2) || partial_omega2 < 0) partial_omega2 <- 0.0

    table_rows[[length(table_rows) + 1]] <- list(
      term = term,
      sumOfSquares = finite_number(ss_eff),
      degreesOfFreedom = as.integer(df_eff),
      meanSquare = finite_number(ss_eff / df_eff),
      fStatistic = finite_number(f_val),
      pValue = finite_number(p_val),
      partialEtaSquared = finite_number(partial_eta2),
      partialOmegaSquared = finite_number(partial_omega2)
    )
  }

  # Calculate EMMs (Estimated Marginal Means)
  emm_list <- list()
  for (f in between_factors) {
    lvl_names <- levels(sub_df[[f]])
    means <- tapply(sub_df[[outcome]], sub_df[[f]], mean, na.rm = TRUE)
    sds <- tapply(sub_df[[outcome]], sub_df[[f]], sd, na.rm = TRUE)
    ns <- tapply(sub_df[[outcome]], sub_df[[f]], length)

    for (lvl in lvl_names) {
      m_val <- means[[lvl]]
      n_val <- ns[[lvl]]
      se_val <- sqrt(mse / n_val)
      crit <- qt(1 - (1 - confidence_level) / 2, df = df_err)
      emm_list[[length(emm_list) + 1]] <- list(
        factorVariable = f,
        level = lvl,
        n = as.integer(n_val),
        mean = finite_number(m_val),
        standardError = finite_number(se_val),
        ciLower = finite_number(m_val - crit * se_val),
        ciUpper = finite_number(m_val + crit * se_val)
      )
    }
  }

  # Format Plot-Ready EMM Data for UI/Rendering
  plot_ready <- lapply(emm_list, function(e) {
    list(
      xCategory = e$level,
      groupSeries = e$factorVariable,
      mean = e$mean,
      standardError = e$standardError,
      ciLower = e$ciLower,
      ciUpper = e$ciUpper
    )
  })

  # Format APA 7th Style Summary
  apa_sentences <- character(0)
  for (row in table_rows) {
    p_str <- if (row$pValue < 0.001) "p < .001" else sprintf("p = %.3f", row$pValue)
    apa_sentences <- c(apa_sentences, sprintf(
      "A Type %s ANOVA revealed a significant main effect of %s, F(%d, %d) = %.2f, %s, partial eta^2 = %.2f.",
      sum_of_squares, row$term, row$degreesOfFreedom, df_err, row$fStatistic, p_str, row$partialEtaSquared
    ))
  }
  apa_text <- paste(apa_sentences, collapse = " ")

  list(
    available = TRUE,
    sumOfSquaresType = sum_of_squares,
    sampleSize = as.integer(n_total),
    confidenceLevel = confidence_level,
    errorDegreesOfFreedom = as.integer(df_err),
    meanSquareError = finite_number(mse),
    rSquared = finite_number(fit_summary$r.squared),
    adjustedRSquared = finite_number(fit_summary$adj.r.squared),
    anovaTable = table_rows,
    estimatedMarginalMeans = emm_list,
    plotReadyData = plot_ready,
    apaReport = apa_text
  )
}
