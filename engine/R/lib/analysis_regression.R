# HC3 execution is shared with the empirical regression path.  An unavailable
# HC3 covariance is represented as an unavailable inference matrix; it is
# never replaced by the classical covariance for the requested estimator.
hc3_unavailable_warnings <- list()
hc3_execution_records <- list()

fit_plan <- function(data, plan) {
  formula <- reformulate(plan$predictors, response = plan$outcome)
  if (plan$outcome %in% binary_node_ids) {
    tryCatch(
      {
        separation_warning <- NULL
        model <- withCallingHandlers(
          glm(formula, data = data, family = binomial(link = "logit")),
          warning = function(warning) {
            warning_message <- conditionMessage(warning)
            if (grepl("did not converge|fitted probabilities numerically 0 or 1", warning_message, ignore.case = TRUE)) {
              separation_warning <<- warning_message
              invokeRestart("muffleWarning")
            }
          }
        )
        if (!isTRUE(model$converged)) stop("maximum-likelihood iteration did not converge; possible complete or quasi-complete separation")
        if (!is.null(separation_warning)) stop(paste("complete or quasi-complete separation detected:", separation_warning))
        if (any(!is.finite(coef(model)))) stop("non-finite coefficient estimate")
        model
      },
      error = function(error) stop(sprintf("Logistic regression failed for %s: %s", plan$outcome, error$message))
    )
  } else {
    tryCatch(
      {
        model <- lm(formula, data = data)
        if (any(!is.finite(coef(model)))) stop("non-finite coefficient estimate")
        model
      },
      error = function(error) stop(sprintf("OLS regression failed for %s: %s", plan$outcome, error$message))
    )
  }
}

fit_models <- function(data) lapply(plans, function(plan) fit_plan(data, plan))

model_vcov <- function(model) {
  if (identical(spec$estimation$standardErrors, "hc3")) {
    execution <- researchpath_hc3_covariance(model)
    hc3_execution_records[[length(hc3_execution_records) + 1L]] <<- researchpath_hc3_execution_metadata(execution)
    if (isTRUE(execution$available)) {
      covariance <- execution$covariance
      attr(covariance, "researchpath_standard_error_method") <- execution$executedMethod
      attr(covariance, "researchpath_covariance_available") <- TRUE
      return(covariance)
    }
    hc3_unavailable_warnings[[length(hc3_unavailable_warnings) + 1L]] <<- list(
      code = "HC3_UNAVAILABLE",
      severity = "warning",
      message = paste0("HC3 稳健标准误不可计算（", execution$fallbackReason, "）；未执行经典标准误替代，请人工复核。")
    )
    return(researchpath_unavailable_covariance(model, execution))
  }
  covariance <- stats::vcov(model)
  attr(covariance, "researchpath_standard_error_method") <- "classical"
  attr(covariance, "researchpath_covariance_available") <- TRUE
  covariance
}

get_r_squared <- function(model) {
  if (inherits(model, "glm")) {
    r2 <- tryCatch({
      null_formula <- as.formula(paste(names(model$model)[1], "~ 1"))
      null_model <- glm(null_formula, data = model$model, family = family(model))
      ll_null <- logLik(null_model)
      ll_full <- logLik(model)
      as.numeric(1 - ll_full / ll_null)
    }, error = function(e) NA_real_)
    finite_number(r2)
  } else {
    finite_number(summary(model)$r.squared)
  }
}

get_adj_r_squared <- function(model) {
  if (inherits(model, "glm")) {
    r2 <- tryCatch({
      null_formula <- as.formula(paste(names(model$model)[1], "~ 1"))
      null_model <- glm(null_formula, data = model$model, family = family(model))
      ll_null <- logLik(null_model)
      ll_full <- logLik(model)
      k <- length(coef(model))
      as.numeric(1 - (ll_full - k) / ll_null)
    }, error = function(e) NA_real_)
    finite_number(r2)
  } else {
    finite_number(summary(model)$adj.r.squared)
  }
}

get_nagelkerke_r_squared <- function(model) {
  if (inherits(model, "glm")) {
    r2 <- tryCatch({
      null_formula <- as.formula(paste(names(model$model)[1], "~ 1"))
      null_model <- glm(null_formula, data = model$model, family = family(model))
      ll_null <- logLik(null_model)
      ll_full <- logLik(model)
      n <- nobs(model)
      r2_cox <- 1 - exp(2 * (ll_null - ll_full) / n)
      r2_max <- 1 - exp(2 * ll_null / n)
      as.numeric(r2_cox / r2_max)
    }, error = function(e) NA_real_)
    finite_number(r2)
  } else {
    NA_real_
  }
}

average_marginal_effect <- function(model, term, binary_ids) {
  if (!inherits(model, "glm") || !identical(family(model)$link, "logit") || identical(term, "(Intercept)")) {
    return(NULL)
  }
  model_terms <- delete.response(terms(model))
  frame <- model.frame(model)
  design <- model.matrix(model_terms, data = frame)
  beta <- coef(model)
  finite_beta <- beta
  finite_beta[!is.finite(finite_beta)] <- 0
  column_index <- match(term, colnames(design))
  if (is.na(column_index)) return(NULL)
  assignment <- attr(design, "assign")[[column_index]]
  term_labels <- attr(model_terms, "term.labels")
  declared_interaction_terms <- researchpath_declared_interaction_terms(spec$moderations)
  if (researchpath_is_interaction_term(term, declared_interaction_terms, term_labels)) {
    return(researchpath_not_applicable_interaction_effect(spec$estimation$confidenceLevel))
  }
  source_variable <- if (assignment > 0L && assignment <= length(term_labels)) term_labels[[assignment]] else term
  source_is_simple <- source_variable %in% names(frame)
  source_values <- if (source_is_simple) frame[[source_variable]] else NULL
  is_binary_source <- source_is_simple && (
    source_variable %in% binary_ids ||
      (is.numeric(source_values) && length(unique(source_values)) == 2L && all(sort(unique(source_values)) == c(0, 1))) ||
      (is.logical(source_values) && length(unique(source_values)) == 2L)
  )
  reference_level <- NULL
  contrast_level <- NULL
  if (is_binary_source && source_variable %in% colnames(design)) {
    zero_frame <- frame
    one_frame <- frame
    zero_frame[[source_variable]] <- if (is.logical(source_values)) FALSE else 0
    one_frame[[source_variable]] <- if (is.logical(source_values)) TRUE else 1
    x_zero <- model.matrix(model_terms, data = zero_frame)
    x_one <- model.matrix(model_terms, data = one_frame)
    p_zero <- plogis(drop(x_zero %*% finite_beta))
    p_one <- plogis(drop(x_one %*% finite_beta))
    estimate <- mean(p_one - p_zero)
    estimand <- "average discrete change in Pr(Y=1) for a 0→1 change"
    effect_type <- "discrete"
    reference_level <- "0"
    contrast_level <- "1"
    ame_at <- function(parameters) mean(plogis(drop(x_one %*% parameters)) - plogis(drop(x_zero %*% parameters)))
  } else if (source_is_simple && is.factor(source_values)) {
    levels_found <- levels(source_values)
    reference_level <- levels_found[[1]]
    reference_frame <- frame
    reference_frame[[source_variable]] <- factor(reference_level, levels = levels_found)
    x_reference <- model.matrix(model_terms, data = reference_frame)
    candidate_levels <- setdiff(levels_found, reference_level)
    candidate_designs <- lapply(candidate_levels, function(level) {
      candidate_frame <- frame
      candidate_frame[[source_variable]] <- factor(level, levels = levels_found)
      model.matrix(model_terms, data = candidate_frame)
    })
    differences <- vapply(candidate_designs, function(candidate) {
      mean(abs(candidate[, column_index] - x_reference[, column_index]))
    }, numeric(1))
    target_index <- which.max(differences)
    if (length(target_index) == 0L || differences[[target_index]] <= 0) return(NULL)
    contrast_level <- candidate_levels[[target_index]]
    x_contrast <- candidate_designs[[target_index]]
    p_reference <- plogis(drop(x_reference %*% finite_beta))
    p_contrast <- plogis(drop(x_contrast %*% finite_beta))
    estimate <- mean(p_contrast - p_reference)
    estimand <- paste0("average discrete change in Pr(Y=1) for ", source_variable, ": ", contrast_level, " versus ", reference_level)
    effect_type <- "categorical_contrast"
    ame_at <- function(parameters) mean(plogis(drop(x_contrast %*% parameters)) - plogis(drop(x_reference %*% parameters)))
  } else {
    continuous_step <- max(diff(range(source_values, na.rm = TRUE)) * 1e-4, 1e-10)
    lower_frame <- frame
    upper_frame <- frame
    lower_frame[[source_variable]] <- source_values - continuous_step / 2
    upper_frame[[source_variable]] <- source_values + continuous_step / 2
    estimand <- "average derivative of Pr(Y=1) for a one-unit term change"
    effect_type <- "continuous_derivative"
    ame_at <- function(parameters) {
      model_at <- model
      model_at[["coefficients"]] <- parameters
      mean((
        stats::predict(model_at, newdata = upper_frame, type = "response") -
          stats::predict(model_at, newdata = lower_frame, type = "response")
      ) / continuous_step)
    }
    estimate <- ame_at(finite_beta)
  }
  covariance <- tryCatch(model_vcov(model), error = function(error) NULL)
  standard_error <- NA_real_
  lower <- NA_real_
  upper <- NA_real_
  if (!is.null(covariance) && all(dim(covariance) == c(length(beta), length(beta))) && all(is.finite(covariance))) {
    gradient <- numeric(length(beta))
    for (index in seq_along(beta)) {
      step <- max(abs(finite_beta[[index]]) * sqrt(.Machine$double.eps), 1e-10)
      plus <- finite_beta
      plus[[index]] <- plus[[index]] + step
      gradient[[index]] <- (ame_at(plus) - estimate) / step
    }
    variance <- as.numeric(t(gradient) %*% covariance %*% gradient)
    if (is.finite(variance) && variance >= 0) {
      standard_error <- sqrt(variance)
      critical <- qnorm(1 - (1 - spec$estimation$confidenceLevel) / 2)
      lower <- estimate - critical * standard_error
      upper <- estimate + critical * standard_error
    }
  }
  list(
    estimate = finite_number(estimate), type = effect_type, estimand = estimand,
    referenceLevel = reference_level, contrastLevel = contrast_level,
    standardError = finite_number(standard_error),
    confidenceInterval = list(
      level = spec$estimation$confidenceLevel, lower = finite_number(lower), upper = finite_number(upper),
      method = "delta_method_on_model_vcov"
    )
  )
}

coefficient_rows <- function(model, equation_id) {
  estimates <- coef(model)
  covariance <- model_vcov(model)
  # vcov() 会丢弃完全共线（别名）项，而 coef() 保留为 NA。按名对齐，
  # 避免 estimates / standard_errors 触发 R 向量回收导致系数-标准误错配。
  non_aliased <- !is.na(estimates)
  se_full <- rep(NA_real_, length(estimates))
  names(se_full) <- names(estimates)
  covariance_names <- rownames(covariance)
  if (!is.null(covariance_names) && all(covariance_names %in% names(estimates))) {
    se_full[covariance_names] <- sqrt(diag(covariance))
  } else {
    se_full[non_aliased] <- sqrt(diag(covariance))
  }
  statistic <- ifelse(non_aliased, estimates / se_full, NA_real_)
  
  is_glm <- inherits(model, "glm")
  if (is_glm) {
    p_values <- 2 * pnorm(abs(statistic), lower.tail = FALSE)
    critical <- qnorm(1 - (1 - spec$estimation$confidenceLevel) / 2)
  } else {
    degrees <- df.residual(model)
    p_values <- 2 * pt(abs(statistic), df = degrees, lower.tail = FALSE)
    critical <- qt(1 - (1 - spec$estimation$confidenceLevel) / 2, df = degrees)
  }
  
  sd_x <- apply(model.matrix(model), 2, sd)
  y_val <- model.frame(model)[[1]]
  sd_y <- sd(y_val)
  
  lapply(seq_along(estimates), function(index) {
    term <- names(estimates)[[index]]
    estimate <- unname(estimates[[index]])
    t_stat <- unname(statistic[[index]])
    
    std_coef <- NA_real_
    cohen_f2 <- NA_real_
    if (!is_glm) {
      if (term != "(Intercept)" && is.finite(sd_y) && sd_y > 0) {
        if (term %in% names(sd_x)) {
          std_coef <- estimate * (sd_x[[term]] / sd_y)
        }
      }
      if (term != "(Intercept)" && degrees > 0) {
        cohen_f2 <- t_stat^2 / degrees
      }
    }
    
    confidence_interval <- list(
      level = spec$estimation$confidenceLevel,
      lower = unname(estimates[[index]] - critical * se_full[[index]]),
      upper = unname(estimates[[index]] + critical * se_full[[index]]),
      method = researchpath_confidence_interval_method(
        covariance,
        is_glm,
        spec$estimation$standardErrors
      )
    )
    row <- list(
      equationId = equation_id,
      term = term,
      estimate = estimate,
      standardError = unname(se_full[[index]]),
      statistic = t_stat,
      pValue = unname(p_values[[index]]),
      standardizedEstimate = std_coef,
      cohenF2 = cohen_f2,
      confidenceInterval = confidence_interval
    )
    if (is_glm) {
      row$oddsRatio <- exp(estimate)
      row$oddsRatioConfidenceInterval <- list(
        level = spec$estimation$confidenceLevel,
        lower = exp(confidence_interval$lower),
        upper = exp(confidence_interval$upper),
        method = confidence_interval$method
      )
      marginal_effect <- average_marginal_effect(model, term, binary_node_ids)
      if (!is.null(marginal_effect)) {
        row$averageMarginalEffect <- marginal_effect$estimate
        row$marginalEffectType <- marginal_effect$type
        row$marginalEffectEstimand <- marginal_effect$estimand
        if (!is.null(marginal_effect$referenceLevel)) row$marginalEffectReferenceLevel <- marginal_effect$referenceLevel
        if (!is.null(marginal_effect$contrastLevel)) row$marginalEffectContrastLevel <- marginal_effect$contrastLevel
        if (!is.null(marginal_effect$reason)) row$marginalEffectReason <- marginal_effect$reason
        if (is.finite(marginal_effect$standardError)) row$marginalEffectStandardError <- marginal_effect$standardError
        if (is.finite(marginal_effect$confidenceInterval$lower) && is.finite(marginal_effect$confidenceInterval$upper)) {
          row$marginalEffectConfidenceInterval <- marginal_effect$confidenceInterval
        }
      }
    }
    row
  })
}

# ---------------------------------------------------------------------------
# Johnson-Neyman Floodlight Analysis
# ---------------------------------------------------------------------------

calc_johnson_neyman <- function(b1, b3, var_b1, var_b3, cov_b1_b3, df_res, w_min, w_max, confidence_level = 0.95) {
  if (!is.finite(b1) || !is.finite(b3) || df_res <= 1 || w_min >= w_max) {
    return(list(available = FALSE, reason = "无法进行 Johnson-Neyman 计算"))
  }
  t_crit <- qt(1 - (1 - confidence_level) / 2, df = df_res)
  t_crit_sq <- t_crit^2

  A <- b3^2 - t_crit_sq * var_b3
  B <- 2 * b1 * b3 - 2 * t_crit_sq * cov_b1_b3
  C <- b1^2 - t_crit_sq * var_b1

  discriminant <- B^2 - 4 * A * C
  boundaries <- numeric(0)

  if (is.finite(discriminant) && discriminant >= 0 && abs(A) > 1e-12) {
    w1 <- (-B - sqrt(discriminant)) / (2 * A)
    w2 <- (-B + sqrt(discriminant)) / (2 * A)
    boundaries <- sort(c(w1, w2))
  }

  w_grid <- seq(w_min, w_max, length.out = 50)
  slopes <- numeric(50)
  se_slopes <- numeric(50)
  p_values <- numeric(50)

  for (k in seq_along(w_grid)) {
    w_val <- w_grid[k]
    eff <- b1 + b3 * w_val
    var_eff <- var_b1 + (w_val^2) * var_b3 + 2 * w_val * cov_b1_b3
    se_eff <- if (var_eff > 0) sqrt(var_eff) else 0.0
    t_val <- if (se_eff > 0) eff / se_eff else 0.0
    slopes[k] <- eff
    se_slopes[k] <- se_eff
    p_values[k] <- 2 * pt(-abs(t_val), df = df_res)
  }

  list(
    available = TRUE,
    tCritical = finite_number(t_crit),
    boundaries = as.list(as.numeric(boundaries)),
    grid = list(
      wValues = as.list(as.numeric(w_grid)),
      simpleSlopes = as.list(as.numeric(slopes)),
      standardErrors = as.list(as.numeric(se_slopes)),
      pValues = as.list(as.numeric(p_values))
    )
  )
}
