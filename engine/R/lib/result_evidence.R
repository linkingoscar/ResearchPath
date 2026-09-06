researchpath_process_sample_flow <- function(data, missing_method) {
  original <- nrow(data)
  missing_variable_counts <- vapply(data, function(column) sum(is.na(column)), integer(1))
  missing_rows <- sum(!complete.cases(data))
  missing_pattern_labels <- if (missing_rows > 0L) {
    pattern_matrix <- is.na(data)
    apply(pattern_matrix, 1, function(row) paste(names(data)[row], collapse = ","))
  } else character(0)
  pattern_table <- if (length(missing_pattern_labels) > 0L) sort(table(missing_pattern_labels), decreasing = TRUE) else integer(0)
  missing_patterns <- lapply(seq_along(pattern_table), function(index) list(
    pattern = names(pattern_table)[[index]], count = as.integer(pattern_table[[index]])
  ))
  list(
    original = as.integer(original), selected = as.integer(original),
    missingRows = as.integer(missing_rows), counts = missing_variable_counts,
    patterns = missing_patterns, missingMethod = missing_method
  )
}

researchpath_default_estimand <- function(spec, effect_type) {
  declared <- spec$estimandSpec$effectScale
  if (!is.null(declared) && nzchar(as.character(declared))) return(as.character(declared))
  if (identical(effect_type, "indirect")) return("cross-sectional indirect association")
  if (identical(effect_type, "conditional")) return("cross-sectional conditional indirect association")
  if (identical(effect_type, "index")) return("cross-sectional moderated association index")
  "cross-sectional regression association"
}

researchpath_process_effect_metadata <- function(effects, spec, payload, process_model_type) {
  edge_hypothesis <- function(edge) {
    value <- edge$hypothesis
    if (is.null(value) || !nzchar(as.character(value))) NULL else as.character(value)
  }
  declared_estimand <- spec$estimandSpec$effectScale
  default_estimand <- function(effect_type) {
    if (!is.null(declared_estimand) && nzchar(as.character(declared_estimand))) return(as.character(declared_estimand))
    if (identical(effect_type, "indirect")) return("cross-sectional indirect association")
    if (identical(effect_type, "conditional")) return("cross-sectional conditional indirect association")
    if (identical(effect_type, "index")) return("cross-sectional moderated association index")
    "cross-sectional regression association"
  }
  node_for_role <- function(role) {
    matches <- Filter(function(node) identical(node$role, role), spec$nodes)
    if (length(matches) == 0L) NULL else matches[[1]]$id
  }
  x_id <- node_for_role("x")
  y_id <- node_for_role("y")
  paths_between <- function(from, to, visited = character(0)) {
    if (identical(from, to)) return(list(list()))
    if (from %in% visited) return(list())
    outgoing <- Filter(function(edge) identical(edge$from, from), spec$edges)
    paths <- list()
    for (edge in outgoing) {
      tails <- paths_between(edge$to, to, c(visited, from))
      for (tail in tails) paths[[length(paths) + 1L]] <- c(list(edge), tail)
    }
    paths
  }
  all_paths <- if (is.null(x_id) || is.null(y_id)) list() else paths_between(x_id, y_id)
  indirect_paths <- Filter(function(path) length(path) > 1L, all_paths)
  path_ids <- function(path) vapply(path, function(edge) edge$id, character(1))
  path_nodes <- function(path) c(path[[1]]$from, vapply(path, function(edge) edge$to, character(1)))
  role_path <- function(roles) {
    nodes <- vapply(roles, function(role) {
      value <- node_for_role(role); if (is.null(value)) "" else value
    }, character(1))
    match <- Filter(function(path) identical(path_nodes(path), nodes), indirect_paths)
    if (length(match) == 1L) path_ids(match[[1]]) else character(0)
  }
  numbered_indirect <- function(number) {
    if (identical(process_model_type, "model_6")) {
      roles <- switch(as.character(number),
        "1" = c("x", "m1", "y"),
        "2" = c("x", "m2", "y"),
        "3" = c("x", "m1", "m2", "y"),
        character(0)
      )
      if (length(roles) > 0L) return(role_path(roles))
    }
    if (number >= 1L && number <= length(indirect_paths)) path_ids(indirect_paths[[number]]) else character(0)
  }
  edge_ids_for_effect <- function(effect) {
    if (!is.null(effect$edgeIds) && length(effect$edgeIds) > 0L) return(as.character(unlist(effect$edgeIds)))
    if (!is.null(effect$edgeId)) return(as.character(effect$edgeId))
    if (identical(effect$type, "total")) return(unique(unlist(lapply(all_paths, path_ids), use.names = FALSE)))
    if (grepl("total_indirect", effect$id, fixed = TRUE)) {
      return(unique(unlist(lapply(indirect_paths, path_ids), use.names = FALSE)))
    }
    path_match <- regexec("^effect_path_([0-9]+)", effect$id)
    captures <- regmatches(effect$id, path_match)[[1]]
    if (length(captures) == 2L) return(numbered_indirect(as.integer(captures[[2]])))
    indirect_match <- regexec("^effect_indirect_([0-9]+)$", effect$id)
    captures <- regmatches(effect$id, indirect_match)[[1]]
    if (length(captures) == 2L) return(numbered_indirect(as.integer(captures[[2]])))
    if (identical(effect$id, "effect_indirect") && length(indirect_paths) == 1L) return(path_ids(indirect_paths[[1]]))
    if (effect$type %in% c("conditional", "index") && length(indirect_paths) == 1L) return(path_ids(indirect_paths[[1]]))
    if (identical(effect$type, "contrast") && identical(process_model_type, "model_6")) {
      numbers <- as.integer(unlist(regmatches(effect$id, gregexpr("[1-3]", effect$id))))
      return(unique(unlist(lapply(numbers, numbered_indirect), use.names = FALSE)))
    }
    character(0)
  }
  edge_ids <- vapply(spec$edges, function(edge) edge$id, character(1))
  for (index in seq_along(effects)) {
    effect <- effects[[index]]
    bound_ids <- edge_ids_for_effect(effect)
    bound_ids <- bound_ids[bound_ids %in% edge_ids]
    bound_edges <- Filter(function(edge) edge$id %in% bound_ids, spec$edges)
    hypotheses <- unique(vapply(bound_edges, function(edge) {
      value <- edge_hypothesis(edge); if (is.null(value)) "" else value
    }, character(1)))
    hypotheses <- hypotheses[nzchar(hypotheses)]
    effect$edgeIds <- as.list(bound_ids)
    if (length(bound_ids) == 1L) effect$edgeId <- bound_ids[[1]]
    effect$hypothesisIds <- as.list(hypotheses)
    effect$hypothesisId <- if (length(hypotheses) == 1L) hypotheses[[1]] else NULL
    effect$estimand <- if (is.null(effect$estimand) || !nzchar(as.character(effect$estimand))) default_estimand(effect$type) else as.character(effect$estimand)
    effects[[index]] <- effect
  }
  evidence_edges <- lapply(spec$edges, function(edge) list(
    edgeId = edge$id, from = edge$from, to = edge$to,
    hypothesisId = edge_hypothesis(edge),
    estimand = if (!is.null(edge$estimand) && nzchar(as.character(edge$estimand))) as.character(edge$estimand) else default_estimand("path")
  ))
  evidence_bindings <- lapply(effects, function(effect) {
    binding <- list(
      effectId = effect$id, edgeIds = effect$edgeIds,
      hypothesisIds = effect$hypothesisIds,
      estimand = effect$estimand
    )
    singular_hypothesis <- effect[["hypothesisId", exact = TRUE]]
    if (!is.null(singular_hypothesis)) binding$hypothesisId <- singular_hypothesis
    binding
  })
  publication_reasons <- character(0)
  if (length(hc3_unavailable_warnings) > 0L) publication_reasons <- c(publication_reasons, "HC3_UNAVAILABLE")
  list(
    effects = effects,
    evidenceGraph = list(
      modelVersionId = if (is.null(payload$modelVersionId)) "demo" else payload$modelVersionId,
      edges = evidence_edges, effectBindings = evidence_bindings
    ),
    claimBoundary = list(
      claimMode = if (identical(spec$design$timeStructure, "experimental")) "experimental_effect" else "association",
      causalLanguageAllowed = identical(spec$design$timeStructure, "experimental") && identical(spec$design$claimMode, "causal_with_assumptions"),
      temporalPrecedenceEstablished = spec$design$timeStructure %in% c("longitudinal", "experimental"),
      experimentalEffectEstablished = identical(spec$design$timeStructure, "experimental")
    ),
    publicationReasons = unique(publication_reasons)
  )
}

researchpath_bootstrap_metadata <- function(config, requested, invalid, confidence_level) {
  requested <- as.integer(requested); invalid <- as.integer(invalid)
  list(
    familyId = "process_effects",
    method = if (isTRUE(config$enabled)) as.character(config$method) else "not_run",
    replicatesRequested = requested, replicatesValid = max(0L, requested - invalid),
    invalidReplications = invalid, invalidRate = invalid / max(1, requested),
    seed = researchpath_seed(config$seed), confidenceLevel = confidence_level,
    failureAction = "超过 5% 无效复制时拒绝发布区间；未超过时披露无效数与有效数。"
  )
}

researchpath_process_warnings <- function(hc3_unavailable_warnings, dropped_bootstrap_replications, replicates, spec, m_node, m1, binary_level_mappings, y_node, binary_node_ids) {
  warnings <- hc3_unavailable_warnings
  if (dropped_bootstrap_replications > 0L) warnings[[length(warnings) + 1L]] <- list(
    code = "BOOTSTRAP_REPLICATION_DROPPED", severity = "warning",
    message = sprintf("bootstrap 重抽样中累计 %d 次（%.1f%%）拟合失败被剔除，置信区间基于剩余有效重抽样计算。", dropped_bootstrap_replications, 100 * dropped_bootstrap_replications / max(1L, replicates))
  )
  if (identical(spec$design$timeStructure, "cross_sectional") && (!is.null(m_node) || !is.null(m1))) warnings[[length(warnings) + 1L]] <- list(
    code = "CROSS_SECTIONAL_MEDIATION", severity = "warning", message = "横截面数据的间接关联不能单独证明因果机制或时间顺序。"
  )
  for (binary_id in names(binary_level_mappings)) {
    mapping <- binary_level_mappings[[binary_id]]
    warnings[[length(warnings) + 1L]] <- list(
      code = paste0("BINARY_ENCODING_", binary_id), severity = "info",
      message = sprintf("二分类变量 %s 编码为 0=%s、1=%s；Logistic 系数以 1 为事件解释。", binary_id, mapping$reference, mapping$event)
    )
  }
  if (y_node$id %in% binary_node_ids && (!is.null(m_node) || !is.null(m1))) warnings[[length(warnings) + 1L]] <- list(
    code = "BINARY_OUTCOME_INDIRECT_SCALE", severity = "warning",
    message = "二分类结果变量的 b 路径和间接效应包含 log-odds 尺度；不能与线性概率尺度的总效应作机械比例分解。"
  )
  warnings
}

researchpath_process_provenance <- function(spec, payload, hc3_unavailable_warnings, bootstrap_config, replicates, process5_manifest, bootstrap_parallel_state) {
  list(
    engine = "researchpath-r", engineVersion = "0.3.0", rVersion = R.version.string,
    jsonliteVersion = as.character(packageVersion("jsonlite")), dataSha256 = payload$dataSha256,
    standardErrors = spec$estimation$standardErrors, confidenceLevel = spec$estimation$confidenceLevel,
    # HC3 is never silently replaced by classical covariance.  Keep the
    # Compatibility field remains false; warnings and CI methods disclose
    # HC3_UNAVAILABLE when applicable.
    hc3FallbackApplied = FALSE,
    bootstrapReplicates = if (isTRUE(bootstrap_config$enabled)) replicates else 0L,
    seed = researchpath_seed(bootstrap_config$seed), processReference = process5_manifest,
    executionMode = Sys.getenv("RESEARCHPATH_RUNTIME_MODE", "rscript"),
    parallelBackend = bootstrap_parallel_state$backend, parallelWorkers = as.integer(bootstrap_parallel_state$workers),
    rngStrategy = bootstrap_parallel_state$rngStrategy
  )
}
