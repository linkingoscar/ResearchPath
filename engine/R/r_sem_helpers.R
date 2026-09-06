# SEM 辅助函数库 (r_sem_helpers.R)
# 提供拟合指数提取、参数解析和潜变量信效度计算

library(lavaan)

# 1. 提取拟合优度指数（适配 ML 与 WLSMV 估计器）
get_fit_indices <- function(fit) {
  m <- fitMeasures(fit)

  safe_val <- function(target_names) {
    for (n in target_names) {
      if (n %in% names(m)) {
        val <- m[[n]]
        if (!is.null(val) && is.finite(val)) return(as.numeric(val))
      }
    }
    return(NA_real_)
  }

  chiSquare <- safe_val("chisq")
  df <- as.integer(safe_val("df"))
  pValue <- safe_val("pvalue")
  cfi <- safe_val("cfi")
  tli <- safe_val("tli")
  rmsea <- safe_val("rmsea")
  srmr <- safe_val("srmr")
  rmseaCiLower <- safe_val("rmsea.ci.lower")
  rmseaCiUpper <- safe_val("rmsea.ci.upper")

  # 稳健拟合指数（WLSMV 或 Robust ML）
  robustChiSquare <- safe_val("chisq.scaled")
  robustDf <- safe_val("df.scaled")
  if (!is.na(robustDf)) robustDf <- as.integer(robustDf)
  robustPValue <- safe_val("pvalue.scaled")
  robustCfi <- safe_val(c("cfi.robust", "cfi.scaled"))
  robustTli <- safe_val(c("tli.robust", "tli.scaled"))
  robustRmsea <- safe_val(c("rmsea.robust", "rmsea.scaled"))
  robustRmseaCiLower <- safe_val(c("rmsea.ci.lower.scaled", "rmsea.robust.ci.lower"))
  robustRmseaCiUpper <- safe_val(c("rmsea.ci.upper.scaled", "rmsea.robust.ci.upper"))

  list(
    chiSquare = if (is.finite(chiSquare)) chiSquare else NA_real_,
    df = if (is.finite(df)) df else NA_integer_,
    pValue = if (is.finite(pValue)) pValue else NA_real_,
    cfi = if (is.finite(cfi)) cfi else NA_real_,
    tli = if (is.finite(tli)) tli else NA_real_,
    rmsea = if (is.finite(rmsea)) rmsea else NA_real_,
    srmr = if (is.finite(srmr)) srmr else NA_real_,
    rmseaCiLower = if (is.finite(rmseaCiLower)) rmseaCiLower else NA_real_,
    rmseaCiUpper = if (is.finite(rmseaCiUpper)) rmseaCiUpper else NA_real_,
    robustChiSquare = if (is.na(robustChiSquare)) NULL else robustChiSquare,
    robustDf = if (is.na(robustDf)) NULL else robustDf,
    robustPValue = if (is.na(robustPValue)) NULL else robustPValue,
    robustCfi = if (is.na(robustCfi)) NULL else robustCfi,
    robustTli = if (is.na(robustTli)) NULL else robustTli,
    robustRmsea = if (is.na(robustRmsea)) NULL else robustRmsea,
    robustRmseaCiLower = if (is.na(robustRmseaCiLower)) NULL else robustRmseaCiLower,
    robustRmseaCiUpper = if (is.na(robustRmseaCiUpper)) NULL else robustRmseaCiUpper
  )
}

# 2. 提取回归与测量参数（含 confidenceLevel 驱动的正态临界值 CI）
#
# merge 键在多组拟合时必须包含 group，否则 pe 与 std 的行会在组间
# 发生笛卡尔积错位；单组拟合两个对象都没有 group 列，键自动退化。
get_sem_parameters <- function(
  fit,
  higher_order_ids = character(0),
  confidence_level = 0.95
) {
  pe <- parameterEstimates(fit)
  std <- standardizedSolution(fit)

  merge_keys <- c("lhs", "op", "rhs")
  if ("group" %in% names(pe) && "group" %in% names(std)) {
    merge_keys <- c(merge_keys, "group")
  }
  m <- merge(pe, std, by = merge_keys, suffixes = c("", ".std"))

  critical <- stats::qnorm(1 - (1 - confidence_level) / 2)
  interval_bounds <- function(est, se) {
    if (
      length(est) == 1 && length(se) == 1 &&
        is.finite(est) && is.finite(se)
    ) {
      list(ciLower = est - critical * se, ciUpper = est + critical * se)
    } else {
      list(ciLower = NA_real_, ciUpper = NA_real_)
    }
  }

  loadings <- list()
  paths <- list()

  # 提取因子载荷 (op == "=~")
  m_loadings <- m[m$op == "=~", ]
  if (nrow(m_loadings) > 0) {
    for (i in 1:nrow(m_loadings)) {
      bounds <- interval_bounds(m_loadings$est[i], m_loadings$se[i])
      loadings[[length(loadings) + 1]] <- list(
        latentId = m_loadings$lhs[i],
        indicatorId = m_loadings$rhs[i],
        level = if (m_loadings$lhs[i] %in% higher_order_ids) "higher_order" else "first_order",
        estimate = as.numeric(m_loadings$est[i]),
        standardError = as.numeric(m_loadings$se[i]),
        statistic = as.numeric(m_loadings$z[i]),
        pValue = as.numeric(m_loadings$pvalue[i]),
        stdAll = as.numeric(m_loadings$est.std[i]),
        ciLower = bounds$ciLower,
        ciUpper = bounds$ciUpper
      )
    }
  }

  # 提取结构关系路径 (op == "~")
  m_paths <- m[m$op == "~", ]
  if (nrow(m_paths) > 0) {
    for (i in 1:nrow(m_paths)) {
      bounds <- interval_bounds(m_paths$est[i], m_paths$se[i])
      paths[[length(paths) + 1]] <- list(
        from = m_paths$rhs[i],
        to = m_paths$lhs[i],
        estimate = as.numeric(m_paths$est[i]),
        standardError = as.numeric(m_paths$se[i]),
        statistic = as.numeric(m_paths$z[i]),
        pValue = as.numeric(m_paths$pvalue[i]),
        stdAll = as.numeric(m_paths$est.std[i]),
        ciLower = bounds$ciLower,
        ciUpper = bounds$ciUpper
      )
    }
  }

  list(loadings = loadings, paths = paths)
}

# 3. 计算 Cronbach's Alpha（同时返回完整案例数以披露样本口径；
#    alpha 始终基于 listwise 完整案例，与主拟合的 FIML 样本可能不同，
#    该差异通过 alphaSampleSize 字段向下游披露。）
calc_alpha_with_n <- function(data, item_ids) {
  items_data <- data[, item_ids, drop = FALSE]
  items_data <- items_data[complete.cases(items_data), , drop = FALSE]
  k <- ncol(items_data)
  n <- nrow(items_data)
  if (k < 2 || n < 3) return(list(alpha = NA_real_, n = as.integer(n)))
  item_vars <- apply(items_data, 2, var)
  total_var <- var(rowSums(items_data))
  if (total_var == 0) return(list(alpha = NA_real_, n = as.integer(n)))
  alpha <- (k / (k - 1)) * (1 - sum(item_vars) / total_var)
  list(alpha = as.numeric(alpha), n = as.integer(n))
}

calc_alpha <- function(data, item_ids) {
  calc_alpha_with_n(data, item_ids)$alpha
}

# 4. 计算组合信度 (CR) 与平均方差提取值 (AVE)
#
# 命名说明：cfa_validity.R 另有一个面向构念列表的 calc_cr_ave（签名不同）。
# 为避免同一 R 会话中后加载者静默覆盖前者，SEM 路径使用独立命名。
calc_sem_cr_ave <- function(std_loadings) {
  sum_loadings_sq <- (sum(std_loadings))^2
  sum_residuals <- sum(1 - std_loadings^2)
  cr <- sum_loadings_sq / (sum_loadings_sq + sum_residuals)
  ave <- sum(std_loadings^2) / length(std_loadings)
  list(cr = as.numeric(cr), ave = as.numeric(ave))
}

# 检测某构念指标之间是否存在自由估计的相关残差（op=="~~" 且 est≠0）。
# 存在时 Fornell-Larcker 型 CR/ω 公式不再成立（遗漏误差协方差项，
# 系统性高估信度），必须抑制输出而不是静默给出有偏数值。
# 使用 parTable（而非 parameterEstimates）因为需要 free 列区分固定与自由参数。
detect_correlated_residuals <- function(param_table, item_ids) {
  rows <- param_table[
    param_table$op == "~~" &
      param_table$lhs != param_table$rhs &
      param_table$lhs %in% item_ids &
      param_table$rhs %in% item_ids,
    ,
    drop = FALSE
  ]
  rows <- rows[rows$free > 0 & !is.na(rows$est) & rows$est != 0, , drop = FALSE]
  paste(rows$lhs, rows$rhs, sep = " ~~ ")
}

# 5. 聚合信效度指标（返回 reliability 条目与结构化警告）
#
# 相关残差守门：检测到自由相关残差时，mcdonaldOmega/compositeReliability
# 输出 null 并给出来因字段 + 警告码 SEM_CR_SUPPRESSED_CORRELATED_RESIDUALS；
# alpha（不依赖模型残差设定）和 AVE（惯例公式）照常报告。
calc_latent_reliability <- function(fit, data, latents) {
  std <- standardizedSolution(fit)
  param_table <- parTable(fit)
  reliability <- list()
  warnings_out <- list()
  for (lat in latents) {
    latent_id <- lat$id
    item_ids <- unlist(lat$indicators)
    if (identical(lat$level, "higher_order") || !all(item_ids %in% names(data))) next
    lat_loadings <- std[std$lhs == latent_id & std$op == "=~" & std$rhs %in% item_ids, ]
    if (nrow(lat_loadings) >= 2) {
      lambda <- as.numeric(lat_loadings$est.std)
      cr_ave <- calc_sem_cr_ave(lambda)
      alpha_result <- calc_alpha_with_n(data, item_ids)
      correlated_residuals <- detect_correlated_residuals(param_table, item_ids)
      cr_available <- length(correlated_residuals) == 0L
      entry <- list(
        latentId = latent_id,
        cronbachAlpha = if (is.na(alpha_result$alpha)) NA_real_ else alpha_result$alpha,
        alphaSampleSize = if (is.na(alpha_result$n)) NA_integer_ else alpha_result$n,
        # 单因子等载荷测量下 McDonald's ω 与 CR 一致；含相关残差时不成立，
        # 抑制为 null 并附来因。
        mcdonaldOmega = if (cr_available) cr_ave$cr else NA_real_,
        compositeReliability = if (cr_available) cr_ave$cr else NA_real_,
        compositeReliabilityReason = if (cr_available) {
          NA_character_
        } else {
          "suppressed_correlated_residuals"
        },
        ave = cr_ave$ave
      )
      reliability[[length(reliability) + 1]] <- entry
      if (!cr_available) {
        warnings_out[[length(warnings_out) + 1]] <- list(
          code = "SEM_CR_SUPPRESSED_CORRELATED_RESIDUALS",
          severity = "warning",
          message = paste0(
            "潜变量 ", latent_id,
            " 的指标间存在自由相关残差（",
            paste(correlated_residuals, collapse = "、"),
            "）；Fornell-Larcker 型 CR/ω 公式在该设定下不成立，",
            "已置 null 并要求人工复核或改用基于模型隐含协方差的信度估计。"
          )
        )
      }
    }
  }
  list(reliability = reliability, warnings = warnings_out)
}
