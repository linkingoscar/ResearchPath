# ResearchPath R Engine - Multiple Imputation Rubin Pooling
#
# 能力边界：产品只提供逐系数 Rubin 合并，不包含多变量 D1/D3 检验。
# 未来若增加多变量合并检验，
# 必须先定义公开结果契约、方法参考与独立验证证据，再进入本库。

if (!exists("researchpath_validate_confidence_level", mode = "function", inherits = TRUE)) {
  researchpath_validate_confidence_level <- function(value, label = "confidenceLevel") {
    level <- suppressWarnings(as.numeric(value))
    if (length(level) != 1L || !is.finite(level) || level <= 0.5 || level >= 1) {
      stop(sprintf("%s 必须位于 (0.5, 1.0) 区间", label), call. = FALSE)
    }
    level
  }
}

pool_rubin_estimates <- function(estimates, standard_errors, m_df = NULL, confidence_level = 0.95) {
  confidence_level <- researchpath_validate_confidence_level(confidence_level)
  m <- length(estimates)
  if (m < 2) {
    stop("Rubin 规则汇合需要至少 2 个插补数据集的结果")
  }
  if (length(standard_errors) != m || any(!is.finite(estimates)) || any(!is.finite(standard_errors)) || any(standard_errors < 0)) {
    stop("Rubin 规则汇合的估计值和标准误必须是等长有限数值")
  }

  q_bar <- mean(estimates)
  u_bar <- mean(standard_errors^2)
  b_var <- var(estimates)

  t_var <- u_bar + (1 + 1 / m) * b_var
  se_pooled <- sqrt(t_var)

  # Barnard-Rubin degrees of freedom adjustment
  df_com <- if (!is.null(m_df)) mean(m_df) else Inf
  riv <- if (u_bar > 0) (1 + 1 / m) * b_var / u_bar else if (b_var > 0) Inf else 0
  df_old <- if (is.finite(riv)) (m - 1) * (1 + 1 / riv)^2 else m - 1
  gamma <- if (t_var > 0) (1 + 1 / m) * b_var / t_var else 0
  df_obs <- if (is.finite(df_com)) ((df_com + 1) / (df_com + 3)) * df_com * (1 - gamma) else Inf
  # The algebraic product form produces Inf / Inf when the between-imputation
  # variance is exactly zero.  In that limiting case the observed-data df is
  # the Barnard--Rubin limit; retain it rather than serialising NaN/null.
  nu <- if (is.infinite(df_old) && is.finite(df_obs)) {
    df_obs
  } else if (is.finite(df_obs)) {
    (df_old * df_obs) / (df_old + df_obs)
  } else {
    df_old
  }
  fmi <- if (is.finite(riv)) (riv + 2 / (df_old + 3)) / (riv + 1) else 1

  t_stat <- if (se_pooled > 0) q_bar / se_pooled else 0
  p_val <- if (se_pooled > 0) 2 * (1 - pt(abs(t_stat), df = nu)) else if (q_bar == 0) 1 else 0

  margin <- if (se_pooled > 0) qt(1 - (1 - confidence_level) / 2, df = nu) * se_pooled else 0

  list(
    m = as.integer(m),
    pooledEstimate = finite_number(q_bar),
    pooledSE = finite_number(se_pooled),
    withinVariance = finite_number(u_bar),
    betweenVariance = finite_number(b_var),
    totalVariance = finite_number(t_var),
    degreesOfFreedom = finite_number(nu),
    tStatistic = finite_number(t_stat),
    pValue = finite_number(p_val),
    confidenceLevel = confidence_level,
    ciLower = finite_number(q_bar - margin),
    ciUpper = finite_number(q_bar + margin),
    RIV = finite_number(riv),
    FMI = finite_number(fmi)
  )
}
