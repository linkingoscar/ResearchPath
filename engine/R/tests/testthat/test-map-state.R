# MAP test state contract: "unavailable" must never be reported as
# a numeric factor recommendation.

source_engine("lib/efa.R")

test_that("MAP reports available=TRUE with a recommendation on a PD matrix", {
  set.seed(20260807)
  latent <- rnorm(200)
  data <- data.frame(
    v1 = latent + rnorm(200, sd = 0.3),
    v2 = 0.9 * latent + rnorm(200, sd = 0.3),
    v3 = 0.8 * latent + rnorm(200, sd = 0.3),
    v4 = latent + rnorm(200, sd = 0.3),
    v5 = 0.7 * latent + rnorm(200, sd = 0.3)
  )
  result <- run_map_test(cor(data))
  expect_true(isTRUE(result$available))
  expect_identical(result$recommendedFactorCount, 1L)
  expect_identical(unlist(result$componentCounts), 0:3)
  expect_length(result$mapValues, ncol(data) - 1L)
  expect_null(result$reason)
})

test_that("MAP preserves the zero-component optimum instead of adding one", {
  result <- run_map_test(diag(5))

  expect_true(isTRUE(result$available))
  expect_identical(result$recommendedFactorCount, 0L)
  expect_identical(unlist(result$componentCounts), 0:3)
  expect_identical(which.min(unlist(result$mapValues)) - 1L, 0L)
})

test_that("MAP reports unavailable instead of a fake 1-factor on a non-PD matrix", {
  # Perfectly collinear columns produce a singular correlation matrix.
  set.seed(20260807)
  base <- rnorm(50)
  data <- data.frame(
    v1 = base,
    v2 = base,                 # v2 == v1 -> singular
    v3 = base * 2,
    v4 = base + 1e-14,
    v5 = -base
  )
  correlation <- cor(data)
  result <- run_map_test(correlation)
  expect_false(isTRUE(result$available))
  expect_null(result$recommendedFactorCount)
  expect_null(result$mapValues)
  expect_identical(result$reason, "correlation_matrix_not_positive_definite")
})

test_that("MAP reports unavailable for fewer than 3 items", {
  result <- run_map_test(matrix(c(1, 0.5, 0.5, 1), nrow = 2))
  expect_false(isTRUE(result$available))
  expect_identical(result$reason, "too_few_items")
  expect_null(result$recommendedFactorCount)
})
