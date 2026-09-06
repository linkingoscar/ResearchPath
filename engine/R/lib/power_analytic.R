run_power <- function() {
  if (identical(spec$method, "monte_carlo")) return(run_power_monte_carlo())
  suppressPackageStartupMessages(library(pwr))

  solve_for <- if (identical(spec$solveFor, "sensitivity")) "effect_size" else spec$solveFor

  if (identical(solve_for, "ci_width")) {
    target_width <- if (!is.null(spec$targetCIWidth)) as.numeric(spec$targetCIWidth) else 0.5
    confidence_level <- if (!is.null(spec$confidenceLevel)) as.numeric(spec$confidenceLevel) else 0.95
    sd_val <- if (!is.null(spec$sd)) as.numeric(spec$sd) else 1.0
    groups_val <- if (!is.null(spec$groups)) as.integer(spec$groups) else 1L
    res <- calc_precision_sample_size(target_width, confidence_level, sd_val, groups_val)
    if (!res$available) stop(res$reason)

    return(list(
      sampleFlow = list(original = 0L, included = 0L, excluded = 0L, missingMethod = "not applicable"),
      estimates = list(
        estimate_entry("required_sample_size", "Required Total Sample Size", res$requiredSampleSize, scale = "count"),
        estimate_entry("achieved_ci_width", "Achieved Confidence Interval Width", res$achievedWidth, scale = "continuous")
      ),
      diagnostics = list(message_entry("PRECISION_ANALYSIS", "info", sprintf("Precision CI target width: %.4f, required N: %d", res$targetWidth, res$requiredSampleSize))),
      warnings = list(),
      provenance = list(engine = "R pwr / precision", engineVersion = "1.0", softwareVersions = list(pwr = "1.3-0"), estimand = "confidence interval precision", degreesOfFreedomMethod = "Student t", sliceId = "power_analysis.precision.ci_width"),
      familyResult = list(family = family, solveFor = "ci_width", solvedValue = as.numeric(res$requiredSampleSize), achievedPower = NULL, powerCurve = list(), parameters = list(targetWidth = res$targetWidth, confidenceLevel = res$confidenceLevel, sd = res$standardDeviation, groups = groups_val)),
      apaReports = list(
        sprintf("A precision analysis was conducted to determine the required sample size for a target CI width of %.3f at %.0f%% confidence.", res$targetWidth, res$confidenceLevel * 100),
        sprintf("The required total sample size is %d.", res$requiredSampleSize)
      )
    ))
  }

  supported <- spec$designFamily %in% c("regression", "t_test", "factorial_anova")
  if (!supported) {
    stop("POWER_DESIGN_NOT_SUPPORTED")
  }
  has_effect_size <- is.list(spec$effectSize) && !is.null(spec$effectSize$metric)
  metric <- if (!has_effect_size) NULL else spec$effectSize$metric
  raw_effect <- if (!has_effect_size) NULL else as.numeric(spec$effectSize$value)
  requested_metric <- if (identical(solve_for, "effect_size")) spec$effectSizeMetric else metric
  if (is.null(requested_metric)) stop("POWER_EFFECT_METRIC_REQUIRED")
  if (!is.null(spec$allocationRatio)) stop("POWER_ALLOCATION_NOT_SUPPORTED")
  if (!is.null(spec$roundingRule) && !identical(spec$roundingRule, "ceil")) stop("POWER_ROUNDING_RULE_NOT_SUPPORTED")
  if (identical(spec$designFamily, "t_test") && !is.null(spec$alternative) && !identical(spec$alternative, "two_sided")) stop("POWER_T_TEST_DIRECTION_REQUIRED")
  if (!identical(spec$designFamily, "t_test") && !is.null(spec$alternative) && !identical(spec$alternative, "two_sided")) stop("POWER_DESIGN_NOT_SUPPORTED")
  alpha <- as.numeric(spec$alpha)
  target <- as.numeric(spec$targetPower)
  analytic <- NULL
  solved <- NULL
  achieved <- NULL
  effect_used <- NULL

  if (identical(spec$designFamily, "regression")) {
    if (!requested_metric %in% c("cohens_f2", "r_squared_change")) stop("POWER_EFFECT_METRIC_NOT_SUPPORTED")
    if (identical(solve_for, "effect_size")) {
      if (has_effect_size) stop("POWER_EFFECT_SIZE_VALUE_NOT_APPLICABLE")
    } else if (!is.null(raw_effect)) {
      effect_used <- if (identical(metric, "r_squared_change")) raw_effect / (1 - raw_effect) else raw_effect
      if (!metric %in% c("cohens_f2", "r_squared_change")) stop("Regression power requires Cohen f2 or R-squared change")
    }
    u <- as.integer(spec$predictors)
    if (identical(solve_for, "sample_size")) {
      analytic <- pwr.f2.test(u = u, v = NULL, f2 = effect_used, sig.level = alpha, power = target)
      solved <- ceiling(analytic$v + u + 1)
      achieved <- pwr.f2.test(u = u, v = solved - u - 1, f2 = effect_used, sig.level = alpha)$power
    } else if (identical(solve_for, "power")) {
      solved <- as.numeric(spec$sampleSize)
      achieved <- pwr.f2.test(u = u, v = solved - u - 1, f2 = effect_used, sig.level = alpha)$power
    } else {
      degrees_freedom <- as.numeric(spec$sampleSize) - u - 1
      analytic <- pwr.f2.test(u = u, v = degrees_freedom, f2 = NULL, sig.level = alpha, power = target)
      upper <- max(1, as.numeric(analytic$f2) * 2)
      while (pwr.f2.test(u = u, v = degrees_freedom, f2 = upper, sig.level = alpha)$power < target) upper <- upper * 2
      effect_used <- uniroot(
        function(value) pwr.f2.test(u = u, v = degrees_freedom, f2 = value, sig.level = alpha)$power - target,
        interval = c(.Machine$double.eps, upper), tol = 1e-12
      )$root
      solved <- if (identical(requested_metric, "r_squared_change")) effect_used / (1 + effect_used) else effect_used
      achieved <- pwr.f2.test(u = u, v = degrees_freedom, f2 = effect_used, sig.level = alpha)$power
    }
    power_at <- function(n) {
      n <- max(as.integer(n), u + 2L)
      pwr.f2.test(u = u, v = n - u - 1, f2 = effect_used, sig.level = alpha)$power
    }
  } else if (identical(spec$designFamily, "t_test")) {
    result <- run_power_t_test(spec, raw_effect, metric, requested_metric, has_effect_size, alpha, target, solve_for)
    analytic <- result$analytic
    solved <- result$solved
    achieved <- result$achieved
    effect_used <- result$effect_used
    power_at <- result$power_at
  } else {
    if (!identical(requested_metric, "cohens_f")) stop("POWER_EFFECT_METRIC_NOT_SUPPORTED")
    if (identical(solve_for, "effect_size") && has_effect_size) stop("POWER_EFFECT_SIZE_VALUE_NOT_APPLICABLE")
    if (!identical(solve_for, "effect_size") && !is.null(raw_effect) && !identical(metric, "cohens_f")) stop("Factorial ANOVA power requires Cohen f")
    effect_used <- raw_effect
    groups <- as.integer(spec$groups)
    if (identical(solve_for, "sample_size")) {
      analytic <- pwr.anova.test(k = groups, n = NULL, f = effect_used, sig.level = alpha, power = target)
      per_group <- ceiling(analytic$n)
      solved <- per_group * groups
      achieved <- pwr.anova.test(k = groups, n = per_group, f = effect_used, sig.level = alpha)$power
    } else if (identical(solve_for, "power")) {
      solved <- as.numeric(spec$sampleSize)
      if (solved %% groups != 0) stop("POWER_SAMPLE_SIZE_NOT_DIVISIBLE_BY_GROUPS")
      per_group <- solved / groups
      achieved <- pwr.anova.test(k = groups, n = per_group, f = effect_used, sig.level = alpha)$power
    } else {
      if (as.numeric(spec$sampleSize) %% groups != 0) stop("POWER_SAMPLE_SIZE_NOT_DIVISIBLE_BY_GROUPS")
      per_group <- as.numeric(spec$sampleSize) / groups
      analytic <- pwr.anova.test(k = groups, n = per_group, f = NULL, sig.level = alpha, power = target)
      upper <- max(1, as.numeric(analytic$f) * 2)
      while (pwr.anova.test(k = groups, n = per_group, f = upper, sig.level = alpha)$power < target) upper <- upper * 2
      effect_used <- uniroot(
        function(value) pwr.anova.test(k = groups, n = per_group, f = value, sig.level = alpha)$power - target,
        interval = c(.Machine$double.eps, upper), tol = 1e-12
      )$root
      solved <- effect_used
      achieved <- pwr.anova.test(k = groups, n = per_group, f = solved, sig.level = alpha)$power
    }
    power_at <- function(n) {
      per_group <- max(2L, as.integer(n) / groups)
      pwr.anova.test(k = groups, n = per_group, f = effect_used, sig.level = alpha)$power
    }
  }

  warnings <- list()
  curve_base <- if (identical(solve_for, "sample_size")) as.numeric(solved) else as.numeric(spec$sampleSize)
  if (identical(spec$designFamily, "regression")) {
    curve_n <- unique(pmax(as.integer(spec$predictors) + 2L, round(curve_base * c(0.75, 0.9, 1, 1.1, 1.25))))
  } else if (identical(spec$designFamily, "t_test")) {
    groups <- as.integer(spec$groups)
    curve_n <- if (groups == 1L) unique(pmax(4L, round(curve_base * c(0.75, 0.9, 1, 1.1, 1.25)))) else unique(groups * pmax(2L, round(curve_base * c(0.75, 0.9, 1, 1.1, 1.25) / groups)))
  } else {
    groups <- as.integer(spec$groups)
    curve_per_group <- pmax(2L, round(curve_base * c(0.75, 0.9, 1, 1.1, 1.25) / groups))
    curve_n <- unique(groups * curve_per_group)
  }
  curve <- lapply(curve_n, function(n) list(sampleSize = as.integer(n), power = finite(power_at(n))))

  reported_effect <- if (identical(solve_for, "effect_size")) as.numeric(solved) else raw_effect
  metric_label <- switch(
    requested_metric,
    cohens_f = "Cohen's f",
    cohens_d = "Cohen's d",
    cohens_f2 = "Cohen's f²",
    r_squared_change = "R² change",
    requested_metric
  )
  parameters <- list(
    alpha = alpha,
    alternative = if (is.null(spec$alternative)) "two_sided" else spec$alternative,
    groups = as.integer(spec$groups),
    predictors = as.integer(spec$predictors),
    effectSize = if (has_effect_size) spec$effectSize else NULL,
    effectSizeMetric = requested_metric,
    solvedValueMetric = if (identical(solve_for, "effect_size")) requested_metric else if (identical(solve_for, "power")) "power" else "total_sample_size",
    solvedEffectSize = if (identical(solve_for, "effect_size")) list(metric = requested_metric, value = as.numeric(solved)) else NULL,
    allocationRatio = if (!is.null(spec$allocationRatio)) as.numeric(spec$allocationRatio) else NULL
  )

  apaReports <- list()
  if (identical(solve_for, "sample_size")) {
    apaReports[[1]] <- sprintf("A power analysis was conducted to determine the required sample size to detect %s = %.3f with %.0f%% power and alpha = %.3f.", metric_label, as.numeric(reported_effect), target * 100, alpha)
    apaReports[[2]] <- sprintf("The recommended total sample size is %s.", solved)
  } else if (identical(solve_for, "power")) {
    apaReports[[1]] <- sprintf("A power analysis was conducted to estimate the statistical power given a sample size of %s, %s = %.3f, and alpha = %.3f.", spec$sampleSize, metric_label, as.numeric(reported_effect), alpha)
    apaReports[[2]] <- sprintf("The achieved power is %.1f%%.", achieved * 100)
  } else {
    apaReports[[1]] <- sprintf("A sensitivity power analysis was conducted given a sample size of %s, a target power of %.0f%%, and alpha = %.3f.", spec$sampleSize, target * 100, alpha)
    apaReports[[2]] <- sprintf("The minimum detectable %s is %.3f.", metric_label, solved)
  }

  list(
    sampleFlow = list(original = 0L, included = 0L, excluded = 0L, missingMethod = "not applicable"),
    estimates = list(estimate_entry("power", "Achieved power", achieved, scale = "probability")),
    diagnostics = list(message_entry("POWER_BACKCHECK", "info", sprintf("Solved design back-check power: %.6f", achieved))),
    warnings = warnings,
    provenance = list(engine = "R pwr", engineVersion = as.character(packageVersion("pwr")), softwareVersions = package_versions(c("pwr")), estimand = "frequentist rejection probability", degreesOfFreedomMethod = if (identical(spec$designFamily, "t_test")) "noncentral t" else "noncentral F", sliceId = paste0("power_analysis.analytic.", spec$designFamily)),
    familyResult = list(family = family, solveFor = solve_for, solvedValue = as.numeric(solved), achievedPower = as.numeric(achieved), monteCarloStandardError = NULL, powerCurve = curve, parameters = parameters),
    apaReports = apaReports
  )
}

# ---------------------------------------------------------------------------
# Precision Analysis (CI Width Target)
# ---------------------------------------------------------------------------

calc_precision_sample_size <- function(target_width, confidence_level = 0.95, sd = 1.0, groups = 1) {
  if (!is.finite(target_width) || target_width <= 0 || !is.finite(sd) || sd <= 0) {
    return(list(available = FALSE, reason = "目标 CI 宽度与标准差必须为正数"))
  }
  margin <- target_width / 2.0
  z_crit <- qnorm(1 - (1 - confidence_level) / 2)
  n_approx <- (z_crit * sd / margin)^2 * groups

  # Refine using t-distribution iteration
  n_curr <- max(4, ceiling(n_approx))
  for (iter in 1:20) {
    df <- if (groups == 1) n_curr - 1 else n_curr - 2
    t_crit <- qt(1 - (1 - confidence_level) / 2, df = max(1, df))
    n_new <- ceiling((t_crit * sd / margin)^2 * groups)
    if (n_new == n_curr) break
    n_curr <- n_new
  }

  list(
    available = TRUE,
    targetWidth = finite_number(target_width),
    confidenceLevel = finite_number(confidence_level),
    standardDeviation = finite_number(sd),
    requiredSampleSize = as.integer(n_curr),
    achievedWidth = finite_number(2 * qt(1 - (1 - confidence_level) / 2, df = max(1, n_curr - groups)) * sd / sqrt(n_curr / groups))
  )
}
