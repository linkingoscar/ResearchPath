args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("Usage: run_analysis.R <input.json> <output.json>")

started_at <- proc.time()[[3]]
input_path <- args[[1]]
output_path <- args[[2]]
suppressPackageStartupMessages(library(jsonlite))
payload <- fromJSON(input_path, simplifyVector = FALSE)
spec <- payload$modelSpec
progress_path <- payload$progressPath
cancel_path <- payload$cancelPath
args_all <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("--file=", args_all, value = TRUE)
script_dir <- if (length(file_arg) > 0) dirname(substring(file_arg[1], 8)) else "engine/R"
for (m in c("runtime.R", "parallel.R", "resource_budget.R", "seed_utils.R", "output_contract.R", "result_evidence.R", "marginal_effects.R", "process5_standard.R")) {
  source(file.path(script_dir, "lib", m), local = environment())
}
write_progress("preparing_data", 0.05)

if (identical(spec$estimation$family, "sem")) {
  source(file.path(script_dir, "lib", "sem_analysis.R"), local = environment())
}

nodes_for_role <- function(role) Filter(function(node) identical(node$role, role), spec$nodes)
node_for_role <- function(role, required = TRUE) {
  matches <- nodes_for_role(role)
  if (required && length(matches) != 1) stop(sprintf("Expected exactly one node for role %s", role))
  if (length(matches) == 0) return(NULL)
  matches[[1]]
}

x_node <- node_for_role("x")
y_node <- node_for_role("y")
m_nodes <- nodes_for_role("m")
w_node <- node_for_role("w", FALSE)
z_node <- node_for_role("z", FALSE)

m1 <- NULL; m2 <- NULL
if (length(m_nodes) == 2) {
  edge12 <- Filter(function(edge) identical(edge$from, m_nodes[[1]]$id) && identical(edge$to, m_nodes[[2]]$id), spec$edges)
  edge21 <- Filter(function(edge) identical(edge$from, m_nodes[[2]]$id) && identical(edge$to, m_nodes[[1]]$id), spec$edges)
  if (length(edge12) == 1) {
    m1 <- m_nodes[[1]]
    m2 <- m_nodes[[2]]
  } else if (length(edge21) == 1) {
    m1 <- m_nodes[[2]]
    m2 <- m_nodes[[1]]
  } else {
    ordered <- m_nodes[order(vapply(m_nodes, function(n) n$id, character(1)))]
    m1 <- ordered[[1]]
    m2 <- ordered[[2]]
  }
}
m_node <- if (length(m_nodes) >= 1) m_nodes[[1]] else NULL

# Binary mediators are rejected before fitting (logit a * OLS b is undefined).
mediator_error <- process5_binary_mediator_error(spec); if (!is.null(mediator_error)) stop(mediator_error)

process_model_number <- if (is.null(payload$processModelNumber)) NA_integer_ else as.integer(payload$processModelNumber)
process5_manifest <- NULL
process5_guard <- list(valid = TRUE, errors = character(0))
if (is.finite(process_model_number)) {
  process5_manifest <- process5_reference_manifest(script_dir)
  process5_guard <- process5_standard_guard(spec, process_model_number, script_dir)
  if (!isTRUE(process5_guard$valid)) {
    stop(paste(process5_guard$errors, collapse = "; "))
  }
}
template <- if (is.finite(process_model_number)) {
  paste0("model_", process_model_number)
} else {
  "model_1"
}
if (!is.finite(process_model_number) && length(m_nodes) == 0 && !is.null(z_node)) {
  has_three_way <- any(vapply(
    spec$moderations,
    function(mod) !is.null(mod$secondaryModeratorNodeId),
    logical(1)
  ))
  template <- if (has_three_way) "model_3" else "model_2"
} else if (!is.finite(process_model_number) && length(m_nodes) == 2) {
  template <- "model_6"
} else if (!is.finite(process_model_number) && length(m_nodes) == 1) {
  if (length(spec$moderations) == 0) {
    template <- "model_4"
  } else if (length(spec$moderations) == 1) {
    target_id <- spec$moderations[[1]]$targetEdgeId
    target <- Filter(function(edge) identical(edge$id, target_id), spec$edges)[[1]]
    template <- if (identical(target$from, x_node$id) && identical(target$to, m_node$id)) {
      "model_7"
    } else if (identical(target$from, m_node$id) && identical(target$to, y_node$id)) {
      "model_14"
    } else {
      "model_5"
    }
  } else if (length(spec$moderations) == 2) {
    moderated_edge_ids <- vapply(spec$moderations, function(mod) mod$targetEdgeId, character(1))
    moderated_edges <- Filter(function(edge) edge$id %in% moderated_edge_ids, spec$edges)
    moderated_pairs <- vapply(
      moderated_edges,
      function(edge) paste(edge$from, edge$to, sep = "->"),
      character(1)
    )
    a_pair <- paste(x_node$id, m_node$id, sep = "->")
    b_pair <- paste(m_node$id, y_node$id, sep = "->")
    direct_pair <- paste(x_node$id, y_node$id, sep = "->")
    moderator_role_for_pair <- function(pair) {
      matches <- Filter(function(mod) {
        target <- Filter(
          function(edge) identical(edge$id, mod$targetEdgeId),
          spec$edges
        )[[1]]
        identical(paste(target$from, target$to, sep = "->"), pair)
      }, spec$moderations)
      if (length(matches) != 1) return(NULL)
      moderator <- Filter(
        function(node) identical(node$id, matches[[1]]$moderatorNodeId),
        spec$nodes
      )[[1]]
      moderator$role
    }
    template <- if (all(c(a_pair, direct_pair) %in% moderated_pairs)) {
      "model_8"
    } else if (all(c(b_pair, direct_pair) %in% moderated_pairs)) {
      "model_15"
    } else if (
      identical(moderator_role_for_pair(a_pair), "w") &&
      identical(moderator_role_for_pair(b_pair), "z")
    ) {
      "model_21"
    } else {
      "model_58"
    }
  } else if (length(spec$moderations) == 3) {
    b_pair <- paste(m_node$id, y_node$id, sep = "->")
    b_moderation <- Filter(function(mod) {
      target <- Filter(
        function(edge) identical(edge$id, mod$targetEdgeId),
        spec$edges
      )[[1]]
      identical(paste(target$from, target$to, sep = "->"), b_pair)
    }, spec$moderations)[[1]]
    b_moderator <- Filter(
      function(node) identical(node$id, b_moderation$moderatorNodeId),
      spec$nodes
    )[[1]]
    template <- if (identical(b_moderator$role, "z")) "model_22" else "model_59"
  }
}
predefined_process_models <- c(1L, 2L, 3L, 4L, 5L, 6L, 7L, 8L, 14L, 15L, 21L, 22L, 58L, 59L)
predefined_mediator_shape <- if (!is.finite(process_model_number)) {
  FALSE
} else if (process_model_number < 4L) {
  length(m_nodes) == 0L
} else if (identical(process_model_number, 6L)) {
  length(m_nodes) == 2L
} else {
  length(m_nodes) == 1L
}
generic_process <- is.finite(process_model_number) && (
  !process_model_number %in% predefined_process_models || !predefined_mediator_shape
)

source(file.path(script_dir, "lib", "run_analysis_data.R"), local = environment())
original_n <- nrow(analysis_data)
sample_flow_source <- researchpath_process_sample_flow(analysis_data, spec$estimation$missing)
missing_variable_counts <- sample_flow_source$counts
missing_rows <- sample_flow_source$missingRows
missing_patterns <- sample_flow_source$patterns
analysis_data <- analysis_data[complete.cases(analysis_data), , drop = FALSE]
included_n <- nrow(analysis_data)
if (included_n < 10) stop("Fewer than 10 complete cases remain")

original_values <- analysis_data
centering_means <- list()
if (identical(spec$estimation$centering$method, "mean")) {
  for (node_id in spec$estimation$centering$nodeIds) {
    center <- mean(analysis_data[[node_id]])
    centering_means[[node_id]] <- center
    analysis_data[[node_id]] <- analysis_data[[node_id]] - center
  }
}

edge_for_id <- function(edge_id) Filter(function(edge) identical(edge$id, edge_id), spec$edges)[[1]]
for (mod in spec$moderations) {
  target <- edge_for_id(mod$targetEdgeId)
  if (!is.null(mod$secondaryModeratorNodeId)) {
    analysis_data[[mod$moderatorProductTermId]] <-
      analysis_data[[mod$moderatorNodeId]] *
      analysis_data[[mod$secondaryModeratorNodeId]]
    analysis_data[[mod$productTermId]] <-
      analysis_data[[target$from]] *
      analysis_data[[mod$moderatorNodeId]] *
      analysis_data[[mod$secondaryModeratorNodeId]]
  } else {
    analysis_data[[mod$productTermId]] <-
      analysis_data[[target$from]] * analysis_data[[mod$moderatorNodeId]]
  }
}

equation_plan <- function(outcome_node) {
  incoming <- Filter(function(edge) identical(edge$to, outcome_node$id), spec$edges)
  predictors <- vapply(incoming, function(edge) edge$from, character(1))
  joint_moderator_term_added <- FALSE
  for (mod in spec$moderations) {
    target <- edge_for_id(mod$targetEdgeId)
    if (identical(target$to, outcome_node$id)) {
      predictors <- c(predictors, mod$moderatorNodeId)
      if (!is.null(mod$secondaryModeratorNodeId)) {
        predictors <- c(predictors, mod$secondaryModeratorNodeId)
        if (!joint_moderator_term_added) {
          predictors <- c(predictors, mod$moderatorProductTermId)
          joint_moderator_term_added <- TRUE
        }
      }
      predictors <- c(predictors, mod$productTermId)
    }
  }
  for (assignment in spec$covariates) {
    if (outcome_node$id %in% unlist(assignment$outcomeNodeIds)) predictors <- c(predictors, assignment$nodeId)
  }
  list(outcome = outcome_node$id, predictors = unique(predictors))
}

plans <- list()
fit_key_by_outcome <- list()
if (generic_process) {
  mediator_order <- m_nodes
  if (length(mediator_order) > 1) {
    remaining <- vapply(mediator_order, function(node) node$id, character(1))
    ordered_ids <- character(0)
    while (length(remaining) > 0) {
      available <- remaining[vapply(remaining, function(node_id) {
        incoming_mediators <- vapply(
          Filter(
            function(edge) identical(edge$to, node_id) && edge$from %in% remaining,
            spec$edges
          ),
          function(edge) edge$from,
          character(1)
        )
        length(incoming_mediators) == 0
      }, logical(1))]
      if (length(available) == 0) stop("Mediator graph contains a cycle")
      ordered_ids <- c(ordered_ids, sort(available))
      remaining <- setdiff(remaining, available)
    }
    mediator_order <- lapply(ordered_ids, function(node_id) {
      Filter(function(node) identical(node$id, node_id), m_nodes)[[1]]
    })
  }
  for (index in seq_along(mediator_order)) {
    fit_key <- paste0("m", index)
    plans[[fit_key]] <- equation_plan(mediator_order[[index]])
    fit_key_by_outcome[[mediator_order[[index]]$id]] <- fit_key
  }
} else if (identical(template, "model_6")) {
  plans$m1 <- equation_plan(m1)
  plans$m2 <- equation_plan(m2)
  fit_key_by_outcome[[m1$id]] <- "m1"
  fit_key_by_outcome[[m2$id]] <- "m2"
} else if (!is.null(m_node)) {
  plans$m <- equation_plan(m_node)
  fit_key_by_outcome[[m_node$id]] <- "m"
}
plans$y <- equation_plan(y_node)
fit_key_by_outcome[[y_node$id]] <- "y"

binary_node_ids <- vapply(
  Filter(function(node) identical(node$dataType, "binary"), spec$nodes),
  function(node) node$id,
  character(1)
)

source(file.path(script_dir, "lib", "inference_covariance.R"), local = environment())
source(file.path(script_dir, "lib", "analysis_regression.R"), local = environment())
fits <- fit_models(analysis_data)
write_progress("fitting_equations", 0.25)

equations <- list()
if (generic_process) {
  for (fit_name in names(plans)) {
    if (identical(fit_name, "y")) next
    plan <- plans[[fit_name]]
    fit <- fits[[fit_name]]
    equations[[length(equations) + 1]] <- list(
      id = paste0("equation_", fit_name),
      outcomeRole = "m",
      formula = paste(plan$outcome, "~", paste(plan$predictors, collapse = " + ")),
      rSquared = get_r_squared(fit),
      adjustedRSquared = get_adj_r_squared(fit),
      nagelkerkeRSquared = get_nagelkerke_r_squared(fit),
      rSquaredType = if (inherits(fit, "glm")) "mcfadden_pseudo_r_squared" else "r_squared",
      modelFamily = if (inherits(fit, "glm")) "binomial_logit" else "linear",
      coefficients = coefficient_rows(fit, paste0("equation_", fit_name))
    )
  }
} else if (identical(template, "model_6")) {
  equations[[length(equations) + 1]] <- list(
    id = "equation_m1", outcomeRole = "m",
    formula = paste(m1$id, "~", paste(plans$m1$predictors, collapse = " + ")),
    rSquared = get_r_squared(fits$m1),
    adjustedRSquared = get_adj_r_squared(fits$m1),
    nagelkerkeRSquared = get_nagelkerke_r_squared(fits$m1),
    rSquaredType = if (inherits(fits$m1, "glm")) "mcfadden_pseudo_r_squared" else "r_squared",
    modelFamily = if (inherits(fits$m1, "glm")) "binomial_logit" else "linear",
    coefficients = coefficient_rows(fits$m1, "equation_m1")
  )
  equations[[length(equations) + 1]] <- list(
    id = "equation_m2", outcomeRole = "m",
    formula = paste(m2$id, "~", paste(plans$m2$predictors, collapse = " + ")),
    rSquared = get_r_squared(fits$m2),
    adjustedRSquared = get_adj_r_squared(fits$m2),
    nagelkerkeRSquared = get_nagelkerke_r_squared(fits$m2),
    rSquaredType = if (inherits(fits$m2, "glm")) "mcfadden_pseudo_r_squared" else "r_squared",
    modelFamily = if (inherits(fits$m2, "glm")) "binomial_logit" else "linear",
    coefficients = coefficient_rows(fits$m2, "equation_m2")
  )
} else if (!is.null(m_node)) {
  equations[[length(equations) + 1]] <- list(
    id = "equation_m", outcomeRole = "m",
    formula = paste(m_node$id, "~", paste(plans$m$predictors, collapse = " + ")),
    rSquared = get_r_squared(fits$m),
    adjustedRSquared = get_adj_r_squared(fits$m),
    nagelkerkeRSquared = get_nagelkerke_r_squared(fits$m),
    rSquaredType = if (inherits(fits$m, "glm")) "mcfadden_pseudo_r_squared" else "r_squared",
    modelFamily = if (inherits(fits$m, "glm")) "binomial_logit" else "linear",
    coefficients = coefficient_rows(fits$m, "equation_m")
  )
}
equations[[length(equations) + 1]] <- list(
  id = "equation_y", outcomeRole = "y",
  formula = paste(y_node$id, "~", paste(plans$y$predictors, collapse = " + ")),
  rSquared = get_r_squared(fits$y),
  adjustedRSquared = get_adj_r_squared(fits$y),
  nagelkerkeRSquared = get_nagelkerke_r_squared(fits$y),
  rSquaredType = if (inherits(fits$y, "glm")) "mcfadden_pseudo_r_squared" else "r_squared",
  modelFamily = if (inherits(fits$y, "glm")) "binomial_logit" else "linear",
  coefficients = coefficient_rows(fits$y, "equation_y")
)

  diagnostics <- lapply(names(fits), function(role) {
    fit <- fits[[role]]
    design <- model.matrix(fit)
    auxiliary <- if (ncol(design) > 1) lm(residuals(fit)^2 ~ design[, -1, drop = FALSE]) else NULL
    bp_statistic <- if (is.null(auxiliary)) 0 else nobs(fit) * summary(auxiliary)$r.squared
    # 用辅助回归的实际秩（减截距），共线列不重复计入自由度
    bp_df <- if (is.null(auxiliary)) 0 else max(0, qr(auxiliary)$rank - 1)
  list(
    equationId = paste0("equation_", role),
    residualStandardError = unname(if (inherits(fit, "glm")) {
      if (fit$df.residual > 0) sqrt(fit$deviance / fit$df.residual) else 0.0
    } else {
      summary(fit)$sigma
    }),
    maximumLeverage = unname(max(hatvalues(fit))),
    maximumCooksDistance = unname(max(cooks.distance(fit))),
    heteroskedasticity = list(
      method = "Breusch-Pagan auxiliary regression",
      statistic = bp_statistic,
      degreesOfFreedom = bp_df,
      pValue = if (bp_df > 0) pchisq(bp_statistic, df = bp_df, lower.tail = FALSE) else 1
    )
  )
})

effects <- list()
for (edge in spec$edges) {
  fit_name <- fit_key_by_outcome[[edge$to]]
  if (is.null(fit_name)) stop(sprintf("No fitted equation for edge outcome %s", edge$to))
  estimate <- unname(coef(fits[[fit_name]])[[edge$from]])
  is_direct <- identical(edge$from, x_node$id) && identical(edge$to, y_node$id)
  effect_type <- if (is_direct) "direct" else "path"
  effects[[length(effects) + 1]] <- list(
    id = paste0("effect_", edge$id), type = effect_type,
    label = if (is.null(edge$label) || edge$label == "") edge$id else edge$label,
    estimate = estimate, edgeId = edge$id, edgeIds = as.list(edge$id),
    hypothesisId = if (is.null(edge$hypothesis) || !nzchar(as.character(edge$hypothesis))) NULL else as.character(edge$hypothesis),
    estimand = researchpath_default_estimand(spec, effect_type)
  )
}

bootstrap_config <- spec$estimation$bootstrap
replicates <- as.integer(bootstrap_config$replicates)
alpha <- 1 - spec$estimation$confidenceLevel
source(file.path(script_dir, "lib", "bootstrap.R"), local = environment())

# 无效重抽样在 ≤5% 以内被 bootstrap_ci 剔除而不终止；包装器汇总剔除数，报告阶段显式警告。
dropped_bootstrap_replications <- 0L
bootstrap_interval <- function(values, original_estimate) {
  interval <- bootstrap_ci(values, original_estimate)
  if (interval$invalidReplicationCount > 0L) dropped_bootstrap_replications <<- dropped_bootstrap_replications + as.integer(interval$invalidReplicationCount)
  interval
}

source(file.path(script_dir, "lib", "moderation_reporting.R"), local = environment())

if (generic_process) {
  source(file.path(script_dir, "lib", "generic_process.R"), local = environment())
  generic_effects <- researchpath_generic_process_effects(
    spec = spec,
    fits = fits,
    plans = plans,
    fit_key_by_outcome = fit_key_by_outcome,
    x_node = x_node,
    y_node = y_node,
    w_node = w_node,
    z_node = z_node,
    original_values = original_values,
    centering_means = centering_means,
    bootstrap_config = bootstrap_config,
    replicates = replicates,
    alpha = alpha,
    included_n = included_n
  )
  effects <- c(effects, generic_effects$effects)
  if (!is.null(generic_effects$bootstrapParallel)) {
    bootstrap_parallel <- generic_effects$bootstrapParallel
  }
} else {
moderation <- if (length(spec$moderations) >= 1) spec$moderations[[1]] else NULL

if (identical(template, "model_6")) {
  a1 <- unname(coef(fits$m1)[[x_node$id]])
  a2 <- unname(coef(fits$m2)[[x_node$id]])
  d <- unname(coef(fits$m2)[[m1$id]])
  b1 <- unname(coef(fits$y)[[m1$id]])
  b2 <- unname(coef(fits$y)[[m2$id]])
  direct <- unname(coef(fits$y)[[x_node$id]])

  indirect_1 <- a1 * b1
  indirect_2 <- a2 * b2
  indirect_3 <- a1 * d * b2
  total_indirect <- indirect_1 + indirect_2 + indirect_3
} else if (identical(template, "model_8")) {
  mod_m <- Filter(function(mod) identical(edge_for_id(mod$targetEdgeId)$to, m_node$id), spec$moderations)[[1]]
  mod_y <- Filter(function(mod) { target <- edge_for_id(mod$targetEdgeId); identical(target$to, y_node$id) && identical(target$from, x_node$id) }, spec$moderations)[[1]]

  a1 <- unname(coef(fits$m)[[x_node$id]])
  a3 <- unname(coef(fits$m)[[mod_m$productTermId]])
  b1 <- unname(coef(fits$y)[[m_node$id]])

  conditional <- vapply(seq_along(representative_model), function(index) (a1 + a3 * representative_model[[index]]) * b1, numeric(1))
  index_value <- a3 * b1
} else if (identical(template, "model_15")) {
  mod_my <- Filter(function(mod) { target <- edge_for_id(mod$targetEdgeId); identical(target$to, y_node$id) && identical(target$from, m_node$id) }, spec$moderations)[[1]]
  mod_xy <- Filter(function(mod) { target <- edge_for_id(mod$targetEdgeId); identical(target$to, y_node$id) && identical(target$from, x_node$id) }, spec$moderations)[[1]]

  a1 <- unname(coef(fits$m)[[x_node$id]])
  b1 <- unname(coef(fits$y)[[m_node$id]])
  b3 <- unname(coef(fits$y)[[mod_my$productTermId]])

  conditional <- vapply(seq_along(representative_model), function(index) a1 * (b1 + b3 * representative_model[[index]]), numeric(1))
  index_value <- a1 * b3
} else if (template %in% c("model_21", "model_22")) {
  mod_xm <- Filter(function(mod) {
    target <- edge_for_id(mod$targetEdgeId)
    identical(target$from, x_node$id) && identical(target$to, m_node$id)
  }, spec$moderations)[[1]]
  mod_my <- Filter(function(mod) {
    target <- edge_for_id(mod$targetEdgeId)
    identical(target$from, m_node$id) && identical(target$to, y_node$id)
  }, spec$moderations)[[1]]

  z_original <- original_values[[z_node$id]]
  z_representative_original <- process_representative_values(z_original)
  z_center <- if (is.null(centering_means[[z_node$id]])) {
    0
  } else {
    centering_means[[z_node$id]]
  }
  z_representative_model <- z_representative_original - z_center
  conditional_w_model <- rep(representative_model, each = 3)
  conditional_z_model <- rep(z_representative_model, times = 3)
  conditional_labels <- paste0(
    "W_", rep(names(representative_original), each = 3),
    "__Z_", rep(names(z_representative_original), times = 3)
  )

  a1 <- unname(coef(fits$m)[[x_node$id]])
  a3 <- unname(coef(fits$m)[[mod_xm$productTermId]])
  b1 <- unname(coef(fits$y)[[m_node$id]])
  b3 <- unname(coef(fits$y)[[mod_my$productTermId]])
  conditional <- (a1 + a3 * conditional_w_model) *
    (b1 + b3 * conditional_z_model)
  names(conditional) <- conditional_labels
} else if (template %in% c("model_58", "model_59")) {
  mod_xm <- Filter(function(mod) {
    target <- edge_for_id(mod$targetEdgeId)
    identical(target$from, x_node$id) && identical(target$to, m_node$id)
  }, spec$moderations)[[1]]
  mod_my <- Filter(function(mod) {
    target <- edge_for_id(mod$targetEdgeId)
    identical(target$from, m_node$id) && identical(target$to, y_node$id)
  }, spec$moderations)[[1]]

  a1 <- unname(coef(fits$m)[[x_node$id]])
  a3 <- unname(coef(fits$m)[[mod_xm$productTermId]])
  b1 <- unname(coef(fits$y)[[m_node$id]])
  b3 <- unname(coef(fits$y)[[mod_my$productTermId]])
  conditional <- vapply(
    seq_along(representative_model),
    function(index) {
      value <- representative_model[[index]]
      (a1 + a3 * value) * (b1 + b3 * value)
    },
    numeric(1)
  )
} else if (!is.null(m_node)) {
  a <- unname(coef(fits$m)[[x_node$id]])
  b <- unname(coef(fits$y)[[m_node$id]])
  direct <- unname(coef(fits$y)[[x_node$id]])
  if (template %in% c("model_4", "model_5")) indirect <- a * b
  if (identical(template, "model_7")) {
    interaction <- unname(coef(fits$m)[[moderation$productTermId]])
    conditional <- vapply(seq_along(representative_model), function(index) (a + interaction * representative_model[[index]]) * b, numeric(1))
    index_value <- interaction * b
  }
  if (identical(template, "model_14")) {
    interaction <- unname(coef(fits$y)[[moderation$productTermId]])
    conditional <- vapply(seq_along(representative_model), function(index) a * (b + interaction * representative_model[[index]]), numeric(1))
    index_value <- a * interaction
  }
}

if (!is.null(m_node) || identical(template, "model_6")) {
  if (!isTRUE(bootstrap_config$enabled)) stop("Mediation models require bootstrap.enabled=true")
  set.seed(researchpath_seed(bootstrap_config$seed))

  # Compile each frozen equation to a design matrix once. Rebuilding formulas,
  # contrasts and full lm/glm objects thousands of times is unnecessary: row
  # bootstrap changes observations, not the model matrix definition.
  bootstrap_designs <- lapply(plans, function(plan) {
    formula <- reformulate(plan$predictors, response = plan$outcome)
    list(
      x = model.matrix(formula, data = analysis_data),
      y = analysis_data[[plan$outcome]],
      binary = plan$outcome %in% binary_node_ids
    )
  })
  ncol_boot <- 4
  if (template %in% c("model_4", "model_5")) ncol_boot <- 1
  if (template %in% c("model_58", "model_59")) ncol_boot <- 3
  if (template %in% c("model_21", "model_22")) ncol_boot <- 9
  interaction_equation <- NULL
  interaction_term <- NULL
  a_interaction_term <- NULL
  b_interaction_term <- NULL
  if (template %in% c("model_7", "model_8")) {
    interaction_equation <- "m"
    selected <- if (identical(template, "model_7")) moderation else Filter(
      function(mod) identical(edge_for_id(mod$targetEdgeId)$to, m_node$id),
      spec$moderations
    )[[1]]
    interaction_term <- selected$productTermId
  } else if (template %in% c("model_14", "model_15")) {
    interaction_equation <- "y"
    selected <- if (identical(template, "model_14")) moderation else Filter(
      function(mod) {
        target <- edge_for_id(mod$targetEdgeId)
        identical(target$to, y_node$id) && identical(target$from, m_node$id)
      },
      spec$moderations
    )[[1]]
    interaction_term <- selected$productTermId
  } else if (template %in% c("model_21", "model_22", "model_58", "model_59")) {
    a_interaction_term <- Filter(
      function(mod) {
        target <- edge_for_id(mod$targetEdgeId)
        identical(target$from, x_node$id) && identical(target$to, m_node$id)
      },
      spec$moderations
    )[[1]]$productTermId
    b_interaction_term <- Filter(
      function(mod) {
        target <- edge_for_id(mod$targetEdgeId)
        identical(target$from, m_node$id) && identical(target$to, y_node$id)
      },
      spec$moderations
    )[[1]]$productTermId
  }
  bootstrap_replicate <- researchpath_make_bootstrap_callback(
    bootstrap_designs,
    list(
      template = template,
      xId = x_node$id,
      mId = if (is.null(m_node)) NULL else m_node$id,
      m1Id = if (is.null(m1)) NULL else m1$id,
      m2Id = if (is.null(m2)) NULL else m2$id,
      interactionEquation = interaction_equation,
      interactionTerm = interaction_term,
      aInteractionTerm = a_interaction_term,
      bInteractionTerm = b_interaction_term,
      representative = if (exists("representative_model")) representative_model else numeric(0),
      representativeA = if (exists("conditional_w_model")) conditional_w_model else numeric(0),
      representativeB = if (exists("conditional_z_model")) conditional_z_model else numeric(0),
      outputColumns = ncol_boot,
      sampleSize = included_n
    )
  )

  bootstrap_parallel <- researchpath_parallel_profile(replicates)
  bootstrap_work_units <- as.double(replicates) * as.double(included_n) * as.double(length(plans))
  if (!researchpath_use_parallel(bootstrap_work_units, replicates)) {
    bootstrap_parallel$backend <- "sequential"
    bootstrap_parallel$workers <- 1L
  }
  bootstrap_values <- matrix(NA_real_, nrow = replicates, ncol = ncol_boot)
  replicate_seeds <- sample.int(.Machine$integer.max, replicates, replace = TRUE)
  samples_per_batch <- min(replicates, 5000L)
  bootstrap_chunks <- researchpath_parallel_chunks(
    replicates,
    1L,
    tasks_per_worker = samples_per_batch
  )
  for (chunk in bootstrap_chunks) {
    check_cancel()
    chunk_values <- researchpath_parallel_grouped_lapply(
      as.list(replicate_seeds[chunk]),
      bootstrap_replicate,
      bootstrap_parallel$workers
    )
    for (offset in seq_along(chunk)) {
      bootstrap_values[chunk[[offset]], ] <- chunk_values[[offset]]
    }
    completed <- max(chunk)
    write_progress(
      "bootstrapping",
      0.25 + 0.65 * completed / replicates,
      completed,
      replicates
    )
  }

  if (template %in% c("model_4", "model_5")) {
    interval <- bootstrap_interval(bootstrap_values[, 1], indirect)
    effects[[length(effects) + 1]] <- list(
      id = "effect_indirect", type = "indirect", label = "a_x_b", estimate = indirect,
      standardError = sd(interval$values),
      confidenceInterval = list(level = spec$estimation$confidenceLevel, lower = interval$lower, upper = interval$upper, method = interval$method, replicates = replicates, seed = researchpath_seed(bootstrap_config$seed))
    )
    if (identical(template, "model_4")) {
      controls_y <- character(0)
      for (assignment in spec$covariates) if (y_node$id %in% unlist(assignment$outcomeNodeIds)) controls_y <- c(controls_y, assignment$nodeId)
      total_fit <- fit_plan(analysis_data, list(outcome = y_node$id, predictors = unique(c(x_node$id, controls_y))))
      effects[[length(effects) + 1]] <- list(id = "effect_total", type = "total", label = "c", estimate = unname(coef(total_fit)[[x_node$id]]))
    }
  } else if (identical(template, "model_6")) {
    int_1 <- bootstrap_interval(bootstrap_values[, 1], indirect_1)
    effects[[length(effects) + 1]] <- list(
      id = "effect_indirect_1", type = "indirect", label = "ind1: X -> M1 -> Y", estimate = indirect_1,
      standardError = sd(int_1$values), confidenceInterval = list(level = spec$estimation$confidenceLevel, lower = int_1$lower, upper = int_1$upper, method = int_1$method, replicates = replicates, seed = researchpath_seed(bootstrap_config$seed))
    )
    int_2 <- bootstrap_interval(bootstrap_values[, 2], indirect_2)
    effects[[length(effects) + 1]] <- list(
      id = "effect_indirect_2", type = "indirect", label = "ind2: X -> M2 -> Y", estimate = indirect_2,
      standardError = sd(int_2$values), confidenceInterval = list(level = spec$estimation$confidenceLevel, lower = int_2$lower, upper = int_2$upper, method = int_2$method, replicates = replicates, seed = researchpath_seed(bootstrap_config$seed))
    )
    int_3 <- bootstrap_interval(bootstrap_values[, 3], indirect_3)
    effects[[length(effects) + 1]] <- list(
      id = "effect_indirect_3", type = "indirect", label = "ind3: X -> M1 -> M2 -> Y", estimate = indirect_3,
      standardError = sd(int_3$values), confidenceInterval = list(level = spec$estimation$confidenceLevel, lower = int_3$lower, upper = int_3$upper, method = int_3$method, replicates = replicates, seed = researchpath_seed(bootstrap_config$seed))
    )
    int_tot <- bootstrap_interval(bootstrap_values[, 4], total_indirect)
    effects[[length(effects) + 1]] <- list(
      id = "effect_total_indirect", type = "indirect", label = "total indirect effect", estimate = total_indirect,
      standardError = sd(int_tot$values), confidenceInterval = list(level = spec$estimation$confidenceLevel, lower = int_tot$lower, upper = int_tot$upper, method = int_tot$method, replicates = replicates, seed = researchpath_seed(bootstrap_config$seed))
    )

    contrast_definitions <- list(
      list(id = "effect_contrast_ind1_ind2", left = 1L, right = 2L, estimate = indirect_1 - indirect_2, label = "ind1 - ind2"),
      list(id = "effect_contrast_ind1_ind3", left = 1L, right = 3L, estimate = indirect_1 - indirect_3, label = "ind1 - ind3"),
      list(id = "effect_contrast_ind2_ind3", left = 2L, right = 3L, estimate = indirect_2 - indirect_3, label = "ind2 - ind3")
    )
    for (contrast in contrast_definitions) {
      contrast_values <- bootstrap_values[, contrast$left] - bootstrap_values[, contrast$right]
      contrast_interval <- bootstrap_interval(contrast_values, contrast$estimate)
      effects[[length(effects) + 1]] <- list(
        id = contrast$id, type = "contrast", label = contrast$label, estimate = contrast$estimate,
        standardError = sd(contrast_interval$values),
        confidenceInterval = list(
          level = spec$estimation$confidenceLevel,
          lower = contrast_interval$lower,
          upper = contrast_interval$upper,
          method = contrast_interval$method,
          replicates = replicates,
          seed = researchpath_seed(bootstrap_config$seed)
        )
      )
    }

    controls_y <- character(0)
    for (assignment in spec$covariates) if (y_node$id %in% unlist(assignment$outcomeNodeIds)) controls_y <- c(controls_y, assignment$nodeId)
    total_fit <- fit_plan(analysis_data, list(outcome = y_node$id, predictors = unique(c(x_node$id, controls_y))))
    effects[[length(effects) + 1]] <- list(id = "effect_total", type = "total", label = "c", estimate = unname(coef(total_fit)[[x_node$id]]))
  } else if (template %in% c("model_21", "model_22", "model_58", "model_59")) {
    effect_labels <- if (exists("conditional_labels")) {
      conditional_labels
    } else {
      names(representative_original)
    }
    for (index in seq_along(conditional)) {
      interval <- bootstrap_interval(bootstrap_values[, index], conditional[[index]])
      effects[[length(effects) + 1]] <- list(
        id = paste0("effect_conditional_", effect_labels[[index]]),
        type = "conditional",
        label = paste0("conditional_indirect_", effect_labels[[index]]),
        estimate = unname(conditional[[index]]),
        standardError = sd(interval$values),
        confidenceInterval = list(
          level = spec$estimation$confidenceLevel,
          lower = interval$lower,
          upper = interval$upper,
          method = interval$method,
          replicates = replicates,
          seed = researchpath_seed(bootstrap_config$seed)
        )
      )
    }
  } else {
    for (index in seq_along(conditional)) {
      interval <- bootstrap_interval(bootstrap_values[, index], conditional[[index]])
      effects[[length(effects) + 1]] <- list(
        id = paste0("effect_conditional_", names(representative_original)[[index]]), type = "conditional", label = paste0("conditional_indirect_", names(representative_original)[[index]]), estimate = unname(conditional[[index]]),
        standardError = sd(interval$values), confidenceInterval = list(level = spec$estimation$confidenceLevel, lower = interval$lower, upper = interval$upper, method = interval$method, replicates = replicates, seed = researchpath_seed(bootstrap_config$seed))
      )
    }
    index_interval <- bootstrap_interval(bootstrap_values[, 4], index_value)
    effects[[length(effects) + 1]] <- list(
      id = "effect_index", type = "index", label = "index_of_moderated_mediation", estimate = index_value,
      standardError = sd(index_interval$values), confidenceInterval = list(level = spec$estimation$confidenceLevel, lower = index_interval$lower, upper = index_interval$upper, method = index_interval$method, replicates = replicates, seed = researchpath_seed(bootstrap_config$seed))
    )
  }
}
}

warnings <- researchpath_process_warnings(
  hc3_unavailable_warnings, dropped_bootstrap_replications, replicates, spec, m_node, m1,
  binary_level_mappings, y_node, binary_node_ids
)

write_progress("building_result", 0.95, if (!is.null(m_node) || !is.null(m1)) replicates else 0L, if (!is.null(m_node) || !is.null(m1)) replicates else 0L)
evidence_metadata <- researchpath_process_effect_metadata(effects, spec, payload, template)
effects <- evidence_metadata$effects
bootstrap_requested <- if (isTRUE(bootstrap_config$enabled)) replicates else 0L
bootstrap_invalid <- as.integer(dropped_bootstrap_replications)
bootstrap_metadata <- researchpath_bootstrap_metadata(
  bootstrap_config, bootstrap_requested, bootstrap_invalid, spec$estimation$confidenceLevel
)
publication_reasons <- unique(c(
  evidence_metadata$publicationReasons,
  if (bootstrap_invalid > 0L) "BOOTSTRAP_REPLICATION_DROPPED" else character(0)
))
result <- list(
  schemaVersion = "0.2.0",
  run = list(id = payload$runId, status = "succeeded", modelId = spec$modelId, modelHash = payload$modelHash, modelVersionId = if (is.null(payload$modelVersionId)) "demo" else payload$modelVersionId, template = template, durationMilliseconds = as.integer((proc.time()[[3]] - started_at) * 1000)),
  sampleFlow = list(
    original = original_n, selected = original_n, included = included_n,
    excluded = original_n - included_n, missingRows = missing_rows, finalN = included_n,
    missingMethod = spec$estimation$missing,
    variableMissingCounts = as.list(missing_variable_counts), missingPatterns = missing_patterns
  ),
  equations = equations,
  diagnostics = diagnostics,
  effects = effects,
  publicationEligible = length(publication_reasons) == 0L,
  requiresManualReview = length(publication_reasons) > 0L,
  publicationEligibilityReasons = as.list(publication_reasons),
  claimBoundary = evidence_metadata$claimBoundary,
  bootstrap = bootstrap_metadata,
  evidenceGraph = evidence_metadata$evidenceGraph,
  probes = probes,
  moderationPlots = moderation_plots,
  johnsonNeyman = jn_result,
  johnsonNeymanResults = jn_results,
  moderator = moderator_summary,
  warnings = warnings,
  provenance = researchpath_process_provenance(
    spec, payload, hc3_unavailable_warnings, bootstrap_config, replicates, process5_manifest,
    if (exists("bootstrap_parallel")) bootstrap_parallel else list(backend = "sequential", workers = 1L, rngStrategy = "not applicable")
  )
)

researchpath_write_result(result, output_path)
write_progress("succeeded", 1, if (!is.null(m_node) || !is.null(m1)) replicates else 0L, if (!is.null(m_node) || !is.null(m1)) replicates else 0L)
