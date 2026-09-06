# Unified result output layer: every R entrypoint writes through
# researchpath_write_result with one serialization contract.

source_engine("lib/runtime.R")
source_engine("lib/output_contract.R")

test_that("finite_number preserves non-finite kinds for provenance", {
  values <- finite_number(c(1, NA_real_, NaN, Inf, -Inf))
  expect_identical(values[[1]], 1)
  expect_true(is.na(values[[2]]) && !is.nan(values[[2]]))
  expect_true(is.nan(values[[3]]))
  expect_identical(values[[4]], Inf)
  expect_identical(values[[5]], -Inf)
})

test_that("researchpath_write_result writes a parseable document", {
  work <- tempfile(pattern = "rp-output-")
  dir.create(work)
  out <- file.path(work, "result.json")
  researchpath_write_result(
    list(a = 1, b = list(c = "x"), c_1 = NA_real_),
    out
  )
  parsed <- jsonlite::fromJSON(out, simplifyVector = FALSE)
  expect_equal(parsed$a, 1)
  expect_equal(parsed$b$c, "x")
  # NA must serialize as JSON null, not NaN.
  expect_true(is.null(parsed$c_1))
})

test_that("researchpath_write_result replaces an existing file atomically", {
  work <- tempfile(pattern = "rp-output-replace-")
  dir.create(work)
  out <- file.path(work, "result.json")
  researchpath_write_result(list(version = 1L), out)
  researchpath_write_result(list(version = 2L), out)
  parsed <- jsonlite::fromJSON(out, simplifyVector = FALSE)
  expect_equal(parsed$version, 2L)
})

test_that("researchpath_write_result rejects non-document results", {
  work <- tempfile(pattern = "rp-output-bad-")
  dir.create(work)
  out <- file.path(work, "result.json")
  expect_error(
    researchpath_write_result(list(1, 2, 3), out),
    "RESULT_NOT_A_NAMED_DOCUMENT"
  )
})

test_that("researchpath_write_result rejects duplicate top-level keys", {
  work <- tempfile(pattern = "rp-output-dup-")
  dir.create(work)
  out <- file.path(work, "result.json")
  duplicate <- list(a = 1, a = 2)
  expect_error(
    researchpath_write_result(duplicate, out),
    "RESULT_DUPLICATE_TOP_LEVEL_KEYS"
  )
})

test_that("researchpath_sanitize_finite neutralizes non-finite values recursively", {
  doc <- list(
    scalar = Inf,
    vector = c(1, NaN, 3),
    nested = list(deep = -Inf, ok = 2.5)
  )
  sanitized <- researchpath_sanitize_finite(doc)
  expect_true(is.na(sanitized$scalar))
  expect_true(is.na(sanitized$vector[[2]]))
  expect_equal(sanitized$vector[[1]], 1)
  expect_true(is.na(sanitized$nested$deep))
  expect_equal(sanitized$nested$ok, 2.5)
})

test_that("non-finite sanitization records JSON Pointer provenance but ignores ordinary NA", {
  work <- tempfile(pattern = "rp-output-provenance-")
  dir.create(work)
  out <- file.path(work, "result.json")
  researchpath_write_result(
    list(
      warnings = list(),
      provenance = list(engine = "test"),
      estimates = list(`a/b` = c(Inf, NA_real_, NaN), negative = -Inf)
    ),
    out
  )

  parsed <- jsonlite::fromJSON(out, simplifyVector = FALSE)
  expect_length(parsed$provenance$nonFiniteValues, 3L)
  paths <- vapply(parsed$provenance$nonFiniteValues, function(row) row$path, character(1))
  kinds <- vapply(parsed$provenance$nonFiniteValues, function(row) row$originalKind, character(1))
  expect_identical(paths, c("/estimates/a~1b/0", "/estimates/a~1b/2", "/estimates/negative"))
  expect_identical(kinds, c("Inf", "NaN", "-Inf"))
  expect_identical(parsed$warnings[[1]]$code, "NON_FINITE_RESULT_VALUE")
  expect_null(parsed$estimates[["a/b"]][[1]])
  expect_null(parsed$estimates[["a/b"]][[2]])
  expect_null(parsed$estimates[["a/b"]][[3]])
})

test_that("sanitization preserves named NULL fields without shifting siblings", {
  value <- list(
    factorCount = 3L,
    optionalReason = NULL,
    methodExecution = list(requestedMethod = "maximum_likelihood"),
    warnings = list()
  )

  sanitized <- researchpath_sanitize_finite_with_diagnostics(value)$value

  expect_named(sanitized, names(value))
  expect_identical(sanitized$factorCount, 3L)
  expect_null(sanitized$optionalReason)
  expect_identical(sanitized$methodExecution$requestedMethod, "maximum_likelihood")
  expect_identical(sanitized$warnings, list())
})
