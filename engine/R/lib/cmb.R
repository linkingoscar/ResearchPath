# cmb.R
# Common Method Bias (CMB) Diagnostic Suite
# Marker Variable Method (Lindell & Whitney 2001), Unmeasured Latent Method Factor (ULMC), MTMM

calc_marker_variable_cmb <- function(df, marker_var_id, constructs) {
  if (is.null(marker_var_id) || !(marker_var_id %in% names(df))) {
    return(list(available = FALSE, reason = "未提供有效的 Marker 变量"))
  }
  
  marker_val <- df[[marker_var_id]]
  construct_scores <- data.frame(matrix(NA_real_, nrow(df), length(constructs)))
  construct_ids <- vapply(constructs, function(c) c$id, character(1))
  names(construct_scores) <- construct_ids
  
  for (i in seq_along(constructs)) {
    ids <- intersect(unlist(constructs[[i]]$itemIds), names(df))
    if (length(ids) > 0) {
      construct_scores[[i]] <- rowMeans(df[, ids, drop = FALSE], na.rm = TRUE)
    }
  }
  
  # Remove incomplete cases
  comp_df <- cbind(marker = marker_val, construct_scores)
  comp_df <- comp_df[complete.cases(comp_df), , drop = FALSE]
  if (nrow(comp_df) < 20) {
    return(list(available = FALSE, reason = "Marker 变量检验有效案例不足 20"))
  }
  
  cor_mat <- cor(comp_df)
  marker_cors <- cor_mat["marker", construct_ids]
  
  # r_m choice: smallest positive correlation with marker variable (Lindell & Whitney 2001)
  pos_cors <- marker_cors[marker_cors > 0]
  r_m <- if (length(pos_cors) > 0) min(pos_cors) else 0.0
  
  # Adjusted construct correlations: r_adj = (r - r_m) / (1 - r_m)
  sub_cors <- cor_mat[construct_ids, construct_ids, drop = FALSE]
  adj_cors <- (sub_cors - r_m) / (1.0 - r_m)
  diag(adj_cors) <- 1.0
  
  # t-statistic: t = r_adj * sqrt(N - 3) / sqrt(1 - r_adj^2)
  N <- nrow(comp_df)
  t_mat <- adj_cors * sqrt(N - 3) / sqrt(pmax(1.0 - adj_cors^2, 1e-6))
  p_mat <- 2 * (1 - pt(abs(t_mat), df = N - 3))
  diag(p_mat) <- 0.0
  
  list(
    available = TRUE,
    method = "Lindell_Whitney_2001_Marker_Variable",
    markerVariableId = marker_var_id,
    r_m = finite_number(r_m),
    sampleSize = N,
    rawCorrelations = mat_to_list(sub_cors),
    adjustedCorrelations = mat_to_list(adj_cors),
    adjustedPValues = mat_to_list(p_mat),
    methodologicalWarning = "提示：Marker 变量调整为事后统计诊断，程序性控制（如匿名性、时空分离）才是排除 CMB 的第一道防线。"
  )
}

fit_ulmc_cmb_model <- function(items, constructs) {
  if (nrow(items) < 30 || ncol(items) < 4) {
    return(list(available = FALSE, reason = "ULMC 方法因子分析需要至少 30 个案例和 4 个题项"))
  }
  
  kept_constructs <- list()
  for (construct in constructs) {
    ids <- intersect(unlist(construct$itemIds), names(items))
    if (length(ids) >= 2) {
      kept_constructs[[length(kept_constructs) + 1]] <- list(id = construct$id, label = construct$label, itemIds = ids)
    }
  }
  if (length(kept_constructs) < 2) {
    return(list(available = FALSE, reason = "ULMC 分析需要至少 2 个包含 2 个以上题项的构念"))
  }
  
  all_item_ids <- unlist(lapply(kept_constructs, function(c) c$itemIds))
  all_item_ids <- unique(all_item_ids)
  sub_df <- items[, all_item_ids, drop = FALSE]
  
  # 1. Baseline Substantive CFA Model
  sub_syntax <- paste(vapply(kept_constructs, function(c) {
    paste0("F_", c$id, " =~ ", paste(c$itemIds, collapse = " + "))
  }, character(1)), collapse = "\n")
  
  fit_base <- tryCatch(lavaan::cfa(sub_syntax, data = sub_df, estimator = "ML"), error = function(e) NULL)
  if (is.null(fit_base) || !isTRUE(lavaan::lavInspect(fit_base, "converged"))) {
    return(list(available = FALSE, reason = "Baseline CFA 模型估计未收敛"))
  }
  
  # 2. ULMC Model: Baseline + Method Factor (constrained equal loadings, orthogonal to substantive)
  method_syntax <- paste0("ULMC_Method =~ ", paste(paste0("m*", all_item_ids), collapse = " + "))
  ortho_syntax <- paste(vapply(kept_constructs, function(c) {
    paste0("ULMC_Method ~~ 0*F_", c$id)
  }, character(1)), collapse = "\n")
  
  ulmc_syntax <- paste(c(sub_syntax, method_syntax, ortho_syntax), collapse = "\n")
  
  fit_ulmc <- tryCatch({
    lavaan::cfa(ulmc_syntax, data = sub_df, estimator = "ML", bounds = "pos.var")
  }, error = function(e) NULL)
  
  if (is.null(fit_ulmc) || !isTRUE(lavaan::lavInspect(fit_ulmc, "converged"))) {
    return(list(available = FALSE, reason = "ULMC 未测量潜方法因子模型估计未收敛，可能由于方法变异性过低"))
  }
  
  m_base <- lavaan::fitMeasures(fit_base)
  m_ulmc <- lavaan::fitMeasures(fit_ulmc)
  
  # Model Comparison (Chi-square LRT)
  lrt <- tryCatch(lavaan::lavTestLRT(fit_base, fit_ulmc), error = function(e) NULL)
  delta_chisq <- if (!is.null(lrt) && nrow(lrt) >= 2) lrt$`Chisq diff`[[2]] else NA_real_
  delta_df <- if (!is.null(lrt) && nrow(lrt) >= 2) lrt$`Df diff`[[2]] else NA_real_
  p_val <- if (!is.null(lrt) && nrow(lrt) >= 2) lrt$`Pr(>Chisq)`[[2]] else NA_real_
  
  delta_cfi <- as.numeric(m_ulmc["cfi"] - m_base["cfi"])
  delta_rmsea <- as.numeric(m_ulmc["rmsea"] - m_base["rmsea"])
  
  list(
    available = TRUE,
    method = "Unmeasured_Latent_Method_Factor_ULMC",
    baselineModel = list(
      chisq = finite_number(as.numeric(m_base["chisq"])),
      df = finite_number(as.numeric(m_base["df"])),
      cfi = finite_number(as.numeric(m_base["cfi"])),
      rmsea = finite_number(as.numeric(m_base["rmsea"]))
    ),
    ulmcModel = list(
      chisq = finite_number(as.numeric(m_ulmc["chisq"])),
      df = finite_number(as.numeric(m_ulmc["df"])),
      cfi = finite_number(as.numeric(m_ulmc["cfi"])),
      rmsea = finite_number(as.numeric(m_ulmc["rmsea"]))
    ),
    modelComparison = list(
      deltaChisq = finite_number(delta_chisq),
      deltaDf = finite_number(delta_df),
      pValue = finite_number(p_val),
      deltaCfi = finite_number(delta_cfi),
      deltaRmsea = finite_number(delta_rmsea),
      significantMethodBias = isTRUE(p_val < 0.05 && delta_cfi > 0.01)
    ),
    methodologicalWarning = "提示：未测量潜方法因子检验 (ULMC) 显著仅表明存在公共方法变异，不代表研究结论失效。请结合理论逻辑评估。"
  )
}
