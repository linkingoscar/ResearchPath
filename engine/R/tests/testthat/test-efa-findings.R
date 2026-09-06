# Regression tests for the EFA chain.
#
# Parallel analysis runs in the same correlation world as the main EFA
#        (polychoric threshold-preserving simulation for ordinal items); the
#        output carries correlationType/simulationType metadata and never
#        silently degrades to a Pearson null distribution.
# Split validation refits the user's estimator spec (correlation,
#        extraction, rotation, item scale) through the shared pipeline; an
#        unsupported combination is reported as unavailable, never swapped.
# Numerical fallbacks (inversion, communality initialization, rotation,
#        extraction, correlation) surface as structured
#        {stage, requested, used, reason} records in the result document.

source_engine("lib/runtime.R")
source_engine("lib/seed_utils.R")
source_engine("lib/parallel.R")
source_engine("lib/resource_budget.R")
source_engine("lib/efa.R")

# Keep the parallel-analysis machinery off the test worker pool: these tests
# assert reproducibility of the sequential path.
Sys.setenv(RESEARCHPATH_PARALLEL_WORKERS = "1")

efa_one_factor_fixture <- local({
  set.seed(20260807)
  latent <- rnorm(300)
  data <- as.data.frame(lapply(1:8, function(i) 0.7 * latent + rnorm(300, sd = 0.6)))
  names(data) <- paste0("item", 1:8)
  data
})

efa_ordinal_fixture <- local({
  set.seed(20260807)
  latent <- rnorm(400)
  data <- as.data.frame(lapply(1:8, function(i) {
    z <- 0.75 * latent + rnorm(400, sd = 0.7)
    as.numeric(findInterval(z, c(-2.0, -0.9, 0.2, 1.3)) + 1L)
  }))
  names(data) <- paste0("ord", 1:8)
  data
})

# ---------------------------------------------------------------------------
# Correlation-aware parallel analysis
# ---------------------------------------------------------------------------

test_that("continuous parallel analysis reports pearson metadata and is reproducible", {
  first <- run_parallel_analysis(efa_one_factor_fixture, iterations = 60, seed = 42)
  second <- run_parallel_analysis(efa_one_factor_fixture, iterations = 60, seed = 42)

  expect_true(first$available)
  expect_identical(first$correlationType, "pearson")
  expect_identical(first$simulationType, "continuous_pearson")
  expect_identical(first$quantile, 0.95)
  expect_identical(first$recommendedFactorCount, 1L)
  # Fixed seed reproducibility: identical null eigenvalue distribution.
  expect_identical(first$simulatedEigenvalues, second$simulatedEigenvalues)
  expect_identical(first$sampleEigenvalues, second$sampleEigenvalues)
})

test_that("ordinal parallel analysis uses polychoric simulation, never silent Pearson", {
  result <- run_parallel_analysis(
    efa_ordinal_fixture,
    iterations = 60,
    seed = 42,
    correlation_type = "polychoric"
  )

  expect_true(result$available)
  expect_identical(result$correlationType, "polychoric")
  expect_identical(result$simulationType, "ordinal_threshold_preserving")
  expect_identical(result$recommendedFactorCount, 1L)

  # The null distribution is genuinely polychoric: it must differ from the
  # Pearson simulation on the same ordinal data (same seed, same iterations).
  pearson_run <- run_parallel_analysis(efa_ordinal_fixture, iterations = 60, seed = 42)
  expect_false(identical(
    result$simulatedEigenvalues,
    pearson_run$simulatedEigenvalues
  ))
})

test_that("ordinal parallel analysis is reproducible under a fixed seed", {
  first <- run_parallel_analysis(
    efa_ordinal_fixture, iterations = 60, seed = 20260714,
    correlation_type = "polychoric"
  )
  second <- run_parallel_analysis(
    efa_ordinal_fixture, iterations = 60, seed = 20260714,
    correlation_type = "polychoric"
  )
  expect_identical(first$simulatedEigenvalues, second$simulatedEigenvalues)
  expect_identical(first$sampleEigenvalues, second$sampleEigenvalues)
})

test_that("ordinal parallel analysis reports unavailable when polychoric is impossible", {
  # A constant ordinal column makes polychoric estimation fail; PA must report
  # unavailable with a machine-readable reason instead of running Pearson.
  broken <- efa_ordinal_fixture
  broken[["ord1"]] <- rep(3L, nrow(broken))

  result <- run_parallel_analysis(
    broken, iterations = 20, seed = 1,
    correlation_type = "polychoric"
  )

  expect_false(isTRUE(result$available))
  expect_identical(result$reason, "unsupported_for_ordinal_correlation")
  expect_identical(result$correlationType, "polychoric")
  expect_identical(result$simulationType, "ordinal_threshold_preserving")
  expect_null(result$recommendedFactorCount)
})

test_that("unknown correlation types are rejected", {
  expect_error(
    run_parallel_analysis(efa_one_factor_fixture, iterations = 10, correlation_type = "spearman"),
    "MEASUREMENT_EFA_UNKNOWN_CORRELATION_TYPE"
  )
})

# ---------------------------------------------------------------------------
# Split validation reuses the user's estimator
# ---------------------------------------------------------------------------

test_that("split validation refits the user's estimator spec via the shared pipeline", {
  set.seed(20260807)
  latent <- rnorm(160)
  d <- as.data.frame(lapply(1:6, function(i) 0.7 * latent + rnorm(160, sd = 0.6)))
  names(d) <- paste0("v", 1:6)

  seen <- list()
  # run_split_validation resolves run_efa_with_method through globalenv (the
  # sourcing environment of lib/efa.R), so the mock must replace that binding.
  original_fit <- get("run_efa_with_method", envir = globalenv())
  mock_fit <- function(data, correlation, n_obs, factor_count,
                       method, rotation, item_scale) {
    seen[[length(seen) + 1L]] <<- list(
      method = method,
      rotation = rotation,
      item_scale = item_scale,
      factor_count = factor_count
    )
    list(
      loadings = matrix(0.6, nrow = 6, ncol = 2),
      factorCorrelations = matrix(c(1, 0.3, 0.3, 1), 2, 2),
      extractionMethod = method,
      numericalFallbacks = list()
    )
  }
  assign("run_efa_with_method", mock_fit, envir = globalenv())
  on.exit(assign("run_efa_with_method", original_fit, envir = globalenv()), add = TRUE)

  result <- run_split_validation(
    d, factor_count = 2, rotation = "promax", seed = 5,
    method = "minres", item_scale = "continuous"
  )

  expect_true(result$available)
  # train + holdout splits both refit through the shared pipeline
  expect_length(seen, 2L)
  for (call_spec in seen) {
    expect_identical(call_spec$method, "minres")
    expect_identical(call_spec$rotation, "promax")
    expect_identical(call_spec$item_scale, "continuous")
    expect_equal(call_spec$factor_count, 2)
  }
  expect_identical(result$method, "minres")
  expect_identical(result$correlationType, "pearson")
})

test_that("split validation honours the ordinal polychoric correlation world", {
  result <- run_split_validation(
    efa_ordinal_fixture, factor_count = 2, rotation = "promax", seed = 5,
    method = "ml", item_scale = "ordinal"
  )

  expect_true(result$available)
  expect_identical(result$correlationType, "polychoric")
  expect_identical(result$method, "ml")
})

test_that("split validation reports unavailable instead of swapping the estimator", {
  small <- efa_one_factor_fixture[1:19, , drop = FALSE]
  result <- run_split_validation(small, factor_count = 2, rotation = "promax", seed = 5)

  expect_false(isTRUE(result$available))
  expect_identical(result$reason, "split_validation_not_supported_for_this_estimator")
})

test_that("split validation rejects mismatched executed estimators", {
  set.seed(20260810)
  latent <- rnorm(160)
  d <- as.data.frame(lapply(1:6, function(i) 0.7 * latent + rnorm(160, sd = 0.6)))
  names(d) <- paste0("v", 1:6)

  call_count <- 0L
  original_fit <- get("run_efa_with_method", envir = globalenv())
  mock_fit <- function(data, correlation, n_obs, factor_count,
                       method, rotation, item_scale) {
    call_count <<- call_count + 1L
    executed <- if (call_count == 1L) "minres" else "paf"
    list(
      loadings = matrix(0.6, nrow = 6, ncol = 2),
      factorCorrelations = diag(2),
      extractionMethod = executed,
      executedExtractionMethod = executed,
      executedCorrelationType = "pearson",
      executedRotation = "promax",
      factorCount = 2L,
      numericalFallbacks = list()
    )
  }
  assign("run_efa_with_method", mock_fit, envir = globalenv())
  on.exit(assign("run_efa_with_method", original_fit, envir = globalenv()), add = TRUE)

  result <- run_split_validation(
    d, factor_count = 2, rotation = "promax", seed = 5,
    method = "minres", item_scale = "continuous",
    primary_execution = list(
      executedCorrelationType = "pearson",
      executedExtractionMethod = "minres",
      executedRotation = "promax",
      factorCount = 2L
    )
  )

  expect_false(result$available)
  expect_identical(result$reason, "split_validation_execution_mismatch")
  expect_identical(result$executionFingerprints$primary$extractionMethod, "minres")
  expect_identical(result$executionFingerprints$holdout$extractionMethod, "paf")
  expect_null(result$tuckerCongruence)
})

# ---------------------------------------------------------------------------
# Structured numerical fallback disclosure
# ---------------------------------------------------------------------------

test_that("PAF discloses SMC communality fallback on a singular correlation matrix", {
  singular <- matrix(1, 4, 4)
  rownames(singular) <- colnames(singular) <- paste0("s", 1:4)

  result <- run_paf(singular, nfactors = 1, rotation = "none")

  expect_length(result$numericalFallbacks, 1L)
  fallback <- result$numericalFallbacks[[1]]
  expect_identical(fallback$stage, "initial_communality")
  expect_identical(fallback$requested, "smc")
  expect_identical(fallback$used, "fixed_0_5")
  expect_match(fallback$reason, "inversion failed")
})

test_that("ordinal EFA discloses a correlation-world fallback when polychoric fails", {
  pearson <- cor(efa_ordinal_fixture)
  # Simulate polychoric being impossible (lavaan unavailable): the ordinal
  # branch must disclose a structured polychoric -> pearson fallback instead
  # of silently changing the correlation world.
  local_mocked_bindings(
    requireNamespace = function(package, quietly = TRUE) FALSE,
    .package = "base"
  )

  result <- run_efa_with_method(
    data = efa_ordinal_fixture,
    correlation = pearson,
    n_obs = nrow(efa_ordinal_fixture),
    factor_count = 1,
    method = "ml",
    rotation = "none",
    item_scale = "ordinal"
  )

  stages <- vapply(result$numericalFallbacks, function(f) f$stage, character(1))
  expect_true("correlation" %in% stages)
  correlation_fallback <- result$numericalFallbacks[[which(stages == "correlation")[[1]]]]
  expect_identical(correlation_fallback$requested, "polychoric")
  expect_identical(correlation_fallback$used, "pearson")
  expect_identical(result$requestedCorrelationType, "polychoric")
  expect_identical(result$executedCorrelationType, "pearson")
  expect_identical(result$correlationType, "pearson")
  expect_false(is.null(result$loadings))
})

test_that("minres EFA discloses extraction fallback to PAF when psych fails", {
  correlation <- cor(efa_one_factor_fixture)
  local_mocked_bindings(
    fa = function(...) NULL,
    .package = "psych"
  )

  result <- run_efa_with_method(
    data = efa_one_factor_fixture,
    correlation = correlation,
    n_obs = nrow(efa_one_factor_fixture),
    factor_count = 2,
    method = "minres",
    rotation = "promax",
    item_scale = "continuous"
  )

  stages <- vapply(result$numericalFallbacks, function(f) f$stage, character(1))
  expect_true("extraction" %in% stages)
  extraction_fallback <- result$numericalFallbacks[[which(stages == "extraction")[[1]]]]
  expect_identical(extraction_fallback$requested, "minres")
  expect_identical(extraction_fallback$used, "paf")
  expect_identical(result$extractionMethod, "paf_fallback_from_minres")
  expect_identical(result$requestedExtractionMethod, "minres")
  expect_identical(result$executedExtractionMethod, "paf")
  expect_false(is.null(result$loadings))
})
