# 独立加载（测试/复用）时引导 seed 工具；入口脚本已先行 source。
if (!exists("researchpath_seed", mode = "function", inherits = TRUE)) {
  if (file.exists(file.path("engine", "R", "lib", "seed_utils.R"))) {
    source(file.path("engine", "R", "lib", "seed_utils.R"))
  }
}
efa_lib_dir <- if (exists("script_dir", mode = "character", inherits = TRUE) && nzchar(script_dir)) {
  file.path(script_dir, "lib")
} else if (nzchar(Sys.getenv("RESEARCHPATH_PROJECT_ROOT"))) {
  file.path(Sys.getenv("RESEARCHPATH_PROJECT_ROOT"), "engine", "R", "lib")
} else {
  file.path("engine", "R", "lib")
}
source(file.path(efa_lib_dir, "efa_helpers.R"), local = environment())

# Parallel analysis replicate callback. `simulation` draws one
# null-hypothesis dataset (continuous normal or threshold-preserving ordinal)
# and `eigenvalue_function` maps it to eigenvalues in the SAME correlation
# world as the observed data (Pearson or polychoric), so the null distribution
# never silently mixes correlation worlds. A failed replicate (for example an
# ordinal column collapsing to a single category on a small sample) retries
# with a salted seed; the caller detects any residual NA row and reports the
# whole PA as unavailable instead of degrading to Pearson.
researchpath_make_parallel_analysis_callback <- function(n, p, simulation, eigenvalue_function) {
  callback_environment <- list2env(
    list(
      n = n,
      p = p,
      simulation = simulation,
      eigenvalue_function = eigenvalue_function,
      researchpath_seed = researchpath_seed
    ),
    parent = globalenv()
  )
  eval(quote(function(replicate_seed) {
    for (attempt in seq_len(5L)) {
      set.seed(researchpath_seed(replicate_seed, salt = attempt - 1L))
      random_data <- simulation()
      values <- tryCatch(
        eigenvalue_function(random_data),
        error = function(e) NULL
      )
      if (!is.null(values) && length(values) == p) {
        return(as.numeric(values))
      }
    }
    rep(NA_real_, p)
  }), envir = callback_environment)
}

# Structured numerical-fallback disclosure. Any fallback that changes
# the numerical meaning of an estimator must surface in the result document as
# {stage, requested, used, reason}, never only in a log line. The collector is
# an environment so recording works from nested closures (tryCatch handlers,
# substitute functions) without `<<-` frame confusion.
new_numerical_fallbacks <- function() {
  store <- new.env(parent = emptyenv())
  store$entries <- list()
  store
}

record_numerical_fallback <- function(fallbacks, stage, requested, used, reason) {
  fallbacks$entries[[length(fallbacks$entries) + 1L]] <- list(
    stage = stage,
    requested = requested,
    used = used,
    reason = reason
  )
  invisible(fallbacks)
}

numerical_fallbacks_list <- function(fallbacks) fallbacks$entries

run_parallel_analysis <- function(data, iterations = 1000, seed = 20260714,
                                  correlation_type = "pearson") {
  n <- nrow(data)
  p <- ncol(data)
  researchpath_budget_parallel_analysis(n, p, iterations)
  ordinal <- identical(correlation_type, "polychoric")
  if (!ordinal && !identical(correlation_type, "pearson")) {
    stop(paste0("MEASUREMENT_EFA_UNKNOWN_CORRELATION_TYPE: ", correlation_type))
  }
  simulation_type <- if (ordinal) "ordinal_threshold_preserving" else "continuous_pearson"
  metadata <- list(
    iterations = as.integer(iterations),
    seed = researchpath_seed(seed),
    quantile = 0.95,
    correlationType = correlation_type,
    simulationType = simulation_type
  )
  if (ordinal && !requireNamespace("lavaan", quietly = TRUE)) {
    return(c(
      list(available = FALSE, reason = "unsupported_for_ordinal_correlation"),
      metadata
    ))
  }

  # Observed eigenvalues in the user's correlation world. Ordinal PA never
  # falls back to Pearson eigenvalues: if polychoric estimation fails, PA is
  # reported as unavailable with a machine-readable reason.
  sample_ev <- if (ordinal) {
    tryCatch(
      eigen(
        unclass(lavaan::lavCor(as.data.frame(data), ordered = colnames(data))),
        symmetric = TRUE,
        only.values = TRUE
      )$values,
      error = function(e) NULL
    )
  } else {
    eigen(cor(data, use = "pairwise.complete.obs"), symmetric = TRUE, only.values = TRUE)$values
  }
  if (is.null(sample_ev) || length(sample_ev) != p) {
    return(c(
      list(available = FALSE, reason = "unsupported_for_ordinal_correlation"),
      metadata
    ))
  }

  # Threshold-preserving ordinal simulation: keep each item's category values,
  # estimate normal-theory thresholds from the observed marginal proportions,
  # draw independent latent normals under the null, discretize through the
  # thresholds, then evaluate polychoric eigenvalues in the same world as the
  # observed matrix.
  simulation <- NULL
  eigenvalue_function <- NULL
  if (ordinal) {
    category_values <- lapply(seq_len(p), function(j) {
      column <- data[, j]
      sort(unique(column[is.finite(column)]))
    })
    thresholds <- lapply(seq_len(p), function(j) {
      column <- data[, j]
      valid <- column[is.finite(column)]
      counts <- as.numeric(table(valid))
      cumulative <- cumsum(counts) / sum(counts)
      qnorm(cumulative[-length(cumulative)])
    })
    simulation <- function() {
      latent <- matrix(rnorm(n * p), nrow = n, ncol = p)
      discretized <- lapply(seq_len(p), function(j) {
        category_index <- findInterval(latent[, j], c(-Inf, thresholds[[j]], Inf))
        category_values[[j]][category_index]
      })
      as.data.frame(
        discretized,
        col.names = colnames(data),
        stringsAsFactors = FALSE
      )
    }
    eigenvalue_function <- function(d) {
      eigen(
        unclass(lavaan::lavCor(d, ordered = colnames(d))),
        symmetric = TRUE,
        only.values = TRUE
      )$values
    }
  } else {
    simulation <- function() matrix(rnorm(n * p), nrow = n, ncol = p)
    eigenvalue_function <- function(d) {
      eigen(stats::cor(d), symmetric = TRUE, only.values = TRUE)$values
    }
  }

  set.seed(researchpath_seed(seed))
  sim_evs <- matrix(0, nrow = iterations, ncol = p)
  profile <- researchpath_parallel_profile(iterations)
  work_units <- as.double(iterations) * as.double(n) * as.double(p) * as.double(p)
  if (!researchpath_use_parallel(work_units, iterations)) {
    profile$backend <- "sequential"
    profile$workers <- 1L
  }
  replicate_seeds <- sample.int(.Machine$integer.max, iterations, replace = TRUE)
  simulations_per_batch <- min(iterations, 5000L)
  chunks <- researchpath_parallel_chunks(
    iterations,
    1L,
    tasks_per_worker = simulations_per_batch
  )
  for (chunk in chunks) {
    chunk_values <- researchpath_parallel_grouped_lapply(
      as.list(replicate_seeds[chunk]),
      researchpath_make_parallel_analysis_callback(
        n, p, simulation, eigenvalue_function
      ),
      profile$workers
    )
    sim_evs[chunk, ] <- do.call(rbind, chunk_values)
  }
  if (any(!is.finite(sim_evs))) {
    return(c(
      list(available = FALSE, reason = "polychoric_simulation_failed"),
      metadata,
      list(
        parallelBackend = profile$backend,
        parallelWorkers = as.integer(profile$workers),
        rngStrategy = profile$rngStrategy
      )
    ))
  }
  sim_ev_95 <- apply(sim_evs, 2, function(x) quantile(x, 0.95))
  recommended_factors <- sum(sample_ev > sim_ev_95)
  c(
    list(
      available = TRUE,
      reason = if (recommended_factors == 0L) "no_factor_exceeds_parallel_threshold" else NULL,
      sampleEigenvalues = as.list(as.numeric(sample_ev)),
      simulatedEigenvalues = as.list(as.numeric(sim_ev_95)),
      recommendedFactorCount = as.integer(recommended_factors)
    ),
    metadata,
    list(
      parallelBackend = profile$backend,
      parallelWorkers = as.integer(profile$workers),
      rngStrategy = profile$rngStrategy
    )
  )
}

run_split_validation <- function(data, factor_count, rotation = "promax", seed = 20260714,
                                 method = "ml", item_scale = "continuous",
                                 primary_execution = NULL) {
  n <- nrow(data)
  if (n < 20 || ncol(data) < 3) {
    return(list(available = FALSE, reason = "split_validation_not_supported_for_this_estimator"))
  }
  set.seed(researchpath_seed(seed))
  train_idx <- sample.int(n, size = floor(n / 2))
  train_data <- data[train_idx, , drop = FALSE]
  val_data <- data[-train_idx, , drop = FALSE]

  max_f <- min(factor_count, ncol(data) - 1)
  if (max_f < 1) {
    return(list(available = FALSE, reason = "split_validation_not_supported_for_this_estimator"))
  }

  # The train/holdout splits reuse the SAME model specification as the
  # full fit — same correlation method (polychoric for ordinal, Pearson for
  # continuous), same extraction method, same rotation, same item scale — via
  # the shared run_efa_with_method pipeline. A combination that cannot be
  # refit on the splits is reported as unavailable; the estimator is never
  # silently swapped.
  split_fit <- function(split_data) {
    correlation <- if (identical(item_scale, "ordinal")) {
      tryCatch(
        unclass(lavaan::lavCor(split_data, ordered = colnames(split_data))),
        error = function(e) NULL
      )
    } else {
      tryCatch(cor(split_data, use = "pairwise.complete.obs"), error = function(e) NULL)
    }
    if (is.null(correlation)) return(NULL)
    tryCatch(
      run_efa_with_method(
        data = split_data,
        correlation = correlation,
        n_obs = nrow(split_data),
        factor_count = max_f,
        method = method,
        rotation = rotation,
        item_scale = item_scale
      ),
      error = function(e) NULL
    )
  }
  fit_train <- split_fit(train_data)
  fit_val <- split_fit(val_data)
  if (is.null(fit_train) || is.null(fit_val)) {
    return(list(
      available = FALSE,
      reason = "split_validation_not_supported_for_this_estimator",
      method = method,
      correlationType = if (identical(item_scale, "ordinal")) "polychoric" else "pearson",
      extractionMethod = if (is.null(fit_train)) NULL else fit_train$extractionMethod
    ))
  }

  execution_fingerprint <- function(fit) {
    list(
      correlationType = if (!is.null(fit$executedCorrelationType)) {
        fit$executedCorrelationType
      } else if (!is.null(fit$correlationType)) {
        fit$correlationType
      } else {
        if (identical(item_scale, "ordinal")) "polychoric" else "pearson"
      },
      extractionMethod = if (!is.null(fit$executedExtractionMethod)) {
        fit$executedExtractionMethod
      } else if (!is.null(fit$extractionMethod)) {
        fit$extractionMethod
      } else {
        method
      },
      rotation = if (!is.null(fit$executedRotation)) fit$executedRotation else rotation,
      factorCount = if (!is.null(fit$factorCount)) as.integer(fit$factorCount) else as.integer(max_f)
    )
  }
  execution_fingerprints <- list(
    primary = if (is.null(primary_execution)) NULL else execution_fingerprint(primary_execution),
    train = execution_fingerprint(fit_train),
    holdout = execution_fingerprint(fit_val)
  )
  comparable_fingerprints <- Filter(Negate(is.null), execution_fingerprints)
  execution_matches <- all(vapply(
    comparable_fingerprints[-1L],
    function(fingerprint) identical(fingerprint, comparable_fingerprints[[1L]]),
    logical(1)
  ))

  numerical_fallbacks <- c(
    fit_train$numericalFallbacks,
    fit_val$numericalFallbacks
  )
  if (!execution_matches) {
    return(list(
      available = FALSE,
      reason = "split_validation_execution_mismatch",
      method = method,
      requestedCorrelationType = if (identical(item_scale, "ordinal")) "polychoric" else "pearson",
      requestedExtractionMethod = method,
      requestedRotation = rotation,
      executionFingerprints = execution_fingerprints,
      numericalFallbacks = numerical_fallbacks
    ))
  }

  loadings_train <- fit_train$loadings
  loadings_val <- fit_val$loadings
  congruence <- NA_real_
  if (ncol(loadings_train) >= 1 && ncol(loadings_val) >= 1) {
    # Tucker's congruence coefficient for the primary factor
    u <- loadings_train[, 1]
    v <- loadings_val[, 1]
    congruence <- sum(u * v) / sqrt(sum(u^2) * sum(v^2))
  }

  list(
    available = TRUE,
    trainSampleCount = length(train_idx),
    validationSampleCount = n - length(train_idx),
    method = method,
    correlationType = execution_fingerprints$train$correlationType,
    extractionMethod = execution_fingerprints$train$extractionMethod,
    rotation = execution_fingerprints$train$rotation,
    requestedCorrelationType = if (identical(item_scale, "ordinal")) "polychoric" else "pearson",
    executedCorrelationType = execution_fingerprints$train$correlationType,
    requestedExtractionMethod = method,
    executedExtractionMethod = execution_fingerprints$train$extractionMethod,
    requestedRotation = rotation,
    executedRotation = execution_fingerprints$train$rotation,
    executionFingerprints = execution_fingerprints,
    tuckerCongruence = if (is.finite(congruence)) congruence else NA_real_,
    numericalFallbacks = numerical_fallbacks
  )
}

# ---------------------------------------------------------------------------
# Unified EFA entry point supporting ML, PAF and MINRES
# ---------------------------------------------------------------------------

run_efa_with_method <- function(data, correlation, n_obs, factor_count, method = "ml",
                                 rotation = "promax", item_scale = "continuous") {
  p <- ncol(correlation)
  if (factor_count < 1 || factor_count >= p) {
    stop("MEASUREMENT_EFA_INVALID_FACTOR_COUNT")
  }
  fallbacks <- new_numerical_fallbacks()
  requested_correlation_type <- if (identical(item_scale, "ordinal")) "polychoric" else "pearson"
  executed_correlation_type <- requested_correlation_type

  # Determine appropriate correlation matrix (a correlation-world
  # fallback is disclosed as a structured numerical fallback, never silent).
  cor_matrix <- if (identical(item_scale, "ordinal")) {
    if (requireNamespace("lavaan", quietly = TRUE)) {
      tryCatch(
        unclass(lavaan::lavCor(data, ordered = colnames(data))),
        error = function(e) {
          executed_correlation_type <<- "pearson"
          record_numerical_fallback(
            fallbacks, "correlation", "polychoric", "pearson",
            "polychoric estimation failed; used Pearson correlation"
          )
          correlation
        }
      )
    } else {
      executed_correlation_type <- "pearson"
      record_numerical_fallback(
        fallbacks, "correlation", "polychoric", "pearson",
        "lavaan unavailable; used Pearson correlation"
      )
      correlation
    }
  } else {
    correlation
  }
  cor_type <- executed_correlation_type

  loading_matrix <- NULL
  factor_correlations <- NULL
  extraction_used <- method
  executed_extraction_method <- method

  if (identical(method, "ml")) {
    fit <- tryCatch(
      stats::factanal(covmat = cor_matrix, factors = factor_count,
                      n.obs = n_obs, rotation = rotation),
      error = function(e) NULL
    )
    if (is.null(fit)) stop("MEASUREMENT_EFA_ESTIMATION_FAILED")
    loading_matrix <- unclass(fit$loadings)
    if (identical(rotation, "promax") && !is.null(fit$rotmat)) {
      factor_correlations <- tryCatch(
        cov2cor(solve(t(fit$rotmat) %*% fit$rotmat)),
        error = function(e) {
          record_numerical_fallback(
            fallbacks, "factor_correlation", "promax_rotmat", "identity",
            "rotation matrix inversion failed; factor correlations set to identity"
          )
          diag(factor_count)
        }
      )
    } else {
      factor_correlations <- diag(factor_count)
    }
  } else if (identical(method, "paf")) {
    paf_result <- run_paf(cor_matrix, factor_count, rotation, fallbacks = fallbacks)
    loading_matrix <- paf_result$loadings
    factor_correlations <- paf_result$factorCorrelations
    extraction_used <- "paf"
  } else if (identical(method, "minres")) {
    paf_fallback <- function() {
      paf_result <- run_paf(cor_matrix, factor_count, rotation, fallbacks = fallbacks)
      record_numerical_fallback(
        fallbacks, "extraction", "minres", "paf",
        "minres extraction failed or psych unavailable; used principal axis factoring"
      )
      list(
        loadings = paf_result$loadings,
        factorCorrelations = paf_result$factorCorrelations
      )
    }
    if (requireNamespace("psych", quietly = TRUE)) {
      fit <- tryCatch(
        psych::fa(r = cor_matrix, nfactors = factor_count, n.obs = n_obs,
                  fm = "minres", rotate = rotation),
        error = function(e) NULL
      )
      if (!is.null(fit) && !is.null(fit$loadings)) {
        loading_matrix <- unclass(fit$loadings)
        factor_correlations <- if (!is.null(fit$Phi)) unclass(fit$Phi) else diag(factor_count)
      } else {
        substituted <- paf_fallback()
        loading_matrix <- substituted$loadings
        factor_correlations <- substituted$factorCorrelations
        extraction_used <- "paf_fallback_from_minres"
        executed_extraction_method <- "paf"
      }
    } else {
      substituted <- paf_fallback()
      loading_matrix <- substituted$loadings
      factor_correlations <- substituted$factorCorrelations
      extraction_used <- "paf_fallback_from_minres"
      executed_extraction_method <- "paf"
    }
  } else {
    stop(paste0("MEASUREMENT_EFA_UNKNOWN_METHOD: ", method))
  }

  if (is.null(loading_matrix)) stop("MEASUREMENT_EFA_ESTIMATION_FAILED")

  diagnostics <- calc_efa_diagnostics(loading_matrix, factor_correlations)
  fallback_entries <- numerical_fallbacks_list(fallbacks)
  rotation_fallbacks <- Filter(
    function(fallback) identical(fallback$stage, "rotation"),
    fallback_entries
  )
  executed_rotation <- if (length(rotation_fallbacks) > 0L) {
    rotation_fallbacks[[length(rotation_fallbacks)]]$used
  } else {
    rotation
  }

  list(
    loadings = loading_matrix,
    factorCorrelations = factor_correlations,
    extractionMethod = extraction_used,
    correlationType = cor_type,
    requestedCorrelationType = requested_correlation_type,
    executedCorrelationType = executed_correlation_type,
    requestedExtractionMethod = method,
    executedExtractionMethod = executed_extraction_method,
    requestedRotation = rotation,
    executedRotation = executed_rotation,
    factorCount = as.integer(factor_count),
    diagnostics = diagnostics,
    numericalFallbacks = fallback_entries
  )
}

# ---------------------------------------------------------------------------
# Base-R iterative Principal Axis Factoring (PAF)
# ---------------------------------------------------------------------------

run_paf <- function(R, nfactors, rotation = "promax", max_iter = 100L, tol = 1e-6,
                    fallbacks = NULL) {
  p <- ncol(R)
  if (is.null(fallbacks)) fallbacks <- new_numerical_fallbacks()
  # Initial communalities from squared multiple correlations
  inv_diag <- tryCatch(
    diag(solve(R)),
    error = function(e) {
      record_numerical_fallback(
        fallbacks, "initial_communality", "smc", "fixed_0_5",
        "correlation matrix inversion failed; SMC unavailable, used fixed 0.5 communalities"
      )
      rep(0.5, p)
    }
  )
  communalities <- pmax(1 - 1 / inv_diag, 0.05)
  communalities <- pmin(communalities, 0.99)

  loadings <- NULL
  for (iter in seq_len(max_iter)) {
    reduced <- R
    diag(reduced) <- communalities
    ev <- eigen(reduced, symmetric = TRUE)
    pos_idx <- which(ev$values > 0)
    if (length(pos_idx) < nfactors) {
      record_numerical_fallback(
        fallbacks, "factor_extraction", as.character(nfactors),
        as.character(max(1L, length(pos_idx))),
        "reduced correlation matrix had fewer positive eigenvalues than requested factors"
      )
      break
    }
    use_idx <- pos_idx[seq_len(nfactors)]
    loadings <- ev$vectors[, use_idx, drop = FALSE] %*%
      diag(sqrt(ev$values[use_idx]), nfactors, nfactors)
    new_communalities <- pmin(rowSums(loadings^2), 0.999)
    if (max(abs(new_communalities - communalities)) < tol) break
    communalities <- new_communalities
  }
  if (is.null(loadings)) stop("MEASUREMENT_EFA_PAF_EXTRACTION_FAILED")

  rownames(loadings) <- rownames(R)

  # Apply rotation (rotation failure falls back to unrotated loadings
  # and is disclosed as a structured numerical fallback).
  if (nfactors > 1 && identical(rotation, "promax")) {
    rot <- tryCatch(
      promax(loadings),
      error = function(e) {
        record_numerical_fallback(
          fallbacks, "rotation", "promax", "none",
          "promax rotation failed; used unrotated loadings"
        )
        list(loadings = loadings, rotmat = NULL)
      }
    )
    loadings <- unclass(rot$loadings)
    factor_correlations <- if (!is.null(rot$rotmat)) {
      tryCatch(
        cov2cor(solve(t(rot$rotmat) %*% rot$rotmat)),
        error = function(e) {
          record_numerical_fallback(
            fallbacks, "factor_correlation", "promax_rotmat", "identity",
            "rotation matrix inversion failed; factor correlations set to identity"
          )
          diag(nfactors)
        }
      )
    } else {
      diag(nfactors)
    }
  } else if (nfactors > 1 && identical(rotation, "varimax")) {
    rot <- tryCatch(
      varimax(loadings),
      error = function(e) {
        record_numerical_fallback(
          fallbacks, "rotation", "varimax", "none",
          "varimax rotation failed; used unrotated loadings"
        )
        list(loadings = loadings)
      }
    )
    loadings <- unclass(rot$loadings)
    factor_correlations <- diag(nfactors)
  } else {
    factor_correlations <- diag(nfactors)
  }

  list(
    loadings = loadings,
    factorCorrelations = factor_correlations,
    numericalFallbacks = numerical_fallbacks_list(fallbacks)
  )
}

# ---------------------------------------------------------------------------
# EFA diagnostics: cross-loading, complexity, communalities
# ---------------------------------------------------------------------------

calc_efa_diagnostics <- function(loadings, factor_correlations, cross_loading_threshold = 0.32) {
  p <- nrow(loadings)
  k <- ncol(loadings)

  # Communalities (oblique: use Λ Φ Λ' diagonal)
  if (!is.null(factor_correlations) && !identical(factor_correlations, diag(k))) {
    communalities <- diag(loadings %*% factor_correlations %*% t(loadings))
  } else {
    communalities <- rowSums(loadings^2)
  }
  communalities <- pmin(communalities, 1.0)

  # Cross-loading flags
  cross_loading_flags <- logical(p)
  primary_factor <- integer(p)
  for (i in seq_len(p)) {
    abs_loads <- abs(loadings[i, ])
    sorted_idx <- order(abs_loads, decreasing = TRUE)
    primary_factor[i] <- sorted_idx[1]
    if (k >= 2) {
      above_threshold <- sum(abs_loads >= cross_loading_threshold)
      cross_loading_flags[i] <- above_threshold >= 2
    }
  }

  # Hoffmann complexity index per item
  complexity <- numeric(p)
  for (i in seq_len(p)) {
    loads_sq <- loadings[i, ]^2
    sum_sq <- sum(loads_sq)
    if (sum_sq > 0) {
      complexity[i] <- sum_sq^2 / sum(loads_sq^2)
    } else {
      complexity[i] <- NA_real_
    }
  }

  item_names <- rownames(loadings)
  if (is.null(item_names)) item_names <- paste0("item_", seq_len(p))

  lapply(seq_len(p), function(i) {
    list(
      itemId = item_names[i],
      communality = finite_number(communalities[i]),
      primaryFactor = as.integer(primary_factor[i]),
      crossLoading = cross_loading_flags[i],
      complexity = finite_number(complexity[i])
    )
  })
}

# Empirical-center EFA keeps ML factor analysis as the requested method and
# exposes PCA fallback explicitly. Ordinal items enter through a polychoric
# matrix; failures are unavailable and never fall back to Pearson PCA.
fit_empirical_efa <- function(data, factor_count, rotation = "varimax",
                              factanal_runner = stats::factanal,
                              correlation_matrix = NULL, sample_size = NULL,
                              allow_pca_fallback = TRUE) {
  uses_correlation <- !is.null(correlation_matrix)
  requested_method <- paste0("maximum_likelihood_factanal_", rotation,
                             if (uses_correlation) "_polychoric" else "")
  fit_error <- NULL
  fit <- tryCatch(if (uses_correlation) {
    if (is.null(sample_size) || !is.finite(sample_size) || sample_size < 1) stop("polychoric EFA requires the complete-case sample size")
    factanal_runner(covmat = correlation_matrix, n.obs = as.integer(sample_size),
                    factors = factor_count, rotation = rotation, scores = "none")
  } else {
    factanal_runner(data, factors = factor_count, rotation = rotation, scores = "none")
  }, error = function(error) { fit_error <<- conditionMessage(error); NULL })

  factor_correlations <- NULL
  if (!is.null(fit)) {
    loading_matrix <- unclass(fit$loadings)[, seq_len(factor_count), drop = FALSE]
    promax_correlation_error <- NULL
    if (identical(rotation, "promax")) factor_correlations <- tryCatch(
      cov2cor(solve(t(fit$rotmat) %*% fit$rotmat)),
      error = function(error) { promax_correlation_error <<- conditionMessage(error); NULL })
    if (identical(rotation, "promax") && is.null(factor_correlations)) {
      return(list(available = TRUE, reason = "promax_factor_correlations_unavailable",
                  loadings = loading_matrix, factorCorrelations = NULL,
                  requestedMethod = requested_method,
                  executedMethod = paste0(requested_method, "_factor_correlations_unavailable"),
                  fallbackApplied = TRUE, fallbackCode = "PROMAX_FACTOR_CORRELATION_UNAVAILABLE",
                  fallbackReason = promax_correlation_error,
                  affectedOutputs = list("factorCorrelations", "structureMatrix"),
                  interpretationBoundary = "promax 旋转矩阵无法求逆，因子相关按不可用处理；载荷不作正交解释。"))
    }
    return(list(available = TRUE, reason = NULL, loadings = loading_matrix,
                factorCorrelations = factor_correlations, requestedMethod = requested_method,
                executedMethod = requested_method, fallbackApplied = FALSE,
                fallbackCode = NULL, fallbackReason = NULL, affectedOutputs = list(),
                interpretationBoundary = NULL))
  }

  if (uses_correlation || !isTRUE(allow_pca_fallback)) {
    execution <- unavailable_empirical_efa_execution(rotation)
    execution$requestedMethod <- requested_method
    execution$fallbackCode <- "EFA_FACTANAL_UNAVAILABLE_NO_PCA_FOR_ORDINAL"
    execution$fallbackReason <- fit_error
    execution$affectedOutputs <- list("factorLoadings", "communalities")
    execution$interpretationBoundary <- "有序题项不使用 Pearson PCA 回退；如需探索性因子结构，请使用高级工作台的 polychoric EFA 路径。"
    return(c(list(available = FALSE, reason = paste0("ordinal_polychoric_efa_failed",
      if (is.null(fit_error)) "" else paste0(": ", fit_error))), execution))
  }

  principal <- prcomp(data, center = TRUE, scale. = TRUE)
  raw_loadings <- sweep(principal$rotation[, seq_len(factor_count), drop = FALSE], 2,
                        principal$sdev[seq_len(factor_count)], "*")
  rotation_error <- NULL
  rotated_fit <- tryCatch(
    if (identical(rotation, "promax")) promax(raw_loadings) else varimax(raw_loadings),
    error = function(error) { rotation_error <<- conditionMessage(error); NULL })
  if (is.null(rotated_fit)) {
    return(list(available = TRUE, reason = "pca_rotation_failed_unrotated_loadings",
                loadings = raw_loadings, factorCorrelations = NULL,
                requestedMethod = requested_method,
                executedMethod = "principal_components_unrotated",
                fallbackApplied = TRUE, fallbackCode = "EFA_PCA_ROTATION_FAILED_UNROTATED",
                fallbackReason = rotation_error,
                affectedOutputs = list("factorCorrelations", "structureMatrix"),
                interpretationBoundary = "PCA 回退的旋转失败时只返回未旋转载荷，不伪造单位旋转矩阵。"))
  }
  loading_matrix <- unclass(rotated_fit$loadings)
  if (identical(rotation, "promax") && !is.null(rotated_fit$rotmat)) {
    factor_correlations <- tryCatch(cov2cor(solve(t(rotated_fit$rotmat) %*% rotated_fit$rotmat)),
                                    error = function(error) NULL)
  }
  list(available = TRUE, reason = NULL, loadings = loading_matrix,
       factorCorrelations = factor_correlations, requestedMethod = requested_method,
       executedMethod = paste0("principal_components_", rotation), fallbackApplied = TRUE,
       fallbackCode = "EFA_FACTANAL_FALLBACK_PCA",
       fallbackReason = if (is.null(fit_error)) "最大似然因子分析未返回可用结果" else fit_error,
       affectedOutputs = list("factorLoadings", "communalities", "factorCorrelations", "structureMatrix"),
       interpretationBoundary = "当前结果为主成分分析，不是共同因子模型；不能将其作为最大似然 EFA 的等价估计。")
}

measurement_execution_fields <- function(result) {
  result[c(
    "requestedMethod",
    "executedMethod",
    "fallbackApplied",
    "fallbackCode",
    "fallbackReason",
    "affectedOutputs",
    "interpretationBoundary"
  )]
}

unavailable_empirical_efa_execution <- function(rotation) {
  list(
    requestedMethod = paste0("maximum_likelihood_factanal_", rotation),
    executedMethod = "unavailable",
    fallbackApplied = FALSE,
    fallbackCode = NULL,
    fallbackReason = NULL,
    affectedOutputs = list(),
    interpretationBoundary = NULL
  )
}

parallel_analysis_zero_warning <- function(factor_method, result) {
  if (!identical(factor_method, "parallel_analysis") ||
      !isTRUE(result$available) ||
      !identical(result$recommendedFactorCount, 0L)) return(NULL)
  list(
    code = "PARALLEL_ANALYSIS_ZERO_FACTORS",
    severity = "warning",
    message = paste0(
      "平行分析未支持保留任何共同因子，因此未自动拟合 EFA。",
      "如仍需拟合一因子或多因子模型，请改用固定因子数并记录理论依据。"
    )
  )
}

measurement_fallback_warning <- function(execution, summary) {
  list(
    code = execution$fallbackCode,
    severity = "warning",
    message = paste0(
      summary,
      "。原因：",
      execution$fallbackReason,
      "；",
      execution$interpretationBoundary
    )
  )
}
