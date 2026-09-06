source_engine("lib/empirical_multiplicity.R")

run_declared_multiplicity_case <- function(adjustment, declared_count, p_values) {
  observed_count <- length(p_values)
  variable_ids <- paste0("v", seq_len(max(2L, observed_count * 2L)))
  raw <- matrix(NA_real_, length(variable_ids), length(variable_ids))
  bindings <- vector("list", observed_count)
  for (index in seq_along(p_values)) {
    first <- (index - 1L) * 2L + 1L
    second <- first + 1L
    raw[first, second] <- p_values[[index]]
    bindings[[index]] <- list(
      component = "correlation",
      key = paste(variable_ids[c(first, second)], collapse = ":"),
      estimandId = paste0("e", index)
    )
  }
  researchpath_apply_global_multiplicity(
    list(multiplicityPAdjust = "BH", controlVariableIds = character(0)),
    FALSE,
    which(upper.tri(raw) & is.finite(raw)),
    raw,
    length(variable_ids),
    list(variables = lapply(variable_ids, function(id) list(id = id)), multiplicity = list()),
    NULL,
    NULL,
    "inferred",
    list(
      hypotheses = list(),
      estimands = list(),
      multiplicityFamilies = list(list(
        id = "declared_family",
        role = "primary",
        adjustment = adjustment,
        memberEstimandIds = as.list(paste0("e", seq_len(declared_count)))
      )),
      resultBindings = bindings
    )
  )
}

test_that("declaration-driven multiplicity uses declared estimands and excludes controls", {
  options <- list(
    multiplicityPAdjust = "BH",
    controlVariableIds = c("age", "gender"),
    outcomeVariableId = "outcome"
  )
  correlations <- list(
    variables = list(
      list(id = "x", label = "X"),
      list(id = "y", label = "Y"),
      list(id = "age", label = "Age"),
      list(id = "gender", label = "Gender")
    ),
    multiplicity = list()
  )
  raw <- matrix(NA_real_, 4, 4)
  raw[1, 2] <- raw[2, 1] <- 0.01
  raw[1, 3] <- raw[3, 1] <- 0.02
  raw[1, 4] <- raw[4, 1] <- 0.03
  group <- list(results = list(list(id = "outcome", pValueRaw = 0.04)), multiplicity = list())
  regression <- list(blocks = list(
    list(block = 1, coefficients = list(
      list(term = "x", pValue = 0.05),
      list(term = "age", pValue = 0.06)
    )),
    list(block = 2, coefficients = list(
      list(term = "x", pValue = 0.05),
      list(term = "gender", pValue = 0.07)
    ))
  ))
  declaration <- list(
    hypotheses = list(
      list(id = "H1", analysisRole = "primary", estimandIds = list("e_x")),
      list(id = "H2", analysisRole = "primary", estimandIds = list("e_y")),
      list(id = "H3", analysisRole = "exploratory", estimandIds = list("e_group"))
    ),
    estimands = list(
      list(id = "e_x", focalPredictorId = "x", outcomeId = "outcome"),
      list(id = "e_y", focalPredictorId = "y", outcomeId = "outcome"),
      list(id = "e_group", outcomeId = "outcome")
    ),
    multiplicityFamilies = list(
      list(id = "primary_hypotheses", role = "primary", adjustment = "holm", memberEstimandIds = list("e_x", "e_y")),
      list(id = "exploratory_effects", role = "exploratory", adjustment = "BH", memberEstimandIds = list("e_group"))
    ),
    resultBindings = list(
      list(component = "correlation", key = "x:y", estimandId = "e_y")
    )
  )
  result <- researchpath_apply_global_multiplicity(
    options, FALSE, which(upper.tri(raw) & is.finite(raw)), raw, 4,
    correlations, group, regression, "inferred", declaration
  )

  expect_identical(result$declarationStatus, "typed")
  expect_false(result$executionDerivedFamily)
  expect_identical(result$familySize, 3L)
  expect_true(all(c("primary_hypotheses", "exploratory_effects") %in% vapply(result$ledger$families, `[[`, character(1), "id")))
  expect_identical(result$hierarchicalRegression$blocks[[1]]$coefficients[[1]]$multiplicityFamilySize, 2L)
  expect_identical(result$hierarchicalRegression$blocks[[2]]$coefficients[[1]]$multiplicityFamilySize, 2L)
  expect_identical(result$hierarchicalRegression$blocks[[1]]$coefficients[[2]]$analysisRole, "adjustment_covariate")
  expect_identical(result$hierarchicalRegression$blocks[[2]]$coefficients[[2]]$analysisRole, "adjustment_covariate")
  expect_true(all(vapply(result$ledger$results, function(row) !identical(row$analysisRole, "adjustment_covariate"), logical(1))))
})

test_that("execution-derived multiplicity remains explicit and ineligible", {
  options <- list(multiplicityPAdjust = "BH", controlVariableIds = character(0))
  raw <- matrix(c(NA_real_, 0.01, 0.01, NA_real_), 2, 2)
  correlations <- list(
    variables = list(list(id = "x"), list(id = "y")),
    multiplicity = list()
  )
  result <- researchpath_apply_global_multiplicity(
    options, FALSE, which(upper.tri(raw) & is.finite(raw)), raw, 2,
    correlations, NULL, NULL, "inferred"
  )

  expect_identical(result$declarationStatus, "execution_derived_family")
  expect_true(result$executionDerivedFamily)
  expect_identical(result$ledger$mode, "execution_derived_family")
})

test_that("inferred regression pValue is the execution-derived adjusted p with raw preserved", {
  options <- list(multiplicityPAdjust = "BH", controlVariableIds = character(0))
  regression <- list(blocks = list(
    list(block = 1, coefficients = list(
      list(term = "x", pValue = 0.01),
      list(term = "z", pValue = 0.02)
    ))
  ))
  correlations <- list(
    variables = list(list(id = "x"), list(id = "z")),
    multiplicity = list()
  )
  result <- researchpath_apply_global_multiplicity(
    options, FALSE, integer(0), matrix(NA_real_, 2, 2), 2,
    correlations, NULL, regression, "inferred"
  )
  rows <- result$hierarchicalRegression$blocks[[1]]$coefficients
  expected <- stats::p.adjust(c(0.01, 0.02), method = "BH")
  expect_equal(vapply(rows, `[[`, numeric(1), "pValueRaw"), c(0.01, 0.02), tolerance = 1e-12)
  expect_equal(vapply(rows, `[[`, numeric(1), "pValueAdjusted"), expected, tolerance = 1e-12)
  expect_equal(vapply(rows, `[[`, numeric(1), "pValue"), expected, tolerance = 1e-12)
  expect_equal(vapply(rows, `[[`, numeric(1), "globalPValue"), expected, tolerance = 1e-12)
})

test_that("typed family adjustment uses declared n and blocks incomplete primary families", {
  result <- run_declared_multiplicity_case("holm", 3L, c(0.01, 0.02))
  family <- result$ledger$families[[1]]

  expect_identical(family$declaredFamilySize, 3L)
  expect_identical(family$adjustmentN, 3L)
  expect_identical(family$observedMemberCount, 2L)
  expect_identical(unlist(family$unobservedMemberEstimandIds), "e3")
  expect_true(isTRUE(family$primaryFamilyIncomplete))
  expect_true(isTRUE(result$primaryFamilyIncomplete))
  expect_identical(unlist(result$incompletePrimaryFamilyIds), "declared_family")
  expect_identical(unlist(result$publicationEligibilityReasons), "PRIMARY_MULTIPLICITY_FAMILY_INCOMPLETE")
  expect_equal(
    vapply(result$ledger$results, function(row) row$pValueAdjusted, numeric(1)),
    stats::p.adjust(c(0.01, 0.02), method = "holm", n = 3L),
    tolerance = 1e-12
  )
})

test_that("typed Holm, Bonferroni and BH adjustments retain declared family size", {
  cases <- list(
    holm = list(declared = 3L, p = c(0.01, 0.02)),
    bonferroni = list(declared = 4L, p = c(0.01, 0.02)),
    BH = list(declared = 5L, p = c(0.01, 0.02, 0.03)),
    all_observed = list(declared = 3L, p = c(0.01, 0.02, 0.03))
  )
  methods <- c(holm = "holm", bonferroni = "bonferroni", BH = "BH", all_observed = "BH")
  for (name in names(cases)) {
    result <- run_declared_multiplicity_case(methods[[name]], cases[[name]]$declared, cases[[name]]$p)
    family <- result$ledger$families[[1]]
    expect_identical(family$declaredFamilySize, cases[[name]]$declared)
    expect_identical(family$adjustmentN, cases[[name]]$declared)
    expect_equal(
      vapply(result$ledger$results, function(row) row$pValueAdjusted, numeric(1)),
      stats::p.adjust(cases[[name]]$p, method = methods[[name]], n = cases[[name]]$declared),
      tolerance = 1e-12
    )
  }
})
