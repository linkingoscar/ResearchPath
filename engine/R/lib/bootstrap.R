# 独立加载（测试/复用）时引导 seed 工具；入口脚本已先行 source。
if (!exists("researchpath_seed", mode = "function", inherits = TRUE)) {
  if (file.exists(file.path("engine", "R", "lib", "seed_utils.R"))) {
    source(file.path("engine", "R", "lib", "seed_utils.R"))
  }
}

bootstrap_ci <- function(values, original_estimate) {
  valid <- values[is.finite(values)]
  if (length(valid) < floor(replicates * 0.95)) {
    stop(
      "BOOTSTRAP_REPLICATION_LOSS_EXCEEDS_LIMIT: ", length(values) - length(valid),
      " of ", length(values), " bootstrap replications failed (>5%), refusing to report intervals"
    )
  }
  method <- bootstrap_config$method
  if (identical(method, "bias_corrected")) {
    # Bias-corrected (BC) percentile interval: z0 bias correction ONLY,
    # WITHOUT jackknife acceleration.  This is NOT BCa -- the engine does not
    # implement acceleration anywhere.  BCa intervals in the repository exist
    # only inside official PROCESS macro oracle reference fixtures.
    prop <- sum(valid < original_estimate) / length(valid)
    prop <- max(min(prop, 1 - 1e-12), 1e-12)
    z0 <- qnorm(prop)
    
    z_lower <- qnorm(alpha / 2)
    z_upper <- qnorm(1 - alpha / 2)
    
    p_lower <- pnorm(2 * z0 + z_lower)
    p_upper <- pnorm(2 * z0 + z_upper)
    
    bounds <- unname(quantile(valid, probs = c(p_lower, p_upper), type = 7, names = FALSE))
    method_name <- "bootstrap_bias_corrected"
  } else {
    bounds <- unname(quantile(valid, probs = c(alpha / 2, 1 - alpha / 2), type = 7, names = FALSE))
    method_name <- "bootstrap_percentile"
  }
  list(
    values = valid,
    lower = bounds[[1]],
    upper = bounds[[2]],
    method = method_name,
    invalidReplicationCount = as.integer(length(values) - length(valid))
  )
}

researchpath_make_bootstrap_callback <- function(designs, context) {
  callback_environment <- list2env(
    list(designs = designs, context = context, researchpath_seed = researchpath_seed),
    parent = globalenv()
  )
  eval(quote(function(replicate_seed) {
    tryCatch({
      set.seed(researchpath_seed(replicate_seed))
      indices <- sample.int(
        context$sampleSize,
        context$sampleSize,
        replace = TRUE
      )
      fitted <- lapply(designs, function(design) {
        x <- design$x[indices, , drop = FALSE]
        y <- design$y[indices]
        if (isTRUE(design$binary)) {
          fit <- suppressWarnings(stats::glm.fit(
            x = x,
            y = y,
            family = stats::binomial(link = "logit")
          ))
          if (!isTRUE(fit$converged) || any(!is.finite(fit$coefficients))) {
            stop("invalid bootstrap logistic fit")
          }
          fit$coefficients
        } else {
          stats::lm.fit(x = x, y = y)$coefficients
        }
      })
      coefficient <- function(equation, term) {
        unname(fitted[[equation]][[term]])
      }

      if (identical(context$template, "model_6")) {
        sa1 <- coefficient("m1", context$xId)
        sa2 <- coefficient("m2", context$xId)
        serial_path <- coefficient("m2", context$m1Id)
        sb1 <- coefficient("y", context$m1Id)
        sb2 <- coefficient("y", context$m2Id)
        indirect_1 <- sa1 * sb1
        indirect_2 <- sa2 * sb2
        indirect_3 <- sa1 * serial_path * sb2
        return(c(
          indirect_1,
          indirect_2,
          indirect_3,
          indirect_1 + indirect_2 + indirect_3
        ))
      }

      sa <- coefficient("m", context$xId)
      sb <- coefficient("y", context$mId)
      if (context$template %in% c("model_4", "model_5")) return(sa * sb)
      if (context$template %in% c("model_21", "model_22")) {
        sa3 <- coefficient("m", context$aInteractionTerm)
        sb3 <- coefficient("y", context$bInteractionTerm)
        return(
          (sa + sa3 * context$representativeA) *
            (sb + sb3 * context$representativeB)
        )
      }
      if (context$template %in% c("model_58", "model_59")) {
        sa3 <- coefficient("m", context$aInteractionTerm)
        sb3 <- coefficient("y", context$bInteractionTerm)
        return(
          (sa + sa3 * context$representative) *
            (sb + sb3 * context$representative)
        )
      }
      interaction <- coefficient(context$interactionEquation, context$interactionTerm)
      if (context$interactionEquation == "m") {
        conditional <- (sa + interaction * context$representative) * sb
        index <- interaction * sb
      } else {
        conditional <- sa * (sb + interaction * context$representative)
        index <- sa * interaction
      }
      c(conditional, index)
    }, error = function(error) rep(NA_real_, context$outputColumns))
  }), envir = callback_environment)
}
