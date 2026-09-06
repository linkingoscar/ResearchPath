run_map_test <- function(R) {
  # MAP cannot be computed without a positive-definite correlation matrix.
  # Returning a numeric recommendation in that state would silently turn
  # "unavailable" into "1 factor". State the status explicitly.
  p <- ncol(R)
  if (is.null(p) || p <= 2) {
    return(list(
      available = FALSE,
      recommendedFactorCount = NULL,
      mapValues = NULL,
      reason = "too_few_items"
    ))
  }
  ev <- tryCatch(eigen(R, symmetric = TRUE), error = function(e) NULL)
  if (is.null(ev) || any(ev$values <= 0)) {
    return(list(
      available = FALSE,
      recommendedFactorCount = NULL,
      mapValues = NULL,
      reason = "correlation_matrix_not_positive_definite"
    ))
  }
  vectors <- ev$vectors
  values <- ev$values
  component_counts <- 0:(p - 2)
  fm <- numeric(length(component_counts))
  for (m in component_counts) {
    if (m == 0) {
      A <- R
    } else {
      loadings <- vectors[, 1:m, drop = FALSE] %*% diag(sqrt(pmax(values[1:m], 0)), m)
      A <- R - loadings %*% t(loadings)
      diag_A <- diag(A)
      diag_A[diag_A <= 0] <- 1e-8
      d <- diag(1 / sqrt(diag_A))
      A <- d %*% A %*% d
    }
    diag(A) <- 0
    fm[m + 1] <- mean(A^2)
  }
  min_idx <- which.min(fm)
  list(
    available = TRUE,
    recommendedFactorCount = as.integer(component_counts[[min_idx]]),
    componentCounts = as.list(as.integer(component_counts)),
    mapValues = as.list(as.numeric(fm))
  )
}
