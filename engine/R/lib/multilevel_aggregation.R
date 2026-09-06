# ResearchPath R Engine - Multilevel Aggregation Evidence & ICC/rwg
#
# The advanced workbench delegates the statistical calculation to the same
# implementation used by the empirical workspace.  This prevents rwg(j) from
# drifting when a construct score is a mean rather than a sum and deliberately
# returns evidence instead of a threshold-based aggregation verdict.

calc_multilevel_aggregation <- function(
  data,
  outcome_var,
  cluster_var,
  scale_min = 1,
  scale_max = 5,
  item_count = 1L,
  aggregation_method = "mean"
) {
  if (!outcome_var %in% colnames(data) || !cluster_var %in% colnames(data)) {
    stop("AGGREGATION_COLUMN_NOT_FOUND")
  }
  if (!is.finite(item_count) || item_count < 1L) {
    stop("AGGREGATION_ITEM_COUNT_INVALID")
  }
  if (!aggregation_method %in% c("mean", "sum")) {
    stop("AGGREGATION_METHOD_INVALID")
  }

  evidence <- calc_aggregation_diagnostics(
    data = data,
    outcome_id = outcome_var,
    outcome_label = outcome_var,
    cluster_id = cluster_var,
    scale_min = scale_min,
    scale_max = scale_max,
    item_count = as.integer(item_count),
    aggregation_method = aggregation_method
  )
  if (!isTRUE(evidence$available)) {
    stop(evidence$reasonCode)
  }

  expected_item_variance <- (round(scale_max - scale_min + 1)^2 - 1) / 12
  list(
    outcomeVariable = outcome_var,
    clusterVariable = cluster_var,
    observations = evidence$observations,
    scale = list(
      min = scale_min,
      max = scale_max,
      itemCount = as.integer(item_count),
      scoreAggregation = aggregation_method,
      expectedItemVariance = as.numeric(expected_item_variance),
      expectedScoreVariance = evidence$rwg$expectedScoreVariance
    ),
    numClusters = evidence$clusterCount,
    eligibleRwgClusterCount = evidence$eligibleRwgClusterCount,
    minimumClusterSize = evidence$minimumClusterSize,
    maximumClusterSize = evidence$maximumClusterSize,
    averageClusterSize = evidence$averageClusterSize,
    icc1 = evidence$icc1,
    icc2 = evidence$icc2,
    designEffect = evidence$designEffect,
    rwgByCluster = evidence$rwg$byCluster,
    meanRwg = evidence$rwg$mean,
    medianRwg = evidence$rwg$median,
    proportionRwgAtLeastPoint70 = evidence$rwg$proportionAtLeastPoint70,
    interpretation = evidence$interpretation,
    diagnosticMessage = paste(
      "ICC 与 rwg(j) 已按声明的题项数和计分规则计算；",
      "这些统计量是聚合证据，不构成自动聚合许可。"
    )
  )
}
