# R module for Measurement Invariance

invariance_model_availability <- function(model_metrics) {
  labels <- c("configural", "metric", "scalar", "strict")
  available <- setNames(lapply(labels, function(label) {
    !is.null(model_metrics[[label]])
  }), labels)
  warnings <- list()
  for (label in labels[-1]) {
    if (!isTRUE(available[[label]])) {
      warnings[[length(warnings) + 1L]] <- list(
        code = "INVARIANCE_LEVEL_UNAVAILABLE",
        severity = "warning",
        message = paste0(
          label, " invariance model is unavailable；",
          "只有 configural 层级可解释，后续层级不能当作已通过。"
        )
      )
    }
  }
  list(modelAvailability = available, warnings = warnings)
}

run_measurement_invariance <- function(data, model_syntax, group_variable, estimator = "ML",
                                      partial_release = TRUE, missing = "listwise",
                                      group_partial = NULL) {
  if (!requireNamespace("lavaan", quietly = TRUE)) {
    stop("INVARIANCE_LAVAAN_NOT_INSTALLED: lavaan package is required for measurement invariance testing")
  }

  if (!group_variable %in% names(data)) {
    stop(paste0("INVARIANCE_INVALID_GROUP_VARIABLE: Grouping variable ", group_variable, " not found in dataset"))
  }

  data[[group_variable]] <- as.factor(data[[group_variable]])
  group_levels <- levels(data[[group_variable]])
  if (length(group_levels) < 2) {
    stop("INVARIANCE_INSUFFICIENT_GROUPS: Measurement invariance requires at least 2 group levels")
  }

  fit_model <- function(group_equal = NULL, custom_partial = NULL, label = "configural") {
    tryCatch({
      lavaan::cfa(
        model_syntax,
        data = data,
        group = group_variable,
        estimator = estimator,
        missing = if (identical(missing, "fiml")) "fiml" else "listwise",
        group.equal = group_equal,
        group.partial = if (!is.null(custom_partial)) custom_partial else group_partial
      )
    }, error = function(e) {
      model_errors[[label]] <<- conditionMessage(e)
      NULL
    })
  }

  model_errors <- list()
  # 1. Configural Invariance
  fit_configural <- fit_model(group_equal = NULL, label = "configural")
  if (is.null(fit_configural) || !isTRUE(lavaan::lavInspect(fit_configural, "converged"))) {
    return(list(available = FALSE, reason = "Configural invariance model failed to converge"))
  }

  # 2. Metric Invariance (weak)
  fit_metric <- fit_model(group_equal = c("loadings"), label = "metric")

  # 3. Scalar Invariance (strong)
  fit_scalar <- fit_model(group_equal = c("loadings", "intercepts"), label = "scalar")

  # 4. Strict Invariance
  fit_strict <- fit_model(group_equal = c("loadings", "intercepts", "residuals"), label = "strict")

  extract_fit <- function(fit) {
    if (is.null(fit) || !isTRUE(lavaan::lavInspect(fit, "converged"))) return(NULL)
    m <- lavaan::fitMeasures(fit)
    get_m <- function(n, alt = NULL) {
      if (!is.null(m[n]) && is.finite(m[n])) return(as.numeric(m[n]))
      if (!is.null(alt) && !is.null(m[alt]) && is.finite(m[alt])) return(as.numeric(m[alt]))
      NA_real_
    }
    list(
      chiSquare = get_m("chisq"),
      chiSquareScaled = get_m("chisq.scaled"),
      df = as.integer(get_m("df")),
      pValue = get_m("pvalue"),
      cfi = get_m("cfi"),
      cfiRobust = get_m("cfi.robust", "cfi.scaled"),
      tli = get_m("tli"),
      tliRobust = get_m("tli.robust", "tli.scaled"),
      rmsea = get_m("rmsea"),
      rmseaRobust = get_m("rmsea.robust", "rmsea.scaled"),
      srmr = get_m("srmr")
    )
  }

  m_configural <- extract_fit(fit_configural)
  m_metric <- extract_fit(fit_metric)
  m_scalar <- extract_fit(fit_scalar)
  m_strict <- extract_fit(fit_strict)
  comparison_value <- function(model, robust_name, classic_name) {
    if (is.null(model)) return(NA_real_)
    robust <- model[[robust_name]]
    if (!is.null(robust) && is.finite(robust)) robust else model[[classic_name]]
  }
  fit_change <- function(current, previous) {
    robust_available <- !is.null(current) && !is.null(previous) &&
      is.finite(current$cfiRobust) && is.finite(previous$cfiRobust)
    list(
      deltaCfi = comparison_value(current, "cfiRobust", "cfi") -
        comparison_value(previous, "cfiRobust", "cfi"),
      deltaRmsea = comparison_value(current, "rmseaRobust", "rmsea") -
        comparison_value(previous, "rmseaRobust", "rmsea"),
      fitIndexBasis = if (robust_available) "robust/scaled where available" else "standard"
    )
  }

  # Adjacent model comparisons. Fit-index changes remain available even when
  # a scaled likelihood-ratio difference cannot be computed.
  compare_models <- function(previous_fit, current_fit, previous_metrics, current_metrics) {
    change <- fit_change(current_metrics, previous_metrics)
    lrt <- tryCatch(lavaan::lavTestLRT(previous_fit, current_fit), error = function(e) NULL)
    list(
      deltaChiSquare = if (!is.null(lrt) && nrow(lrt) >= 2) finite_number(as.numeric(lrt$`Chisq diff`[2])) else NA_real_,
      deltaDf = if (!is.null(lrt) && nrow(lrt) >= 2) finite_number(as.numeric(lrt$`Df diff`[2])) else
        finite_number(current_metrics$df - previous_metrics$df),
      pValue = if (!is.null(lrt) && nrow(lrt) >= 2) finite_number(as.numeric(lrt$`Pr(>Chisq)`[2])) else NA_real_,
      deltaCfi = finite_number(change$deltaCfi),
      deltaRmsea = finite_number(change$deltaRmsea),
      fitIndexBasis = change$fitIndexBasis
    )
  }
  lrt_res <- list()
  if (!is.null(m_metric)) {
    lrt_res$metric <- compare_models(fit_configural, fit_metric, m_configural, m_metric)
  }
  if (!is.null(m_metric) && !is.null(m_scalar)) {
    lrt_res$scalar <- compare_models(fit_metric, fit_scalar, m_metric, m_scalar)
  }
  if (!is.null(m_scalar) && !is.null(m_strict)) {
    lrt_res$strict <- compare_models(fit_scalar, fit_strict, m_scalar, m_strict)
  }

  # Latent Mean Comparison (from scalar invariance model)
  latent_means <- list()
  if (!is.null(fit_scalar)) {
    par <- tryCatch(lavaan::parameterEstimates(fit_scalar, ci = TRUE), error = function(e) NULL)
    if (!is.null(par)) {
      means_df <- par[par$op == "~1" & grepl("^F_", par$lhs), ]
      for (i in seq_len(nrow(means_df))) {
        row <- means_df[i, ]
        latent_means[[length(latent_means) + 1]] <- list(
          latentVariable = row$lhs,
          group = group_levels[row$group],
          estimate = finite_number(row$est),
          se = finite_number(row$se),
          zValue = finite_number(row$z),
          pValue = finite_number(row$pvalue),
          ciLower = finite_number(row$ci.lower),
          ciUpper = finite_number(row$ci.upper)
        )
      }
    }
  }

  # Partial invariance inspection
  partial_released_parameters <- list()
  if (isTRUE(partial_release) && !is.null(fit_metric)) {
    mod_idx <- tryCatch(lavaan::modindices(fit_metric, sort = TRUE), error = function(e) NULL)
    if (!is.null(mod_idx) && nrow(mod_idx) > 0) {
      high_mi <- mod_idx[mod_idx$mi > 10.0, ]
      if (nrow(high_mi) > 0) {
        for (i in seq_len(min(3, nrow(high_mi)))) {
          r <- high_mi[i, ]
          partial_released_parameters[[length(partial_released_parameters) + 1]] <- list(
            lhs = r$lhs, op = r$op, rhs = r$rhs, mi = as.numeric(r$mi), epc = as.numeric(r$epc)
          )
        }
      }
    }
  }

  availability <- invariance_model_availability(list(
    configural = m_configural,
    metric = m_metric,
    scalar = m_scalar,
    strict = m_strict
  ))

  list(
    available = TRUE,
    sampleSize = as.integer(lavaan::lavInspect(fit_configural, "ntotal")),
    missingMethod = missing,
    groupVariable = group_variable,
    groupLevels = as.list(group_levels),
    groupSizes = as.list(as.integer(table(data[[group_variable]]))),
    modelAvailability = availability$modelAvailability,
    warnings = availability$warnings,
    models = list(
      configural = m_configural,
      metric = m_metric,
      scalar = m_scalar,
      strict = m_strict
    ),
    comparisons = lrt_res,
    latentMeans = latent_means,
    partialReleasedParameters = partial_released_parameters
  )
}
