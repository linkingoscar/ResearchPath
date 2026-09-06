# Unified R -> Python result output layer.
#
# Every R execution entrypoint (run_analysis.R, run_empirical_analysis.R,
# run_advanced_analysis.R, lib/sem_analysis.R) writes its result document
# through researchpath_write_result() so the serialization contract is
# identical everywhere:
#
#   * single top-level named list;
#   * auto_unbox = TRUE, full double precision (digits = NA);
#   * NA/NaN/Inf serialized as JSON null;
#   * atomic write (temp file + parse check + rename);
#   * non-finite values never leak into the document.
#
# This module is self-contained (jsonlite only) because run_advanced_analysis.R
# does not load lib/runtime.R on every family branch. Schema gating happens on
# the Python side (validate_contract) against specs/*.schema.json.

researchpath_write_result <- function(result, path) {
  if (!is.list(result) || is.null(names(result))) {
    stop("RESULT_NOT_A_NAMED_DOCUMENT: result must be a named list")
  }
  duplicate_names <- names(result)[duplicated(names(result))]
  if (length(duplicate_names) > 0) {
    stop(
      "RESULT_DUPLICATE_TOP_LEVEL_KEYS: ",
      paste(unique(duplicate_names), collapse = ", ")
    )
  }
  # NaN/Inf/-Inf become JSON null, with their original JSON Pointer path kept
  # in provenance. Ordinary NA remains a normal missing value and is not
  # misclassified as a numerical anomaly.
  sanitization <- researchpath_sanitize_finite_with_diagnostics(result)
  sanitized <- sanitization$value
  if (length(sanitization$diagnostics) > 0L) {
    if (is.null(sanitized$provenance) || !is.list(sanitized$provenance)) {
      sanitized$provenance <- list()
    }
    sanitized$provenance$nonFiniteValues <- sanitization$diagnostics
    if (is.null(sanitized$warnings) || !is.list(sanitized$warnings)) {
      sanitized$warnings <- list()
    }
    sanitized$warnings[[length(sanitized$warnings) + 1L]] <- list(
      code = "NON_FINITE_RESULT_VALUE",
      severity = "warning",
      message = paste0(
        length(sanitization$diagnostics),
        " 个 NaN/Inf 数值已转换为 null；原始类型与路径记录在 provenance.nonFiniteValues。"
      )
    )
  }
  temporary <- paste0(path, ".tmp.", Sys.getpid())
  on.exit(unlink(temporary), add = TRUE)
  write_json <- jsonlite::write_json
  from_json <- jsonlite::fromJSON
  write_json(
    sanitized,
    path = temporary,
    auto_unbox = TRUE,
    pretty = TRUE,
    digits = NA,
    na = "null",
    null = "null"
  )
  if (!file.exists(temporary)) {
    stop("failed to write result JSON")
  }
  parsed <- tryCatch(
    {
      from_json(temporary)
      TRUE
    },
    error = function(error) FALSE
  )
  if (!parsed) stop("result JSON failed serialization check")
  if (file.exists(path) && !file.remove(path)) {
    stop("failed to replace previous result JSON")
  }
  if (!file.rename(temporary, path)) {
    if (!file.copy(temporary, path, overwrite = TRUE)) {
      stop("failed to move result JSON into place")
    }
    unlink(temporary)
  }
  invisible(NULL)
}

researchpath_sanitize_finite <- function(value) {
  researchpath_sanitize_finite_with_diagnostics(value)$value
}

researchpath_json_pointer_segment <- function(value) {
  gsub("/", "~1", gsub("~", "~0", as.character(value), fixed = TRUE), fixed = TRUE)
}

researchpath_non_finite_kind <- function(value) {
  if (is.nan(value)) "NaN" else if (value > 0) "Inf" else "-Inf"
}

researchpath_sanitize_finite_with_diagnostics <- function(value, path = "") {
  if (is.list(value)) {
    sanitized <- vector("list", length(value))
    names(sanitized) <- names(value)
    diagnostics <- list()
    for (index in seq_along(value)) {
      segment <- if (!is.null(names(value)) && nzchar(names(value)[[index]])) {
        researchpath_json_pointer_segment(names(value)[[index]])
      } else {
        as.character(index - 1L)
      }
      child <- researchpath_sanitize_finite_with_diagnostics(
        value[[index]], paste0(path, "/", segment)
      )
      # Single-bracket assignment preserves an intentional NULL element.
      # Using `[[index]] <- NULL` would delete the element and shift every
      # following named field, corrupting the serialized result contract.
      sanitized[index] <- list(child$value)
      diagnostics <- c(diagnostics, child$diagnostics)
    }
    list(value = sanitized, diagnostics = diagnostics)
  } else if (is.numeric(value)) {
    sanitized <- value
    diagnostics <- list()
    for (index in seq_along(value)) {
      if (!is.na(value[[index]]) || is.nan(value[[index]])) {
        if (!is.finite(value[[index]])) {
          value_path <- if (length(value) == 1L) path else paste0(path, "/", index - 1L)
          diagnostics[[length(diagnostics) + 1L]] <- list(
            path = if (nzchar(value_path)) value_path else "/",
            originalKind = researchpath_non_finite_kind(value[[index]])
          )
          sanitized[[index]] <- NA_real_
        }
      }
    }
    list(value = sanitized, diagnostics = diagnostics)
  } else {
    list(value = value, diagnostics = list())
  }
}
