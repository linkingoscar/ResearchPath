# Golden test: analytic power workbench vs an independent SciPy oracle.
#
# The product runner delegates to R pwr, while the checked-in reference values
# are generated from SciPy's noncentral t/F distributions and independent root
# solving. This test makes the external-validation claim executable by
# running the engine's power path (run_advanced_analysis.R, family
# power_analysis, method analytic) over the frozen spec grid.

project_root <- Sys.getenv("RESEARCHPATH_PROJECT_ROOT")
golden_path <- file.path(project_root, "engine", "R", "tests", "reference", "power-goldens-v1.json")
power_golden <- jsonlite::fromJSON(golden_path, simplifyVector = FALSE)
power_tolerance <- power_golden$provenance$tolerance

run_engine_power <- function(case, work_dir) {
  spec <- list(
    family = "power_analysis",
    method = "analytic",
    designFamily = case$designFamily,
    solveFor = case$solveFor,
    alpha = 0.05,
    targetPower = 0.8,
    predictors = case$predictors,
    groups = case$groups,
    simulations = 5000,
    seed = 20260814,
    datasetVersionId = "power_golden_v1"
  )
  if (!is.null(case$effectSize)) spec$effectSize <- case$effectSize
  if (!is.null(case$effectSizeMetric)) spec$effectSizeMetric <- case$effectSizeMetric
  if (!is.null(case$sampleSize)) spec$sampleSize <- case$sampleSize
  if (!is.null(case$targetCIWidth)) spec$targetCIWidth <- case$targetCIWidth
  if (!is.null(case$confidenceLevel)) spec$confidenceLevel <- case$confidenceLevel
  if (!is.null(case$sd)) spec$sd <- case$sd
  if (!is.null(case$targetPower)) spec$targetPower <- as.numeric(case$targetPower)

  input_path <- file.path(work_dir, "input.json")
  output_path <- file.path(work_dir, "output.json")
  writeLines(
    jsonlite::toJSON(list(spec = spec,
                           progressPath = file.path(work_dir, "progress.json"),
                           cancelPath = file.path(work_dir, "cancel.json")),
      auto_unbox = TRUE, digits = NA),
    input_path
  )
  runner <- file.path(project_root, "engine", "R", "run_advanced_analysis.R")
  rscript <- file.path(R.home("bin"), "Rscript.exe")
  status <- system2(
    rscript, c("--vanilla", shQuote(runner), shQuote(input_path), shQuote(output_path)),
    stdout = TRUE, stderr = TRUE
  )
  if (!file.exists(output_path)) {
    stop("run_advanced_analysis.R power failed for ", case$id, ": ", paste(status, collapse = "\n"))
  }
  jsonlite::fromJSON(output_path, simplifyVector = FALSE)
}

for (case in power_golden$cases) {
  test_that(paste0("analytic power ", case$id, " matches the SciPy oracle"), {
    work <- tempfile(paste0("rp-power-", case$id, "-")); dir.create(work)
    result <- run_engine_power(case, work)
    family_result <- result$familyResult
    expect_equal(
      as.numeric(family_result$solvedValue), as.numeric(case$expected$solvedValue),
      tolerance = power_tolerance$solvedValue,
      info = paste0(case$id, ": solvedValue")
    )
    if (!is.null(case$expected$achievedPower)) {
      expect_equal(
        as.numeric(family_result$achievedPower), as.numeric(case$expected$achievedPower),
        tolerance = power_tolerance$achievedPower,
        info = paste0(case$id, ": achievedPower")
      )
    }
  })
}
