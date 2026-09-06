# Public-data SEM oracle tests: the engine's SEM path (run_analysis.R with
# estimation.family="sem") vs frozen lavaan fits of the canonical models
# (Bollen 1989 PoliticalDemocracy; Holzinger-Swineford 1939 three-factor;
# lavaan Demo.growth latent growth curve).
#
# Both sides execute lavaan::sem with identical syntax and defaults, so
# tolerances are tight (1e-6), not statistical. The oracle fits live in
# output/validation-datasets/oracle/lavaan/*.json and *_estimates.csv; tests
# skip when the data or oracles are absent.

project_root <- Sys.getenv("RESEARCHPATH_PROJECT_ROOT")
public_data_dir <- Sys.getenv(
  "RESEARCHPATH_PUBLIC_DATA_DIR",
  file.path(project_root, "output", "validation-datasets")
)
lavaan_oracle_dir <- file.path(public_data_dir, "oracle", "lavaan")
lavaan_data_dir <- file.path(public_data_dir, "lavaan")

sem_tolerance <- list(fit = 1e-6, estimate = 1e-6, se = 1e-5)

sem_models <- list(
  PoliticalDemocracy_bollen = list(
    dataFile = "PoliticalDemocracy.csv",
    latents = list(
      list(id = "ind60", level = "first_order", indicators = list("x1", "x2", "x3")),
      list(id = "dem60", level = "first_order", indicators = list("y1", "y2", "y3", "y4")),
      list(id = "dem65", level = "first_order", indicators = list("y5", "y6", "y7", "y8"))
    ),
    required = c("x1", "x2", "x3", "y1", "y2", "y3", "y4", "y5", "y6", "y7", "y8"),
    syntax = paste(c(
      "ind60 =~ x1 + x2 + x3",
      "dem60 =~ y1 + y2 + y3 + y4",
      "dem65 =~ y5 + y6 + y7 + y8",
      "dem60 ~ ind60",
      "dem65 ~ ind60 + dem60",
      "y1 ~~ y5",
      "y2 ~~ y4 + y6",
      "y3 ~~ y7",
      "y4 ~~ y8",
      "y6 ~~ y8"
    ), collapse = "\n")
  ),
  HS1939_cfa = list(
    dataFile = "HolzingerSwineford1939.csv",
    latents = list(
      list(id = "visual", level = "first_order", indicators = list("x1", "x2", "x3")),
      list(id = "textual", level = "first_order", indicators = list("x4", "x5", "x6")),
      list(id = "speed", level = "first_order", indicators = list("x7", "x8", "x9"))
    ),
    required = c("x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9"),
    syntax = paste(c(
      "visual  =~ x1 + x2 + x3",
      "textual =~ x4 + x5 + x6",
      "speed   =~ x7 + x8 + x9"
    ), collapse = "\n")
  ),
  DemoGrowth_lgm = list(
    dataFile = "Demo.growth.csv",
    latents = list(
      list(id = "i", level = "first_order", indicators = list("t1", "t2", "t3", "t4")),
      list(id = "s", level = "first_order", indicators = list("t1", "t2", "t3", "t4"))
    ),
    required = c("t1", "t2", "t3", "t4"),
    syntax = paste(c(
      "i =~ 1*t1 + 1*t2 + 1*t3 + 1*t4",
      "s =~ 0*t1 + 1*t2 + 2*t3 + 3*t4"
    ), collapse = "\n")
  )
)

run_engine_sem <- function(tag, cfg, data_path, work_dir) {
  input_path <- file.path(work_dir, "input.json")
  output_path <- file.path(work_dir, "output.json")
  spec <- list(
    schemaVersion = "1.0.0",
    modelId = paste0("public_sem_", tag),
    name = "public data SEM validation",
    datasetVersionId = "public_sem_validation",
    design = list(timeStructure = "cross_sectional", clustering = "none", claimMode = "associational"),
    latents = cfg$latents,
    nodes = list(),
    edges = list(),
    moderations = list(),
    covariates = list(),
    estimation = list(
      family = "sem",
      estimator = "ML",
      missing = "listwise",
      standardErrors = "classical",
      confidenceLevel = 0.95,
      multiGroup = list(compareStructuralPaths = FALSE),
      invariance = FALSE
    )
  )
  writeLines(
    jsonlite::toJSON(list(
      runId = paste0("run_sem_", tag),
      modelHash = "public-sem-validation",
      modelVersionId = "public_sem_validation",
      dataSha256 = "public-sem-validation",
      dataPath = data_path,
      progressPath = file.path(work_dir, "progress.json"),
      cancelPath = file.path(work_dir, "cancel.json"),
      modelSpec = spec,
      lavaanSyntax = cfg$syntax,
      requiredVariables = cfg$required,
      orderedVariables = list()
    ), auto_unbox = TRUE, digits = NA),
    input_path
  )
  runner <- file.path(project_root, "engine", "R", "run_analysis.R")
  rscript <- file.path(R.home("bin"), "Rscript.exe")
  status <- system2(
    rscript, c("--vanilla", shQuote(runner), shQuote(input_path), shQuote(output_path)),
    stdout = TRUE, stderr = TRUE
  )
  if (!file.exists(output_path)) {
    stop("run_analysis.R SEM failed for ", tag, ": ", paste(status, collapse = "\n"))
  }
  jsonlite::fromJSON(output_path, simplifyVector = FALSE)
}

read_oracle_fit <- function(tag) {
  path <- file.path(lavaan_oracle_dir, paste0(tag, "_fit.json"))
  if (!file.exists(path)) return(NULL)
  jsonlite::fromJSON(path, simplifyVector = FALSE)
}

read_oracle_estimates <- function(tag) {
  path <- file.path(lavaan_oracle_dir, paste0(tag, "_estimates.csv"))
  if (!file.exists(path)) return(NULL)
  read.csv(path, check.names = FALSE, stringsAsFactors = FALSE)
}

skip_unless_sem_data <- function(tag, cfg) {
  skip_if(
    !file.exists(file.path(lavaan_data_dir, cfg$dataFile)) ||
      is.null(read_oracle_fit(tag)) || is.null(read_oracle_estimates(tag)),
    paste0("public SEM validation assets absent for ", tag)
  )
}

for (tag in names(sem_models)) {
  test_that(paste0(tag, " matches the frozen lavaan sem() fit"), {
    cfg <- sem_models[[tag]]
    skip_unless_sem_data(tag, cfg)
    work <- tempfile(paste0("rp-public-sem-", tag, "-")); dir.create(work)
    result <- run_engine_sem(tag, cfg, file.path(lavaan_data_dir, cfg$dataFile), work)

    expect_true(isTRUE(result$semResult$publicationEligible),
      info = paste0(tag, ": SEM should be publication-eligible (no convergence warnings)"))

    # Loadings and paths carry confidence-level-driven normal CIs.
    conf <- if (is.null(result$provenance$confidenceLevel)) {
      0.95
    } else {
      as.numeric(result$provenance$confidenceLevel)
    }
    critical <- stats::qnorm(1 - (1 - conf) / 2)
    for (entry in result$semResult$loadings) {
      if (!is.null(entry$standardError) && is.finite(entry$standardError)) {
        expect_false(is.null(entry$ciLower), info = paste0(tag, ": loading ciLower missing"))
        expect_false(is.null(entry$ciUpper), info = paste0(tag, ": loading ciUpper missing"))
        expect_equal(
          entry$ciUpper - entry$ciLower,
          2 * critical * entry$standardError,
          tolerance = 1e-8,
          info = paste0(tag, ": loading CI width must equal 2*z*SE")
        )
      }
    }
    for (entry in result$semResult$paths) {
      if (!is.null(entry$standardError) && is.finite(entry$standardError)) {
        expect_false(is.null(entry$ciLower), info = paste0(tag, ": path ciLower missing"))
        expect_false(is.null(entry$ciUpper), info = paste0(tag, ": path ciUpper missing"))
        expect_equal(
          entry$ciUpper - entry$ciLower,
          2 * critical * entry$standardError,
          tolerance = 1e-8,
          info = paste0(tag, ": path CI width must equal 2*z*SE")
        )
      }
    }

    # CR suppression must pair with the reason field and exactly one
    # warning-code emission family; non-suppressed constructs stay numeric.
    warning_codes <- vapply(result$warnings, function(w) w$code, character(1))
    cr_warning_present <- "SEM_CR_SUPPRESSED_CORRELATED_RESIDUALS" %in% warning_codes
    suppressed_constructs <- character(0)
    for (rel in result$semResult$reliability) {
      expect_true(
        is.null(rel$alphaSampleSize) || is.numeric(rel$alphaSampleSize),
        info = paste0(tag, ": alphaSampleSize must be number or null")
      )
      if (is.null(rel$mcdonaldOmega)) {
        expect_identical(
          rel$compositeReliabilityReason, "suppressed_correlated_residuals",
          info = paste0(tag, ": suppressed CR must expose its reason")
        )
        suppressed_constructs <- c(suppressed_constructs, rel$latentId)
      } else {
        expect_true(is.finite(as.numeric(rel$mcdonaldOmega)),
          info = paste0(tag, ": unsuppressed omega must be finite"))
      }
    }
    expect_identical(
      cr_warning_present, length(suppressed_constructs) > 0L,
      info = paste0(tag, ": CR warning presence must match suppressed constructs")
    )

    # Without bootstrap the provenance seed must be null, and the
    # executed standardErrors value must be a known enum member.
    expect_null(result$provenance$seed,
      info = paste0(tag, ": non-bootstrap provenance.seed must be null"))
    expect_true(
      result$provenance$standardErrors %in% c("classical", "hc3", "standard", "robust", "bootstrap"),
      info = paste0(tag, ": provenance.standardErrors enum")
    )

    # fit indices
    engine_fit <- result$semResult$fitIndices
    oracle_fit <- read_oracle_fit(tag)
    fit_map <- list(
      chiSquare = "chisq", df = "df", pValue = "pvalue",
      cfi = "cfi", tli = "tli", rmsea = "rmsea", srmr = "srmr",
      rmseaCiLower = "rmsea.ci.lower", rmseaCiUpper = "rmsea.ci.upper"
    )
    for (engine_key in names(fit_map)) {
      expect_equal(
        as.numeric(engine_fit[[engine_key]]), as.numeric(oracle_fit[[fit_map[[engine_key]]]]),
        tolerance = sem_tolerance$fit,
        info = paste0(tag, ": fit index ", engine_key)
      )
    }

    # loadings
    oracle_est <- read_oracle_estimates(tag)
    oracle_loadings <- oracle_est[oracle_est$op == "=~", , drop = FALSE]
    engine_loadings <- result$semResult$loadings
    expect_equal(length(engine_loadings), nrow(oracle_loadings),
      info = paste0(tag, ": loading count"))
    loading_key <- function(row) paste0(row$lhs, "->", row$rhs)
    engine_loading_by_key <- stats::setNames(
      engine_loadings,
      vapply(engine_loadings, function(row) paste0(row$latentId, "->", row$indicatorId), character(1))
    )
    for (index in seq_len(nrow(oracle_loadings))) {
      row <- oracle_loadings[index, , drop = FALSE]
      key <- loading_key(row)
      engine_row <- engine_loading_by_key[[key]]
      expect_false(is.null(engine_row), info = paste0(tag, ": engine missing loading ", key))
      expect_equal(
        as.numeric(engine_row$estimate), as.numeric(row$est),
        tolerance = sem_tolerance$estimate,
        info = paste0(tag, ": loading ", key)
      )
      expect_equal(
        as.numeric(engine_row$standardError), as.numeric(row$se),
        tolerance = sem_tolerance$se,
        info = paste0(tag, ": loading SE ", key)
      )
    }

    # structural paths
    oracle_paths <- oracle_est[oracle_est$op == "~", , drop = FALSE]
    engine_paths <- result$semResult$paths
    expect_equal(length(engine_paths), nrow(oracle_paths),
      info = paste0(tag, ": path count"))
    path_key <- function(row) paste0(row$rhs, "->", row$lhs)
    engine_path_by_key <- stats::setNames(
      engine_paths,
      vapply(engine_paths, function(row) paste0(row$from, "->", row$to), character(1))
    )
    for (index in seq_len(nrow(oracle_paths))) {
      row <- oracle_paths[index, , drop = FALSE]
      key <- path_key(row)
      engine_row <- engine_path_by_key[[key]]
      expect_false(is.null(engine_row), info = paste0(tag, ": engine missing path ", key))
      expect_equal(
        as.numeric(engine_row$estimate), as.numeric(row$est),
        tolerance = sem_tolerance$estimate,
        info = paste0(tag, ": path ", key)
      )
      expect_equal(
        as.numeric(engine_row$standardError), as.numeric(row$se),
        tolerance = sem_tolerance$se,
        info = paste0(tag, ": path SE ", key)
      )
    }
  })
}
