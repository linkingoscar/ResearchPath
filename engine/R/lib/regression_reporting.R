# Public helper alias; the implementation lives in inference_covariance.R.
hc3_covariance <- function(fit) researchpath_hc3_covariance(fit)

coefficient_rows <- function(fit, label_lookup, robust_se = NULL, confidence_level = 0.95, robust_covariance = NULL) {
  table <- summary(fit)$coefficients
  degrees <- df.residual(fit)
  critical <- qt(1 - (1 - confidence_level) / 2, degrees)
  predictor_names <- setdiff(names(coef(fit)), "(Intercept)")

  # Calculate HC3 robust covariance if requested
  cov_mat <- NULL
  if (identical(robust_se, "HC3")) {
    cov_mat <- robust_covariance
    if (is.null(cov_mat)) {
      hc3_info <- researchpath_hc3_covariance(fit)
      if (isTRUE(hc3_info$available)) cov_mat <- hc3_info$covariance
    }
  }

  vif_values <- setNames(rep(NA_real_, length(predictor_names)), predictor_names)
  if (length(predictor_names) >= 2) {
    model_frame <- model.frame(fit)
    if (all(predictor_names %in% names(model_frame))) {
      for (name in predictor_names) {
        others <- setdiff(predictor_names, name)
        auxiliary <- lm(reformulate(others, response = name), data = model_frame)
        vif_values[[name]] <- 1 / (1 - summary(auxiliary)$r.squared)
      }
    }
  }

  sd_x <- apply(model.matrix(fit), 2, sd)
  y_val <- model.frame(fit)[[1]]
  sd_y <- sd(y_val)

  lapply(seq_len(nrow(table)), function(index) {
    term <- rownames(table)[index]
    estimate <- table[index, 1]
    standard_error <- if (identical(robust_se, "HC3")) {
      if (!is.null(cov_mat)) sqrt(cov_mat[index, index]) else NA_real_
    } else table[index, 2]
    t_stat <- estimate / standard_error
    p_val <- 2 * pt(-abs(t_stat), df = degrees)

    std_coef <- NA_real_
    cohen_f2 <- NA_real_
    if (term != "(Intercept)") {
      if (is.finite(sd_y) && sd_y > 0 && term %in% names(sd_x)) {
        std_coef <- estimate * (sd_x[[term]] / sd_y)
      }
      if (degrees > 0) {
        cohen_f2 <- t_stat^2 / degrees
      }
    }

    list(
      term = term,
      label = if (term == "(Intercept)") "常数" else label_lookup(term),
      estimate = finite_number(estimate),
      standardError = finite_number(standard_error),
      statistic = finite_number(t_stat),
      pValue = finite_number(p_val),
      standardizedEstimate = finite_number(std_coef),
      cohenF2 = finite_number(cohen_f2),
      lower = finite_number(estimate - critical * standard_error),
      upper = finite_number(estimate + critical * standard_error),
      vif = if (term %in% names(vif_values)) finite_number(vif_values[[term]]) else NA_real_
    )
  })
}

regression_sensitivity_report <- function(adjusted_fit, unadjusted_fit, label_lookup, confidence_level = 0.95) {
  classic <- coefficient_rows(adjusted_fit, label_lookup, confidence_level = confidence_level)
  hc3_info <- researchpath_hc3_covariance(adjusted_fit)
  hc3 <- coefficient_rows(
    adjusted_fit, label_lookup, robust_se = "HC3", confidence_level = confidence_level,
    robust_covariance = hc3_info$covariance
  )
  classic_by_term <- setNames(classic, vapply(classic, function(row) row$term, character(1)))
  hc3_by_term <- setNames(hc3, vapply(hc3, function(row) row$term, character(1)))
  terms <- setdiff(names(classic_by_term), "(Intercept)")
  standard_error_comparison <- lapply(terms, function(term) {
    classic_row <- classic_by_term[[term]]
    hc3_row <- hc3_by_term[[term]]
    list(
      term = term, label = label_lookup(term), estimate = classic_row$estimate,
      classicStandardError = classic_row$standardError, classicPValue = classic_row$pValue,
      classicLower = classic_row$lower, classicUpper = classic_row$upper,
      hc3StandardError = hc3_row$standardError, hc3PValue = hc3_row$pValue,
      hc3Lower = hc3_row$lower, hc3Upper = hc3_row$upper
    )
  })

  cooks <- cooks.distance(adjusted_fit)
  leverage <- hatvalues(adjusted_fit)
  cook_cutoff <- 4 / nobs(adjusted_fit)
  leverage_cutoff <- 2 * length(coef(adjusted_fit)) / nobs(adjusted_fit)
  influential <- which(cooks > cook_cutoff | leverage > leverage_cutoff)
  retained <- setdiff(seq_len(nobs(adjusted_fit)), influential)
  sensitivity_fit <- if (length(influential) > 0 && length(retained) > length(coef(adjusted_fit))) {
    lm(formula(adjusted_fit), data = model.frame(adjusted_fit)[retained, , drop = FALSE])
  } else {
    NULL
  }
  sensitivity_rows <- if (is.null(sensitivity_fit)) list() else coefficient_rows(sensitivity_fit, label_lookup, confidence_level = confidence_level)
  sensitivity_by_term <- setNames(
    sensitivity_rows,
    vapply(sensitivity_rows, function(row) row$term, character(1))
  )

  unadjusted_rows <- coefficient_rows(unadjusted_fit, label_lookup, confidence_level = confidence_level)
  unadjusted_by_term <- setNames(
    unadjusted_rows,
    vapply(unadjusted_rows, function(row) row$term, character(1))
  )
  coefficient_stability <- lapply(terms, function(term) {
    adjusted_row <- classic_by_term[[term]]
    unadjusted_row <- unadjusted_by_term[[term]]
    sensitivity_row <- sensitivity_by_term[[term]]
    list(
      term = term, label = label_lookup(term),
      unadjustedEstimate = if (is.null(unadjusted_row)) NA_real_ else unadjusted_row$estimate,
      adjustedEstimate = adjusted_row$estimate,
      withoutInfluentialEstimate = if (is.null(sensitivity_row)) NA_real_ else sensitivity_row$estimate,
      signChangedAfterControls = if (is.null(unadjusted_row)) NA else
        sign(unadjusted_row$estimate) != sign(adjusted_row$estimate),
      signChangedWithoutInfluential = if (is.null(sensitivity_row)) NA else
        sign(sensitivity_row$estimate) != sign(adjusted_row$estimate)
    )
  })

  list(
    hc3Execution = c(
      researchpath_hc3_execution_metadata(hc3_info),
      list(
        requested = hc3_info$requestedMethod, executed = hc3_info$executedMethod,
        confidenceLevel = confidence_level,
        leveragePolicy = "exact hat values; no clipping; leverage effectively equal to one makes HC3 unavailable"
      )
    ),
    standardErrorComparison = standard_error_comparison,
    influence = list(
      cookDistanceCutoff = finite_number(cook_cutoff),
      leverageCutoff = finite_number(leverage_cutoff),
      influentialCount = length(influential),
      retainedCount = length(retained),
      maximumCookDistance = finite_number(max(cooks)),
      maximumLeverage = finite_number(max(leverage)),
      rule = "Cook distance > 4/N or leverage > 2p/N; flagged cases are not removed from the primary model"
    ),
    coefficientStability = coefficient_stability
  )
}

# ---------------------------------------------------------------------------
# Binary Logistic Regression & Average Marginal Effects (AME)
# ---------------------------------------------------------------------------

fit_binary_logistic_with_ame <- function(
  data, formula_obj, label_lookup, confidence_level = 0.95,
  interaction_terms = character(0)
) {
  fit <- tryCatch(
    glm(formula_obj, data = data, family = binomial(link = "logit")),
    error = function(e) NULL
  )
  if (is.null(fit) || !fit$converged) {
    return(list(available = FALSE, reason = "二分类 Logistic 回归未收敛"))
  }

  table <- summary(fit)$coefficients
  n <- nobs(fit)
  frame <- model.frame(fit)
  model_terms <- delete.response(terms(fit))
  X <- model.matrix(model_terms, data = frame)
  beta <- coef(fit)
  covariance <- vcov(fit)
  critical <- qnorm(1 - (1 - confidence_level) / 2)

  marginal_effect <- function(term) {
    column_index <- match(term, colnames(X))
    if (is.na(column_index)) return(NULL)
    assignment <- attr(X, "assign")[[column_index]]
    labels <- attr(model_terms, "term.labels")
    source <- if (assignment > 0L && assignment <= length(labels)) labels[[assignment]] else term
    if (researchpath_is_interaction_term(term, interaction_terms, labels)) {
      return(researchpath_not_applicable_interaction_effect(confidence_level))
    }
    source_values <- if (source %in% names(frame)) frame[[source]] else NULL
    reference_level <- NULL; contrast_level <- NULL
    if (!is.null(source_values) && (is.logical(source_values) || (is.numeric(source_values) && length(unique(source_values)) == 2L && all(sort(unique(source_values)) == c(0, 1))))) {
      reference <- frame; contrast <- frame
      reference[[source]] <- if (is.logical(source_values)) FALSE else 0
      contrast[[source]] <- if (is.logical(source_values)) TRUE else 1
      x_reference <- model.matrix(model_terms, data = reference)
      x_contrast <- model.matrix(model_terms, data = contrast)
      type <- "discrete"; reference_level <- "0"; contrast_level <- "1"
      estimand <- "average discrete change in Pr(Y=1) for a 0→1 change"
      evaluate <- function(parameters) mean(plogis(drop(x_contrast %*% parameters)) - plogis(drop(x_reference %*% parameters)))
    } else if (is.factor(source_values)) {
      levels_found <- levels(source_values); reference_level <- levels_found[[1]]
      reference <- frame; reference[[source]] <- factor(reference_level, levels = levels_found)
      x_reference <- model.matrix(model_terms, data = reference)
      candidates <- setdiff(levels_found, reference_level)
      candidate_designs <- lapply(candidates, function(level) {
        candidate <- frame; candidate[[source]] <- factor(level, levels = levels_found)
        model.matrix(model_terms, data = candidate)
      })
      differences <- vapply(candidate_designs, function(candidate) mean(abs(candidate[, column_index] - x_reference[, column_index])), numeric(1))
      target <- which.max(differences)
      if (length(target) == 0L || differences[[target]] <= 0) return(NULL)
      contrast_level <- candidates[[target]]; x_contrast <- candidate_designs[[target]]
      type <- "categorical_contrast"
      estimand <- paste0("average discrete change in Pr(Y=1) for ", source, ": ", contrast_level, " versus ", reference_level)
      evaluate <- function(parameters) mean(plogis(drop(x_contrast %*% parameters)) - plogis(drop(x_reference %*% parameters)))
    } else {
      continuous_step <- max(diff(range(source_values, na.rm = TRUE)) * 1e-4, 1e-10)
      lower_frame <- frame
      upper_frame <- frame
      lower_frame[[source]] <- source_values - continuous_step / 2
      upper_frame[[source]] <- source_values + continuous_step / 2
      type <- "continuous_derivative"
      estimand <- "average derivative of Pr(Y=1) for a one-unit term change"
      evaluate <- function(parameters) {
        fit_at <- fit
        fit_at[["coefficients"]] <- parameters
        mean((
          stats::predict(fit_at, newdata = upper_frame, type = "response") -
            stats::predict(fit_at, newdata = lower_frame, type = "response")
        ) / continuous_step)
      }
    }
    estimate <- evaluate(beta)
    gradient <- vapply(seq_along(beta), function(index) {
      step <- max(abs(beta[[index]]) * sqrt(.Machine$double.eps), 1e-10)
      plus <- beta
      plus[[index]] <- plus[[index]] + step
      (evaluate(plus) - estimate) / step
    }, numeric(1))
    variance <- as.numeric(t(gradient) %*% covariance %*% gradient)
    standard_error <- if (is.finite(variance) && variance >= 0) sqrt(variance) else NA_real_
    list(
      estimate = finite_number(estimate), type = type, estimand = estimand,
      referenceLevel = reference_level, contrastLevel = contrast_level,
      standardError = finite_number(standard_error),
      ciLower = finite_number(estimate - critical * standard_error),
      ciUpper = finite_number(estimate + critical * standard_error)
    )
  }

  coef_list <- lapply(seq_len(nrow(table)), function(i) {
    term <- rownames(table)[i]
    b <- table[i, 1]
    se <- table[i, 2]
    z <- table[i, 3]
    p_val <- table[i, 4]
    or <- exp(b)
    effect <- if (term == "(Intercept)") NULL else marginal_effect(term)
    row <- list(
      term = term,
      label = if (term == "(Intercept)") "常数" else label_lookup(term),
      estimate = finite_number(b),
      standardError = finite_number(se),
      zValue = finite_number(z),
      pValue = finite_number(p_val),
      oddsRatio = finite_number(or),
      orCiLower = finite_number(exp(b - critical * se)),
      orCiUpper = finite_number(exp(b + critical * se)),
      confidenceLevel = confidence_level
    )
    if (!is.null(effect)) {
      row$averageMarginalEffect <- effect$estimate; row$marginalEffectType <- effect$type
      row$marginalEffectEstimand <- effect$estimand; row$marginalEffectStandardError <- effect$standardError
      row$marginalEffectCiLower <- effect$ciLower; row$marginalEffectCiUpper <- effect$ciUpper
      if (!is.null(effect$reason)) row$marginalEffectReason <- effect$reason
      if (!is.null(effect$referenceLevel)) row$marginalEffectReferenceLevel <- effect$referenceLevel
      if (!is.null(effect$contrastLevel)) row$marginalEffectContrastLevel <- effect$contrastLevel
    }
    row
  })

  null_fit <- glm(update(formula_obj, . ~ 1), data = data, family = binomial(link = "logit"))
  mcfadden_r2 <- 1 - (logLik(fit) / logLik(null_fit))

  list(
    available = TRUE,
    converged = TRUE,
    sampleSize = as.integer(n),
    nullDeviance = finite_number(fit$null.deviance),
    residualDeviance = finite_number(fit$deviance),
    aic = finite_number(AIC(fit)),
    mcfaddenRSquared = finite_number(as.numeric(mcfadden_r2)),
    coefficients = coef_list
  )
}
