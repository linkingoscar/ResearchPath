# 独立加载（测试/复用）时引导 seed 工具；入口脚本已先行 source。
if (!exists("researchpath_seed", mode = "function", inherits = TRUE)) {
  if (file.exists(file.path("engine", "R", "lib", "seed_utils.R"))) {
    source(file.path("engine", "R", "lib", "seed_utils.R"))
  }
}
if (!exists("researchpath_validate_confidence_level", mode = "function", inherits = TRUE)) {
  researchpath_validate_confidence_level <- function(value, label = "confidenceLevel") {
    level <- suppressWarnings(as.numeric(value))
    if (length(level) != 1L || !is.finite(level) || level <= 0.5 || level >= 1) {
      stop(sprintf("%s 必须位于 (0.5, 1.0) 区间", label), call. = FALSE)
    }
    level
  }
}

estimate_htmt_item_correlations <- function(df, item_ids, correlation_type = "pearson") {
  item_frame <- df[, item_ids, drop = FALSE]
  if (identical(correlation_type, "polychoric")) {
    if (!requireNamespace("lavaan", quietly = TRUE)) {
      stop("HTMT_POLYCHORIC_REQUIRES_LAVAAN")
    }
    return(unclass(lavaan::lavCor(item_frame, ordered = item_ids)))
  }
  if (!identical(correlation_type, "pearson")) {
    stop("HTMT_UNSUPPORTED_CORRELATION_TYPE")
  }
  cor(item_frame, use = "pairwise.complete.obs")
}

calc_htmt_matrix <- function(df, constructs_metadata, correlation_type = "pearson") {
  k <- length(constructs_metadata)
  mat <- matrix(NA_real_, k, k)
  item_sets <- lapply(constructs_metadata, function(construct) {
    intersect(unlist(construct$itemIds), names(df))
  })
  all_items <- unique(unlist(item_sets, use.names = FALSE))
  item_correlations <- if (length(all_items) >= 2L) {
    abs(estimate_htmt_item_correlations(df, all_items, correlation_type))
  } else {
    matrix(1.0, nrow = length(all_items), ncol = length(all_items), dimnames = list(all_items, all_items))
  }
  for (i in seq_len(k)) {
    for (j in i:k) {
      if (i == j) {
        mat[i, j] <- 1.0
        next
      }
      left_ids <- item_sets[[i]]
      right_ids <- item_sets[[j]]
      if (length(left_ids) == 0 || length(right_ids) == 0) next

      cross <- item_correlations[left_ids, right_ids, drop = FALSE]
      left_cor <- item_correlations[left_ids, left_ids, drop = FALSE]
      right_cor <- item_correlations[right_ids, right_ids, drop = FALSE]
      left_within <- if (length(left_ids) >= 2) left_cor[upper.tri(left_cor)] else 1.0
      right_within <- if (length(right_ids) >= 2) right_cor[upper.tri(right_cor)] else 1.0
      val <- mean(cross) / sqrt(mean(left_within) * mean(right_within))
      mat[i, j] <- val
      mat[j, i] <- val
    }
  }
  mat
}

researchpath_make_htmt_callback <- function(df, constructs_metadata, k, correlation_type) {
  calculator <- calc_htmt_matrix
  callback_environment <- list2env(
    list(
      df = df,
      constructs_metadata = constructs_metadata,
      k = k,
      correlation_type = correlation_type,
      estimate_htmt_item_correlations = estimate_htmt_item_correlations,
      n = nrow(df),
      researchpath_seed = researchpath_seed
    ),
    parent = globalenv()
  )
  environment(calculator) <- callback_environment
  callback_environment$calculator <- calculator
  eval(quote(function(replicate_seed) {
    set.seed(researchpath_seed(replicate_seed))
    indices <- sample.int(n, n, replace = TRUE)
    tryCatch(
      calculator(df[indices, , drop = FALSE], constructs_metadata, correlation_type),
      error = function(error) matrix(NA_real_, k, k)
    )
  }), envir = callback_environment)
}

htmt_bootstrap <- function(
  df,
  constructs_metadata,
  reps = 500,
  seed = 20260714,
  correlation_type = "pearson",
  confidence_level = 0.95
) {
  confidence_level <- researchpath_validate_confidence_level(confidence_level)
  k <- length(constructs_metadata)
  researchpath_budget_htmt(nrow(df), ncol(df), k, reps)
  boot_values <- array(NA_real_, dim = c(reps, k, k))
  n <- nrow(df)
  set.seed(researchpath_seed(seed))
  profile <- researchpath_parallel_profile(reps)
  work_units <- as.double(reps) * as.double(n) * as.double(max(1L, ncol(df))^2)
  if (!researchpath_use_parallel(work_units, reps)) {
    profile$backend <- "sequential"
    profile$workers <- 1L
  }
  replicate_seeds <- sample.int(.Machine$integer.max, reps, replace = TRUE)
  samples_per_batch <- min(reps, 5000L)
  chunks <- researchpath_parallel_chunks(
    reps,
    1L,
    tasks_per_worker = samples_per_batch
  )
  for (chunk in chunks) {
    chunk_values <- researchpath_parallel_grouped_lapply(
      as.list(replicate_seeds[chunk]),
      researchpath_make_htmt_callback(df, constructs_metadata, k, correlation_type),
      profile$workers
    )
    for (offset in seq_along(chunk)) {
      boot_values[chunk[[offset]], , ] <- chunk_values[[offset]]
    }
  }
  
  ci_lower <- matrix(NA_real_, k, k)
  ci_upper <- matrix(NA_real_, k, k)
  dropped_replications <- 0L
  affected_pairs <- 0L
  
  for (i in seq_len(k)) {
    for (j in seq_len(k)) {
      if (i == j) {
        ci_lower[i, j] <- 1.0
        ci_upper[i, j] <- 1.0
        next
      }
      vals <- boot_values[, i, j]
      vals <- vals[!is.na(vals) & is.finite(vals)]
      dropped <- reps - length(vals)
      if (dropped > 0L) {
        dropped_replications <- dropped_replications + as.integer(dropped)
        affected_pairs <- affected_pairs + 1L
      }
      if (length(vals) >= 10) {
        ci <- quantile(vals, probs = c((1 - confidence_level) / 2, 1 - (1 - confidence_level) / 2), type = 7)
        ci_lower[i, j] <- ci[[1]]
        ci_upper[i, j] <- ci[[2]]
      }
    }
  }
  list(
    lower = ci_lower,
    upper = ci_upper,
    confidenceLevel = confidence_level,
    confidenceIntervalMethod = "bootstrap_percentile",
    replicates = as.integer(reps),
    invalidReplicationCount = dropped_replications,
    affectedPairs = affected_pairs,
    seed = researchpath_seed(seed),
    parallelBackend = profile$backend,
    parallelWorkers = as.integer(profile$workers),
    rngStrategy = profile$rngStrategy
  )
}

mat_to_list <- function(mat) {
  lapply(seq_len(nrow(mat)), function(i) {
    as.list(as.numeric(mat[i, ]))
  })
}

calc_spearman_brown <- function(r) {
  if (!is.finite(r)) return(NA_real_)
  denominator <- 1 + r
  if (abs(denominator) <= .Machine$double.eps) return(NA_real_)
  as.numeric(2 * r / denominator)
}

calc_ordinal_reliability <- function(df, item_ids) {
  if (length(item_ids) < 2) {
    return(list(alpha = NA_real_, ordinalAlpha = NA_real_, omega = NA_real_,
                ordinalOmega = NA_real_, method = "insufficient_items"))
  }
  sub_df <- df[, item_ids, drop = FALSE]
  sub_df <- sub_df[complete.cases(sub_df), , drop = FALSE]
  k <- ncol(sub_df)
  if (nrow(sub_df) < 5 || k < 2) {
    return(list(alpha = NA_real_, ordinalAlpha = NA_real_, omega = NA_real_,
                ordinalOmega = NA_real_, method = "insufficient_observations"))
  }

  pearson_cor <- tryCatch(cor(sub_df, use = "pairwise.complete.obs"), error = function(e) NULL)
  calc_alpha_from_cor <- function(R, p) {
    if (is.null(R) || isTRUE(any(is.na(R)))) return(NA_real_)
    sum_r <- sum(R, na.rm = TRUE)
    if (is.na(sum_r) || sum_r <= 0) return(NA_real_)
    as.numeric((p / (p - 1)) * (1 - p / sum_r))
  }
  alpha <- calc_alpha_from_cor(pearson_cor, k)

  poly_error <- NULL
  ordinal_eligible <- all(vapply(sub_df, function(values) {
    numeric_values <- suppressWarnings(as.numeric(values))
    unique_count <- length(unique(numeric_values))
    all(is.finite(numeric_values)) &&
      unique_count >= 2L &&
      unique_count <= 12L &&
      all(abs(numeric_values - round(numeric_values)) <= sqrt(.Machine$double.eps))
  }, logical(1)))
  poly_cor <- if (ordinal_eligible) {
    tryCatch({
      if (requireNamespace("lavaan", quietly = TRUE)) {
        unclass(lavaan::lavCor(sub_df, ordered = names(sub_df)))
      } else {
        stop("lavaan package is required for polychoric reliability")
      }
    }, error = function(e) {
      poly_error <<- conditionMessage(e)
      NULL
    })
  } else {
    poly_error <- "ORDINAL_RELIABILITY_REQUIRES_INTEGER_ORDERED_CATEGORIES_UP_TO_12_LEVELS"
    NULL
  }

  ordinal_alpha <- calc_alpha_from_cor(poly_cor, k)

  # Two-item scales: use Spearman-Brown instead of omega (unidentified with k<3)
  if (k == 2) {
    r_pearson <- if (!is.null(pearson_cor)) pearson_cor[1, 2] else NA_real_
    r_poly <- if (!is.null(poly_cor)) poly_cor[1, 2] else NA_real_
    return(list(
      alpha = if (is.finite(alpha)) alpha else NA_real_,
      ordinalAlpha = if (is.finite(ordinal_alpha)) ordinal_alpha else NA_real_,
      omega = NA_real_,
      ordinalOmega = NA_real_,
      spearmanBrown = calc_spearman_brown(r_pearson),
      ordinalSpearmanBrown = calc_spearman_brown(r_poly),
      method = "spearman_brown_standard_2r_over_1_plus_r",
      reliabilityWarning = if (is.finite(r_pearson) && r_pearson <= 0) {
        "TWO_ITEM_NONPOSITIVE_CORRELATION_REQUIRES_CODING_REVIEW"
      } else {
        NULL
      },
      ordinalReliabilityAvailable = !is.null(poly_cor),
      ordinalReliabilityReason = poly_error
    ))
  }

  calc_omega_from_cor <- function(R, n_obs) {
    if (is.null(R) || isTRUE(any(is.na(R)))) return(NA_real_)
    if (!requireNamespace("psych", quietly = TRUE)) return(NA_real_)
    fit <- tryCatch(
      psych::fa(
        r = R,
        nfactors = 1L,
        n.obs = n_obs,
        fm = "minres",
        rotate = "none",
        warnings = FALSE
      ),
      error = function(error) NULL
    )
    if (is.null(fit) || is.null(fit$loadings) || is.null(fit$uniquenesses)) return(NA_real_)
    loadings <- as.numeric(unclass(fit$loadings)[, 1])
    if (isTRUE(sum(loadings) < 0)) loadings <- -loadings
    uniquenesses <- as.numeric(fit$uniquenesses)
    if (any(!is.finite(loadings)) || any(!is.finite(uniquenesses))) return(NA_real_)
    common_score_variance <- sum(loadings)^2
    denominator <- common_score_variance + sum(uniquenesses)
    if (!is.finite(denominator) || denominator <= 0) return(NA_real_)
    as.numeric(common_score_variance / denominator)
  }

  omega <- calc_omega_from_cor(pearson_cor, nrow(sub_df))
  ordinal_omega <- calc_omega_from_cor(poly_cor, nrow(sub_df))

  list(
    alpha = if (is.finite(alpha)) alpha else NA_real_,
    ordinalAlpha = if (is.finite(ordinal_alpha)) ordinal_alpha else NA_real_,
    omega = if (is.finite(omega)) omega else NA_real_,
    ordinalOmega = if (is.finite(ordinal_omega)) ordinal_omega else NA_real_,
    method = "one_factor_minres_omega_total",
    omegaMethod = "common_factor_minres_loadings_and_uniquenesses",
    ordinalOmegaMethod = if (!is.null(poly_cor)) {
      "polychoric_common_factor_minres_loadings_and_uniquenesses"
    } else {
      NULL
    },
    ordinalReliabilityAvailable = !is.null(poly_cor),
    ordinalReliabilityReason = poly_error
  )
}

calc_item_diagnostics <- function(df, item_ids) {
  sub_df <- df[, item_ids, drop = FALSE]
  sub_df <- sub_df[complete.cases(sub_df), , drop = FALSE]
  k <- ncol(sub_df)
  if (nrow(sub_df) < 5 || k < 2) return(list())

  lapply(seq_along(item_ids), function(i) {
    item_id <- item_ids[i]
    other_ids <- item_ids[-i]
    other_items <- sub_df[, other_ids, drop = FALSE]
    corrected_total <- rowSums(other_items)
    citc <- tryCatch(
      cor(sub_df[[item_id]], corrected_total, use = "pairwise.complete.obs"),
      error = function(e) NA_real_
    )
    alpha_if_deleted <- if (length(other_ids) >= 2) {
      r <- calc_ordinal_reliability(sub_df, other_ids)
      r$alpha
    } else NA_real_
    omega_if_deleted <- if (length(other_ids) >= 3) {
      r <- calc_ordinal_reliability(sub_df, other_ids)
      r$omega
    } else NA_real_
    list(
      itemId = item_id,
      correctedItemTotalCorrelation = finite_number(citc),
      alphaIfDeleted = finite_number(alpha_if_deleted),
      omegaIfDeleted = finite_number(omega_if_deleted)
    )
  })
}

calc_structural_missingness <- function(df, constructs_metadata) {
  result <- list()
  for (construct in constructs_metadata) {
    items <- intersect(unlist(construct$itemIds), names(df))
    if (length(items) == 0) next
    sub_df <- df[, items, drop = FALSE]
    missing_counts <- rowSums(is.na(sub_df))
    all_missing_rows <- sum(missing_counts == length(items))
    partial_missing_rows <- sum(missing_counts > 0 & missing_counts < length(items))
    complete_rows <- sum(missing_counts == 0)
    result[[construct$id]] <- list(
      constructId = construct$id,
      totalRows = nrow(df),
      completeRows = as.integer(complete_rows),
      structurallyMissingRows = as.integer(all_missing_rows),
      itemLevelMissingRows = as.integer(partial_missing_rows),
      structuralMissingRate = if (nrow(df) > 0) all_missing_rows / nrow(df) else 0.0
    )
  }
  result
}

# ---------------------------------------------------------------------------
# Correlation CIs & Partial Correlations
# ---------------------------------------------------------------------------

calc_correlation_ci <- function(r, n, confidence_level = 0.95) {
  if (!is.finite(r) || !is.finite(n) || n <= 3 || abs(r) >= 1.0) {
    return(list(lower = NA_real_, upper = NA_real_))
  }
  z <- 0.5 * log((1 + r) / (1 - r))
  se <- 1 / sqrt(n - 3)
  z_crit <- qnorm(1 - (1 - confidence_level) / 2)
  z_lower <- z - z_crit * se
  z_upper <- z + z_crit * se
  list(
    lower = finite_number(tanh(z_lower)),
    upper = finite_number(tanh(z_upper))
  )
}

calc_correlation_matrix_with_ci <- function(df, method = "pearson", confidence_level = 0.95) {
  p <- ncol(df)
  col_names <- names(df)
  cor_mat <- matrix(NA_real_, p, p, dimnames = list(col_names, col_names))
  ci_lower <- matrix(NA_real_, p, p, dimnames = list(col_names, col_names))
  ci_upper <- matrix(NA_real_, p, p, dimnames = list(col_names, col_names))
  p_mat <- matrix(NA_real_, p, p, dimnames = list(col_names, col_names))

  for (i in seq_len(p)) {
    for (j in seq_len(p)) {
      if (i == j) {
        cor_mat[i, j] <- 1.0
        ci_lower[i, j] <- 1.0
        ci_upper[i, j] <- 1.0
        p_mat[i, j] <- 0.0
        next
      }
      valid <- complete.cases(df[[i]], df[[j]])
      x <- df[[i]][valid]
      y <- df[[j]][valid]
      n <- length(x)
      if (n < 4) next

      ct <- tryCatch(cor.test(x, y, method = method, conf.level = confidence_level), error = function(e) NULL)
      if (!is.null(ct)) {
        r <- as.numeric(ct$estimate)
        cor_mat[i, j] <- r
        p_mat[i, j] <- as.numeric(ct$p.value)
        if (!is.null(ct$conf.int)) {
          ci_lower[i, j] <- as.numeric(ct$conf.int[1])
          ci_upper[i, j] <- as.numeric(ct$conf.int[2])
        } else {
          ci_bounds <- calc_correlation_ci(r, n, confidence_level)
          ci_lower[i, j] <- ci_bounds$lower
          ci_upper[i, j] <- ci_bounds$upper
        }
      }
    }
  }

  list(
    coefficients = mat_to_list(cor_mat),
    pValues = mat_to_list(p_mat),
    ciLower = mat_to_list(ci_lower),
    ciUpper = mat_to_list(ci_upper)
  )
}

calc_partial_correlation <- function(df, x_var, y_var, z_vars, confidence_level = 0.95) {
  all_vars <- unique(c(x_var, y_var, z_vars))
  valid_df <- df[complete.cases(df[, all_vars, drop = FALSE]), all_vars, drop = FALSE]
  n <- nrow(valid_df)
  k_z <- length(z_vars)
  if (n <= k_z + 3) {
    return(list(available = FALSE, reason = "更正缺失案例后样本量不足"))
  }

  # Residualize X and Y with respect to Z
  f_x <- as.formula(paste(x_var, "~", paste(z_vars, collapse = " + ")))
  f_y <- as.formula(paste(y_var, "~", paste(z_vars, collapse = " + ")))
  res_x <- residuals(lm(f_x, data = valid_df))
  res_y <- residuals(lm(f_y, data = valid_df))

  r_part <- cor(res_x, res_y)
  deg_f <- n - k_z - 2
  t_stat <- r_part * sqrt(deg_f / (1 - r_part^2))
  p_val <- 2 * pt(-abs(t_stat), df = deg_f)

  ci_bounds <- calc_correlation_ci(r_part, n - k_z, confidence_level)

  list(
    available = TRUE,
    estimate = finite_number(r_part),
    statistic = finite_number(t_stat),
    degreesOfFreedom = as.integer(deg_f),
    pValue = finite_number(p_val),
    ciLower = ci_bounds$lower,
    ciUpper = ci_bounds$upper,
    controlVariables = as.list(z_vars),
    sampleSize = as.integer(n)
  )
}
