# ResearchPath R Engine - RI-CLPM & Latent Growth Modeling

fit_riclpm_model <- function(data, x_waves, y_waves, estimator = "MLR", missing = "fiml") {
  suppressPackageStartupMessages(library(lavaan))

  if (length(x_waves) < 3 || length(y_waves) < 3) {
    stop("RI-CLPM 模型至少需要 3 个时间波段的数据")
  }

  num_waves <- min(length(x_waves), length(y_waves))
  ri_x_syntax <- paste0("RI_X =~ ", paste(paste0("1*", x_waves[seq_len(num_waves)]), collapse = " + "))
  ri_y_syntax <- paste0("RI_Y =~ ", paste(paste0("1*", y_waves[seq_len(num_waves)]), collapse = " + "))

  within_syntax <- character(0)
  for (t in seq_len(num_waves)) {
    within_syntax <- c(
      within_syntax,
      paste0("wx_", t, " =~ 1*", x_waves[[t]]),
      paste0("wy_", t, " =~ 1*", y_waves[[t]]),
      paste0(x_waves[[t]], " ~~ 0*", x_waves[[t]]),
      paste0(y_waves[[t]], " ~~ 0*", y_waves[[t]]),
      paste0("wx_", t, " ~~ wy_", t)
    )
  }

  clpm_paths <- character(0)
  if (num_waves > 1) {
    for (t in 2:num_waves) {
      previous <- t - 1
      clpm_paths <- c(
        clpm_paths,
        paste0("wx_", t, " ~ a1*wx_", previous, " + c1*wy_", previous),
        paste0("wy_", t, " ~ a2*wy_", previous, " + c2*wx_", previous)
      )
    }
  }

  orthogonality <- c(
    paste0("RI_X ~~ 0*wx_", seq_len(num_waves)),
    paste0("RI_X ~~ 0*wy_", seq_len(num_waves)),
    paste0("RI_Y ~~ 0*wx_", seq_len(num_waves)),
    paste0("RI_Y ~~ 0*wy_", seq_len(num_waves)),
    "RI_X ~~ RI_Y"
  )
  model_syntax <- paste(c(ri_x_syntax, ri_y_syntax, within_syntax, clpm_paths, orthogonality), collapse = "\n")
  fit <- lavaan::sem(
    model_syntax,
    data = data,
    estimator = estimator,
    missing = if (identical(missing, "fiml")) "fiml" else "listwise",
    auto.fix.first = FALSE,
    auto.var = TRUE
  )
  if (!lavaan::lavInspect(fit, "converged")) stop("RI-CLPM 模型拟合未收敛")

  finite_number <- function(value) {
    if (length(value) == 0L || is.na(value[[1]]) || !is.finite(value[[1]])) return(NULL)
    as.numeric(value[[1]])
  }
  parameters <- lavaan::parameterEstimates(fit)
  cross_lagged <- parameters[parameters$op == "~" & parameters$label %in% c("c1", "c2"), , drop = FALSE]
  autoregressive <- parameters[parameters$op == "~" & parameters$label %in% c("a1", "a2"), , drop = FALSE]
  effect_rows <- function(rows) lapply(seq_len(nrow(rows)), function(index) list(
    lhs = as.character(rows$lhs[[index]]),
    rhs = as.character(rows$rhs[[index]]),
    estimate = finite_number(rows$est[[index]]),
    standardError = finite_number(rows$se[[index]]),
    zValue = finite_number(rows$z[[index]]),
    pValue = finite_number(rows$pvalue[[index]])
  ))
  trait_row <- function(lhs, rhs = lhs) {
    row <- parameters[parameters$op == "~~" & parameters$lhs == lhs & parameters$rhs == rhs, , drop = FALSE]
    if (nrow(row) == 0L && lhs != rhs) row <- parameters[parameters$op == "~~" & parameters$lhs == rhs & parameters$rhs == lhs, , drop = FALSE]
    if (nrow(row) == 0L) return(NULL)
    finite_number(row$est)
  }
  fit_metrics <- lavaan::fitMeasures(fit, c("chisq", "df", "pvalue", "cfi", "tli", "rmsea", "srmr"))
  missing_patterns <- NULL
  if (identical(missing, "fiml")) {
    patterns <- tryCatch(lavaan::lavInspect(fit, "patterns"), error = function(error) NULL)
    if (!is.null(patterns)) missing_patterns <- as.integer(nrow(patterns))
  }

  list(
    available = TRUE,
    modelType = "RI-CLPM",
    sampleSize = as.integer(lavaan::lavInspect(fit, "ntotal")),
    missingMethod = missing,
    missingPatterns = missing_patterns,
    numWaves = num_waves,
    converged = TRUE,
    fitIndices = list(
      chiSquare = finite_number(fit_metrics[["chisq"]]),
      df = as.integer(fit_metrics[["df"]]),
      pValue = finite_number(fit_metrics[["pvalue"]]),
      cfi = finite_number(fit_metrics[["cfi"]]),
      tli = finite_number(fit_metrics[["tli"]]),
      rmsea = finite_number(fit_metrics[["rmsea"]]),
      srmr = finite_number(fit_metrics[["srmr"]])
    ),
    traitComponents = list(
      var_RI_X = trait_row("RI_X"),
      var_RI_Y = trait_row("RI_Y"),
      cov_RI = trait_row("RI_X", "RI_Y")
    ),
    autoregressiveEffects = effect_rows(autoregressive),
    crossLaggedEffects = effect_rows(cross_lagged)
  )
}
