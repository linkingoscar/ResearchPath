# 独立加载（测试/复用）时引导 seed 工具；入口脚本已先行 source。
if (!exists("researchpath_seed", mode = "function", inherits = TRUE)) {
  if (file.exists(file.path("engine", "R", "lib", "seed_utils.R"))) {
    source(file.path("engine", "R", "lib", "seed_utils.R"))
  }
}

# PROCESS 5.0 supported boundary
#
# The product runner is an independent implementation. The official macro is
# not distributed with ResearchPath; a user may provide a local copy only when
# regenerating or checking frozen validation evidence. This file translates the
# platform's frozen graph into the reference vocabulary and enforces the same
# numbered-model restrictions before the ResultBundle estimator runs.

process5_reference_version <- "5.0"
process5_reference_source <- "external user-provided PROCESS for R 5.0 macro"
process5_reference_sha256 <- "3D02E6BBEC08A4A3EE9EDEB8E6300678D717A7A08E41E11C8149C04AB64B8648"

process5_model_limits <- function(model_number) {
  if (model_number < 4L) return(c(0L, 0L))
  if (model_number %in% c(80L, 81L)) return(c(3L, 6L))
  if (model_number == 82L) return(c(4L, 4L))
  if (model_number == 6L || (model_number >= 83L && model_number <= 92L)) {
    return(c(2L, 6L))
  }
  c(1L, 10L)
}

process5_node_ids <- function(spec, role) {
  vapply(
    Filter(function(node) identical(node$role, role), spec$nodes),
    function(node) as.character(node$id),
    character(1)
  )
}

process5_edge_pairs <- function(spec) {
  vapply(
    spec$edges,
    function(edge) paste(edge$from, edge$to, sep = "->"),
    character(1)
  )
}

process5_binary_mediator_error <- function(spec) {
  binary_mediator_ids <- vapply(
    Filter(
      function(node) identical(node$role, "m") && identical(node$dataType, "binary"),
      spec$nodes
    ),
    function(node) node$id,
    character(1)
  )
  if (length(binary_mediator_ids) == 0L) return(NULL)
  paste0(
    "BINARY_MEDIATOR_NOT_SUPPORTED: ",
    paste(binary_mediator_ids, collapse = ", "),
    " (logit a path times OLS b path is not a defined indirect effect)"
  )
}

process5_reference_path <- function(script_dir) {
  configured_path <- Sys.getenv("RESEARCHPATH_PROCESS_MACRO", unset = "")
  if (nzchar(configured_path)) return(configured_path)
  file.path(script_dir, "..", "..", "specs", "vendor", "process5.0.R")
}

process5_reference_actual_sha256 <- function(script_dir) {
  path <- process5_reference_path(script_dir)
  if (!file.exists(path)) return(NA_character_)
  tryCatch(
    toupper(unname(tools::sha256sum(path))),
    error = function(...) NA_character_
  )
}

process5_reference_available <- function(script_dir) {
  identical(process5_reference_actual_sha256(script_dir), process5_reference_sha256)
}

process5_standard_guard <- function(spec, model_number, script_dir = NULL) {
  errors <- character(0)
  if (!is.finite(model_number) || model_number < 1L || model_number > 92L) {
    return(list(valid = FALSE, errors = "PROCESS 5.0 model number is invalid"))
  }
  # script_dir is accepted by the public helper signature. Runtime
  # execution never depends on the optional external validation oracle.
  mediator_ids <- process5_node_ids(spec, "m")
  binary_mediator_error <- process5_binary_mediator_error(spec)
  if (!is.null(binary_mediator_error)) errors <- c(errors, binary_mediator_error)
  limits <- process5_model_limits(model_number)
  if (length(mediator_ids) < limits[[1]] || length(mediator_ids) > limits[[2]]) {
    errors <- c(
      errors,
      sprintf(
        "Model %s requires %s-%s mediators (received %s)",
        model_number, limits[[1]], limits[[2]], length(mediator_ids)
      )
    )
  }
  if (length(process5_node_ids(spec, "x")) != 1L || length(process5_node_ids(spec, "y")) != 1L) {
    errors <- c(errors, "PROCESS requires exactly one X and one Y")
  }

  # The reference macro's special wcmat branch for Models 91/92 adds W to
  # inter-mediator equations even though their model-matrix bit vector is
  # zero.  Therefore these two models still require an explicit W column.
  if (model_number %in% c(91L, 92L) && length(process5_node_ids(spec, "w")) != 1L) {
    errors <- c(errors, sprintf("PROCESS Model %s requires W for serial-edge moderation", model_number))
  }
  if (model_number %in% c(83L, 84L, 85L, 86L, 87L, 88L, 89L, 90L, 91L, 92L) && length(mediator_ids) < 2L) {
    errors <- c(errors, "Serial PROCESS models require at least two mediators")
  }

  # PROCESS R accepts numeric columns only.  Binary variables are accepted
  # after the platform's explicit 0/1 encoding; unordered factors are not.
  for (node in spec$nodes) {
    encoding <- if (is.null(node$encoding)) list() else node$encoding
    encoding_method <- if (!is.null(encoding$method)) {
      as.character(encoding$method)
    } else if (identical(node$dataType, "binary")) {
      "binary_indicator"
    } else {
      "as_is"
    }
    if (node$role %in% c("x", "m", "y", "w", "z") &&
        !node$dataType %in% c("continuous", "binary")) {
      errors <- c(errors, sprintf("PROCESS variable %s must be continuous or binary", node$id))
    }
    if (node$role %in% c("x", "m", "y", "w", "z") && node$dataType == "binary" &&
        !identical(encoding_method, "binary_indicator")) {
      errors <- c(errors, sprintf("Binary PROCESS variable %s must use binary_indicator encoding", node$id))
    }
  }
  list(valid = length(errors) == 0L, errors = errors)
}

process5_standard_options <- function(spec, model_number, data) {
  x <- process5_node_ids(spec, "x")
  y <- process5_node_ids(spec, "y")
  m <- process5_node_ids(spec, "m")
  w <- process5_node_ids(spec, "w")
  z <- process5_node_ids(spec, "z")
  estimation <- spec$estimation
  bootstrap <- estimation$bootstrap
  standard_errors <- if (identical(estimation$standardErrors, "hc3")) 3L else 5L
  center <- if (identical(estimation$centering$method, "mean") &&
                length(estimation$centering$nodeIds) > 0L) 1L else 0L
  boot <- if (isTRUE(bootstrap$enabled)) as.integer(bootstrap$replicates) else 0L
  bias_corrected <- if (identical(bootstrap$method, "bias_corrected")) 1L else 0L
  seed <- if (is.null(bootstrap$seed)) -999L else researchpath_seed(bootstrap$seed)
  covariates <- process5_node_ids(spec, "covariate")

  list(
    data = data,
    y = y,
    x = x,
    m = if (length(m) > 0L) m else "xxxxx",
    w = if (length(w) > 0L) w else "xxxxx",
    z = if (length(z) > 0L) z else "xxxxx",
    cov = if (length(covariates) > 0L) covariates else "xxxxx",
    model = as.integer(model_number),
    hc = standard_errors,
    center = center,
    conf = as.numeric(estimation$confidenceLevel * 100),
    boot = boot,
    bc = bias_corrected,
    seed = seed,
    outscreen = 0L,
    progress = 0L,
    save = 2L
  )
}

process5_reference_manifest <- function(script_dir) {
  list(
    name = "PROCESS for R",
    version = process5_reference_version,
    source = process5_reference_source,
    sha256 = process5_reference_sha256,
    available = process5_reference_available(script_dir),
    modelMatrix = "official process5.0.R modelmat (9 moderation bits)",
    specialRules = list(
      firstMediatorOnlyForW = c(83L, 86L),
      lastMediatorOnlyForW = c(87L, 90L),
      serialEdgesModeratedByW = c(91L, 92L)
    )
  )
}
