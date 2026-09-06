# Independent PROCESS 5.0 reference golden generator.
#
# This script runs the OFFICIAL "PROCESS for R" macro (Andrew F. Hayes) on
# deterministic synthetic data and freezes the numeric results (path
# coefficients, indirect/conditional effects, bootstrap intervals, JN
# regions) as golden JSON. The product runner is NEVER invoked here, so a
# request-to-runner regression cannot mask itself by regenerating goldens.
#
# The official macro is not copied into this repository. Point the script at
# your local copy with RESEARCHPATH_PROCESS_MACRO or the first CLI argument:
#
#   $env:RESEARCHPATH_PROCESS_MACRO = "C:/path/to/process5.0.R"
#   & ".runtime/R/bin/Rscript.exe" --vanilla engine/R/tests/reference/generate-process-goldens.R
#
# Regenerating a checked-in golden is a reviewed change, never an automatic
# CI update. Tolerances must not be widened to accept drift.

suppressPackageStartupMessages(library(jsonlite))
suppressPackageStartupMessages(library(digest))

macro_path <- Sys.getenv("RESEARCHPATH_PROCESS_MACRO", unset = "")
args <- commandArgs(trailingOnly = TRUE)
if (length(args) >= 1L) macro_path <- args[[1]]
if (!nzchar(macro_path)) {
  stop(
    "Provide a local official PROCESS for R 5.0 macro with ",
    "RESEARCHPATH_PROCESS_MACRO or the first command-line argument"
  )
}
if (!file.exists(macro_path)) stop("PROCESS macro not found: ", macro_path)

out_dir <- Sys.getenv("RESEARCHPATH_PROCESS_GOLDEN_OUTPUT_DIR", unset = "")
if (!nzchar(out_dir)) {
  args_all <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("--file=", args_all, value = TRUE)
  base_dir <- if (length(file_arg) > 0) dirname(substring(file_arg[1], 8)) else "engine/R/tests/reference"
  out_dir <- base_dir
}
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

seed_value <- 20260730
replicates <- 5000

# Deterministic synthetic data — identical formulas to the Model 19 numeric
# reference in apps/api/tests/test_process_catalog_execution.py so the two
# golden families are consistent.
row <- 1:240
x <- sin(row * 0.37) + cos(row * 0.11)
w <- cos(row * 0.23) + sin(row * 0.07)
z <- sin(row * 0.19) - cos(row * 0.13)
m1 <- 0.4 * x + 0.18 * w - 0.12 * z + sin(row * 1.31) * 0.55
m2 <- 0.25 * m1 + 0.15 * x + 0.1 * w + cos(row * 0.71) * 0.45
y <- 0.22 * x + 0.36 * m1 + 0.14 * w - 0.09 * z +
  0.17 * m1 * w - 0.11 * m1 * z + 0.08 * m1 * w * z +
  cos(row * 1.17) * 0.6
data <- data.frame(
  var_x = x, var_m1 = m1, var_m2 = m2, var_y = y, var_w = w, var_z = z
)
# Mean-centering identical to the product spec (centering method=mean on
# x, m1, w, z).
for (v in c("var_x", "var_m1", "var_w", "var_z")) {
  data[[v]] <- data[[v]] - mean(data[[v]])
}
data_sha <- digest(format(data, digits = 17), algo = "sha256")

source(macro_path)

parse_coeff_rows <- function(lines, outcome_label, skip_banner = FALSE) {
  # Find the "Outcome Variable: <label>" block; return rows of its "Model:" table.
  i <- 1
  n <- length(lines)
  while (i <= n) {
    if (grepl("^Outcome Variable:", lines[i]) &&
        grepl(outcome_label, lines[i], fixed = TRUE)) {
      j <- i
      while (j <= n && !grepl("^Model:", lines[j])) j <- j + 1
      if (j <= n) {
        j <- j + 1
        rows <- list()
        repeat {
          if (j > n) break
          line <- lines[j]
          j <- j + 1
          if (grepl("^\\s*$", line)) next
          if (grepl("^\\s*coeff\\s", line)) next
          if (!grepl("^\\s*\\S+\\s+-?[0-9.]+", line)) break
          parts <- strsplit(trimws(line), "\\s+")[[1]]
          if (length(parts) >= 7) {
            rows[[length(rows) + 1]] <- list(
              term = parts[1],
              coeff = as.numeric(parts[2]),
              se = as.numeric(parts[3]),
              t = as.numeric(parts[4]),
              p = as.numeric(parts[5]),
              llci = as.numeric(parts[6]),
              ulci = as.numeric(parts[7])
            )
          }
        }
        if (length(rows) > 0) return(rows)
      }
    }
    i <- i + 1
  }
  stop("coefficient block not found for outcome: ", outcome_label)
}

parse_effect_table <- function(lines, header_pattern, value_cols) {
  idx <- grep(header_pattern, lines)
  if (length(idx) == 0) return(NULL)
  j <- idx[[1]] + 2
  rows <- list()
  repeat {
    if (j > length(lines)) break
    line <- lines[j]
    j <- j + 1
    if (grepl("^\\s*$", line)) break
    if (grepl("^\\s*[A-Za-z][A-Za-z ]*\\s+[A-Za-z]", line)) next
    parts <- strsplit(trimws(line), "\\s+")[[1]]
    # First column may be a numeric probe (moderator value) or a label.
    first_is_numeric <- suppressWarnings(!is.na(as.numeric(parts[1])))
    if (first_is_numeric) {
      if (length(parts) < length(value_cols)) next
      values <- as.numeric(parts[1:length(value_cols)])
      rows[[length(rows) + 1]] <- c(list(label = parts[1]), as.list(values))
    } else {
      if (length(parts) < length(value_cols) + 1) next
      rows[[length(rows) + 1]] <- c(
        list(label = parts[1]),
        as.list(as.numeric(parts[2:(length(value_cols) + 1)]))
      )
    }
    names(rows[[length(rows)]]) <- c("label", value_cols)
  }
  if (length(rows) == 0) return(NULL)
  rows
}

parse_conditional_effects <- function(lines, value_cols, header_pattern = NULL) {
  idx <- grep("^\\s*INDIRECT EFFECT:", lines)
  if (length(idx) == 0) return(NULL)
  j <- idx[[1]]
  pattern <- if (!is.null(header_pattern)) header_pattern else "^\\s*[A-Za-z_][A-Za-z0-9_]*\\s+Effect\\s"
  while (j <= length(lines) && !grepl(pattern, lines[j])) j <- j + 1
  if (j > length(lines)) return(NULL)
  j <- j + 1
  rows <- list()
  repeat {
    if (j > length(lines)) break
    line <- lines[j]
    j <- j + 1
    if (grepl("^\\s*$", line)) break
    parts <- strsplit(trimws(line), "\\s+")[[1]]
    if (length(parts) < length(value_cols)) next
    # W x Z grid rows carry 6 numeric columns (W, Z, Effect, BootSE, L, U).
    if (length(parts) == 6 && all(suppressWarnings(!is.na(as.numeric(parts))))) {
      values <- as.numeric(parts)
      row <- list(label = paste0("W_", values[1], "__Z_", values[2]),
                  w = values[1], z = values[2],
                  effect = values[3], bootSE = values[4],
                  bootLLCI = values[5], bootULCI = values[6])
      rows[[length(rows) + 1]] <- row
      next
    }
    if (length(parts) < length(value_cols) + 1) next
    if (!all(suppressWarnings(!is.na(as.numeric(parts[2:(length(value_cols) + 1)]))))) next
    rows[[length(rows) + 1]] <- c(
      list(label = parts[1]),
      as.list(as.numeric(parts[2:(length(value_cols) + 1)]))
    )
    names(rows[[length(rows)]]) <- c("label", value_cols)
  }
  if (length(rows) == 0) return(NULL)
  rows
}

parse_conditional_direct <- function(lines) {
  idx <- grep("Conditional direct effect\\(s\\) of X on Y:", lines)
  if (length(idx) == 0) return(NULL)
  j <- idx[[1]] + 2
  rows <- list()
  repeat {
    if (j > length(lines)) break
    line <- lines[j]
    j <- j + 1
    if (grepl("^\\s*$", line)) break
    parts <- strsplit(trimws(line), "\\s+")[[1]]
    if (length(parts) == 7 && all(suppressWarnings(!is.na(as.numeric(parts))))) {
      values <- as.numeric(parts)
      rows[[length(rows) + 1]] <- list(
        w = values[1], effect = values[2], se = values[3],
        t = values[4], p = values[5], llci = values[6], ulci = values[7]
      )
    }
  }
  if (length(rows) == 0) return(NULL)
  rows
}

parse_johnson_neyman <- function(lines) {
  region_idx <- grep("defining Johnson-Neyman significance region", lines)
  grid_idx <- grep("Conditional effect of focal predictor at values", lines)
  region <- NULL
  if (length(region_idx) > 0) {
    j <- region_idx[[1]] + 2
    rows <- list()
    repeat {
      if (j > length(lines)) break
      line <- lines[j]
      j <- j + 1
      if (grepl("^\\s*$", line)) break
      parts <- strsplit(trimws(line), "\\s+")[[1]]
      if (length(parts) >= 3) {
        rows[[length(rows) + 1]] <- list(
          value = as.numeric(parts[1]),
          percentBelow = as.numeric(parts[2]),
          percentAbove = as.numeric(parts[3])
        )
      }
    }
    region <- if (length(rows) > 0) rows else NULL
  }
  grid <- NULL
  if (length(grid_idx) > 0) {
    j <- grid_idx[[1]] + 2
    rows <- list()
    repeat {
      if (j > length(lines)) break
      line <- lines[j]
      j <- j + 1
      if (grepl("^\\s*$", line)) break
      parts <- strsplit(trimws(line), "\\s+")[[1]]
      if (length(parts) >= 7) {
        rows[[length(rows) + 1]] <- list(
          w = as.numeric(parts[1]),
          effect = as.numeric(parts[2]),
          se = as.numeric(parts[3]),
          t = as.numeric(parts[4]),
          p = as.numeric(parts[5]),
          llci = as.numeric(parts[6]),
          ulci = as.numeric(parts[7])
        )
      }
    }
    grid <- if (length(rows) > 0) rows else NULL
  }
  list(region = region, grid = grid)
}

run_macro <- function(model_number, mediators, bc, with_jn = FALSE, w_flag = FALSE, z_flag = FALSE) {
  m_args <- if (length(mediators) > 0) list(m = paste0("var_", mediators)) else list()
  jn_arg <- if (with_jn) list(jn = 1) else list()
  boot_arg <- if (model_number >= 4) list(boot = replicates, seed = seed_value, bc = bc) else list()
  # PROCESS errors out when W/Z are supplied for models that do not moderate.
  w_args <- if (w_flag || model_number %in% c(1, 7, 14)) list(w = "var_w") else list()
  z_args <- if (z_flag || model_number %in% c(9, 12, 19, 69, 73)) list(z = "var_z") else list()
  capture <- capture.output(
    invisible(do.call(process, c(
      list(
        data = data, y = "var_y", x = "var_x",
        model = model_number, conf = 95, modelbt = 1, total = 1,
        progress = 0, decimals = "10.7"
      ),
      m_args, w_args, z_args, jn_arg, boot_arg
    )))
  )
  capture
}

build_equations <- function(lines, outcomes) {
  lapply(outcomes, function(outcome) parse_coeff_rows(lines, outcome))
}

# Model 4: simple mediation (X -> M1 -> Y)
m4_lines <- run_macro(4, c("m1"), bc = 0)
m4_lines_bc <- run_macro(4, c("m1"), bc = 1)

# Model 6: serial double mediation (X -> M1 -> M2 -> Y)
m6_lines <- run_macro(6, c("m1", "m2"), bc = 0)

# Model 7: first-stage moderation (W moderates X -> M1)
m7_lines <- run_macro(7, c("m1"), bc = 0)

# Model 14: second-stage moderation (W moderates M1 -> Y)
m14_lines <- run_macro(14, c("m1"), bc = 0)

# Model 1: pure moderation (W moderates X -> Y) with JN region
m1_lines <- run_macro(1, c(), bc = 0, with_jn = TRUE)

effect_field_names <- c("effect", "bootSE", "bootLLCI", "bootULCI")

goldens <- list(
  provenance = list(
    reference = "Independent PROCESS for R Version 5.0 macro (Andrew F. Hayes)",
    macroSource = "user-provided official PROCESS for R 5.0 macro (not distributed)",
    dataSha256 = data_sha,
    dataGenerator = "sin/cos formulas shared with test_process_catalog_execution.py Model 19 reference",
    seed = seed_value,
    replicates = replicates,
    confidenceLevel = 0.95,
    centering = list(method = "mean", nodeIds = c("var_x", "var_m1", "var_w", "var_z")),
    decimals = "10.7",
    generatedAt = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
    rVersion = R.version.string,
    tolerance = list(
      coefficient = 5e-7,
      effect = 5e-7,
      bootstrapInterval = 0.01,
      bootstrapSE = 0.001
    )
  ),
  models = list(
    model_4 = list(
      equations = build_equations(m4_lines, c("var_m1", "var_y")),
      indirect = parse_effect_table(m4_lines, "Indirect effect\\(s\\) of X on Y:", effect_field_names),
      total = parse_effect_table(m4_lines, "Total effect of X on Y:", c("effect", "se", "t", "p", "llci", "ulci")),
      direct = parse_effect_table(m4_lines, "Direct effect of X on Y:", c("effect", "se", "t", "p", "llci", "ulci")),
      indirectBiasCorrected = parse_effect_table(m4_lines_bc, "Indirect effect\\(s\\) of X on Y:", effect_field_names)
    ),
    model_6 = list(
      equations = build_equations(m6_lines, c("var_m1", "var_m2", "var_y")),
      indirect = parse_effect_table(m6_lines, "Indirect effect\\(s\\) of X on Y:", effect_field_names)
    ),
    model_7 = list(
      equations = build_equations(m7_lines, c("var_m1", "var_y")),
      conditional = parse_conditional_effects(m7_lines, effect_field_names),
      index = parse_effect_table(m7_lines, "Index of moderated mediation:", effect_field_names)
    ),
    model_14 = list(
      equations = build_equations(m14_lines, c("var_m1", "var_y")),
      conditional = parse_conditional_effects(m14_lines, effect_field_names),
      index = parse_effect_table(m14_lines, "Index of moderated mediation:", effect_field_names)
    ),
    model_1 = list(
      equations = build_equations(m1_lines, c("var_y")),
      jn = parse_johnson_neyman(m1_lines)
    )
  )
)

out_path <- file.path(out_dir, "process-goldens.json")
write_json(goldens, path = out_path, auto_unbox = TRUE, pretty = TRUE, null = "null", digits = NA)
cat("Wrote ", out_path, "\n", sep = "")

# --- Additional predefined templates (5/15/21/22/58/59) -----------------------
# Kept in a second file so each golden file stays within the architecture
# 800-line ceiling. Same synthetic data, seed and macro.

m5_lines  <- run_macro(5,  c("m1"), bc = 0, w_flag = TRUE)
m15_lines <- run_macro(15, c("m1"), bc = 0, w_flag = TRUE)
m21_lines <- run_macro(21, c("m1"), bc = 0, w_flag = TRUE, z_flag = TRUE)
m22_lines <- run_macro(22, c("m1"), bc = 0, w_flag = TRUE, z_flag = TRUE)
m58_lines <- run_macro(58, c("m1"), bc = 0, w_flag = TRUE)
m59_lines <- run_macro(59, c("m1"), bc = 0, w_flag = TRUE)
# Model 60 exercises the generic estimator path beyond the predefined set:
# W and Z moderate the a path, W moderates the b path.
m60_lines <- run_macro(60, c("m1"), bc = 0, w_flag = TRUE, z_flag = TRUE)
# Models 28 (a-W, b-Z, direct-W) and 29 (+ direct-Z) complete the generic
# estimator's coverage of the remaining catalog families.
m28_lines <- run_macro(28, c("m1"), bc = 0, w_flag = TRUE, z_flag = TRUE)
m29_lines <- run_macro(29, c("m1"), bc = 0, w_flag = TRUE, z_flag = TRUE)

grid_header <- "^\\s*[A-Za-z_][A-Za-z0-9_]*\\s+[A-Za-z_][A-Za-z0-9_]*\\s+Effect\\s"

# Keep the second golden file compact (architecture line ceiling): equation
# rows freeze coeff only; full-precision rows live in the official outputs.
compact_eq <- function(rows) {
  lapply(rows, function(row) list(term = row$term, coeff = row$coeff))
}

goldens2 <- list(
  provenance = goldens$provenance,
  models = list(
    model_5 = list(
      equations = lapply(build_equations(m5_lines, c("var_m1", "var_y")), compact_eq),
      indirect = parse_effect_table(m5_lines, "Indirect effect\\(s\\) of X on Y:", effect_field_names),
      conditionalDirect = parse_conditional_direct(m5_lines)
    ),
    model_15 = list(
      equations = lapply(build_equations(m15_lines, c("var_m1", "var_y")), compact_eq),
      conditional = parse_conditional_effects(m15_lines, effect_field_names),
      index = parse_effect_table(m15_lines, "Index of moderated mediation:", effect_field_names)
    ),
    model_21 = list(
      equations = lapply(build_equations(m21_lines, c("var_m1", "var_y")), compact_eq),
      conditional = parse_conditional_effects(m21_lines, effect_field_names, grid_header)
    ),
    model_22 = list(
      equations = lapply(build_equations(m22_lines, c("var_m1", "var_y")), compact_eq),
      conditional = parse_conditional_effects(m22_lines, effect_field_names, grid_header)
    ),
    model_58 = list(
      equations = lapply(build_equations(m58_lines, c("var_m1", "var_y")), compact_eq),
      conditional = parse_conditional_effects(m58_lines, effect_field_names)
    ),
    model_59 = list(
      equations = lapply(build_equations(m59_lines, c("var_m1", "var_y")), compact_eq),
      conditional = parse_conditional_effects(m59_lines, effect_field_names)
    ),
    model_60 = list(
      equations = lapply(build_equations(m60_lines, c("var_m1", "var_y")), compact_eq),
      conditional = parse_conditional_effects(m60_lines, effect_field_names, grid_header),
      direct = parse_effect_table(m60_lines, "Direct effect of X on Y:", c("effect", "se", "t", "p", "llci", "ulci"))
    )
  )
)

out_path2 <- file.path(out_dir, "process-goldens-2.json")
write_json(goldens2, path = out_path2, auto_unbox = TRUE, pretty = TRUE, null = "null", digits = NA)
cat("Wrote ", out_path2, "\n", sep = "")

# --- Generic-estimator catalog models 28/29 (third file: line ceiling) --------
goldens3 <- list(
  provenance = goldens$provenance,
  models = list(
    model_28 = list(
      equations = lapply(build_equations(m28_lines, c("var_m1", "var_y")), compact_eq),
      conditional = parse_conditional_effects(m28_lines, effect_field_names, grid_header)
    ),
    model_29 = list(
      equations = lapply(build_equations(m29_lines, c("var_m1", "var_y")), compact_eq),
      conditional = parse_conditional_effects(m29_lines, effect_field_names, grid_header)
    )
  )
)

out_path3 <- file.path(out_dir, "process-goldens-3.json")
write_json(goldens3, path = out_path3, auto_unbox = TRUE, pretty = TRUE, null = "null", digits = NA)
cat("Wrote ", out_path3, "\n", sep = "")
