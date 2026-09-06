"""Generate analytic-power goldens without calling the ResearchPath R engine.

The product implementation delegates to R pwr. This oracle evaluates the
noncentral t and F distributions through SciPy and solves the declared design
equations independently. Regeneration is a reviewed action; CI only consumes
the checked-in JSON.
"""

from __future__ import annotations

import json
import math
from functools import partial
from pathlib import Path
from typing import Any, Callable

import scipy
from scipy.optimize import brentq
from scipy.stats import f, ncf, nct, t

ALPHA = 0.05
DEFAULT_TARGET = 0.8


def regression_power(total_n: int, predictors: int, effect_f2: float) -> float:
    denominator_df = total_n - predictors - 1
    critical = f.ppf(1 - ALPHA, predictors, denominator_df)
    noncentrality = effect_f2 * (predictors + denominator_df + 1)
    return float(ncf.sf(critical, predictors, denominator_df, noncentrality))


def t_test_power(total_n: int, groups: int, effect_d: float) -> float:
    per_group = total_n / groups
    denominator_df = per_group - 1 if groups == 1 else 2 * per_group - 2
    noncentrality = effect_d * math.sqrt(per_group if groups == 1 else per_group / 2)
    critical = t.ppf(1 - ALPHA / 2, denominator_df)
    return float(
        nct.sf(critical, denominator_df, noncentrality)
        + nct.cdf(-critical, denominator_df, noncentrality)
    )


def anova_power(total_n: int, groups: int, effect_f: float) -> float:
    per_group = total_n / groups
    numerator_df = groups - 1
    denominator_df = groups * (per_group - 1)
    critical = f.ppf(1 - ALPHA, numerator_df, denominator_df)
    noncentrality = total_n * effect_f**2
    return float(ncf.sf(critical, numerator_df, denominator_df, noncentrality))


def first_total_n(start: int, step: int, power: Callable[[int], float], target: float) -> int:
    for total_n in range(start, 100_001, step):
        if power(total_n) >= target:
            return total_n
    raise RuntimeError("No sample-size solution within the declared search range")


def sensitivity(power: Callable[[float], float], target: float) -> float:
    upper = 1.0
    while power(upper) < target:
        upper *= 2
    return float(brentq(lambda effect: power(effect) - target, 1e-12, upper, xtol=1e-14))


def precision_sample_size(target_width: float, confidence: float, sd: float, groups: int) -> int:
    margin = target_width / 2
    normal_critical = 1.959963984540054
    current = max(4, math.ceil((normal_critical * sd / margin) ** 2 * groups))
    for _ in range(20):
        denominator_df = current - 1 if groups == 1 else current - 2
        critical = t.ppf(1 - (1 - confidence) / 2, max(1, denominator_df))
        updated = math.ceil((critical * sd / margin) ** 2 * groups)
        if updated == current:
            break
        current = updated
    return current


def cases() -> list[dict[str, Any]]:
    specifications: list[dict[str, Any]] = [
        {"id": "regression_sample_size_f2_015", "designFamily": "regression", "solveFor": "sample_size", "effectSize": {"metric": "cohens_f2", "value": 0.15}, "predictors": 3, "groups": 1},
        {"id": "regression_power_f2_010_n120", "designFamily": "regression", "solveFor": "power", "effectSize": {"metric": "cohens_f2", "value": 0.1}, "sampleSize": 120, "predictors": 5, "groups": 1},
        {"id": "regression_sensitivity_f2_n80", "designFamily": "regression", "solveFor": "sensitivity", "effectSize": "cohens_f2", "effectSizeMetric": "cohens_f2", "sampleSize": 80, "predictors": 2, "groups": 1},
        {"id": "regression_sensitivity_r2change_n100", "designFamily": "regression", "solveFor": "sensitivity", "effectSize": "r_squared_change", "effectSizeMetric": "r_squared_change", "sampleSize": 100, "predictors": 4, "groups": 1, "targetPower": 0.9},
        {"id": "ttest_onesample_sample_size_d05", "designFamily": "t_test", "solveFor": "sample_size", "effectSize": {"metric": "cohens_d", "value": 0.5}, "groups": 1},
        {"id": "ttest_twosample_sample_size_d05", "designFamily": "t_test", "solveFor": "sample_size", "effectSize": {"metric": "cohens_d", "value": 0.5}, "groups": 2},
        {"id": "ttest_twosample_power_d03_n176", "designFamily": "t_test", "solveFor": "power", "effectSize": {"metric": "cohens_d", "value": 0.3}, "sampleSize": 176, "groups": 2},
        {"id": "ttest_onesample_sensitivity_n60", "designFamily": "t_test", "solveFor": "sensitivity", "effectSize": "cohens_d", "effectSizeMetric": "cohens_d", "sampleSize": 60, "groups": 1},
        {"id": "anova_sample_size_f025_k3", "designFamily": "factorial_anova", "solveFor": "sample_size", "effectSize": {"metric": "cohens_f", "value": 0.25}, "groups": 3},
        {"id": "anova_power_f020_n160_k4", "designFamily": "factorial_anova", "solveFor": "power", "effectSize": {"metric": "cohens_f", "value": 0.2}, "sampleSize": 160, "groups": 4},
        {"id": "anova_sensitivity_n120_k3", "designFamily": "factorial_anova", "solveFor": "sensitivity", "effectSize": "cohens_f", "effectSizeMetric": "cohens_f", "sampleSize": 120, "groups": 3},
        {"id": "precision_ci_width_050", "designFamily": "regression", "solveFor": "ci_width", "targetCIWidth": 0.5, "confidenceLevel": 0.95, "sd": 1, "groups": 1},
    ]
    for case in specifications:
        target = float(case.get("targetPower", DEFAULT_TARGET))
        family = case["designFamily"]
        solve_for = case["solveFor"]
        if solve_for == "ci_width":
            solved = precision_sample_size(case["targetCIWidth"], case["confidenceLevel"], case["sd"], case["groups"])
            case["expected"] = {"solvedValue": solved}
            continue
        if family == "regression":
            predictors = case["predictors"]
            if solve_for == "sample_size":
                effect = case["effectSize"]["value"]
                solved = first_total_n(
                    predictors + 2,
                    1,
                    partial(regression_power, predictors=predictors, effect_f2=effect),
                    target,
                )
                achieved = regression_power(solved, predictors, effect)
            elif solve_for == "power":
                solved = case["sampleSize"]
                achieved = regression_power(solved, predictors, case["effectSize"]["value"])
            else:
                raw = sensitivity(
                    partial(regression_power, case["sampleSize"], predictors), target
                )
                solved = raw / (1 + raw) if case["effectSizeMetric"] == "r_squared_change" else raw
                achieved = target
        elif family == "t_test":
            groups = case["groups"]
            if solve_for == "sample_size":
                effect = case["effectSize"]["value"]
                solved = first_total_n(
                    2 if groups == 1 else 4,
                    groups,
                    partial(t_test_power, groups=groups, effect_d=effect),
                    target,
                )
                achieved = t_test_power(solved, groups, effect)
            elif solve_for == "power":
                solved = case["sampleSize"]
                achieved = t_test_power(solved, groups, case["effectSize"]["value"])
            else:
                solved = sensitivity(
                    partial(t_test_power, case["sampleSize"], groups), target
                )
                achieved = target
        else:
            groups = case["groups"]
            if solve_for == "sample_size":
                effect = case["effectSize"]["value"]
                solved = first_total_n(
                    groups * 2,
                    groups,
                    partial(anova_power, groups=groups, effect_f=effect),
                    target,
                )
                achieved = anova_power(solved, groups, effect)
            elif solve_for == "power":
                solved = case["sampleSize"]
                achieved = anova_power(solved, groups, case["effectSize"]["value"])
            else:
                solved = sensitivity(
                    partial(anova_power, case["sampleSize"], groups), target
                )
                achieved = target
        case["expected"] = {"solvedValue": solved}
        if solve_for in {"sample_size", "power"}:
            case["expected"]["achievedPower"] = achieved
    return specifications


def main() -> None:
    payload = {
        "schemaVersion": "1.1.0",
        "provenance": {
            "oracle": "SciPy noncentral t/F distributions with independent root solving",
            "scipyVersion": scipy.__version__,
            "generator": "engine/R/tests/reference/generate-power-independent-goldens.py",
            "independence": "Python SciPy evaluates the reference equations directly and does not call the R engine or any product runner.",
            "note": "Covers analytic regression, one/two-sample t, balanced between-group ANOVA, sensitivity, ceiling rules, and CI-width iteration; Monte Carlo power is outside this golden.",
            "tolerance": {"solvedValue": 1e-9, "achievedPower": 1e-9},
        },
        "cases": cases(),
    }
    destination = Path(__file__).with_name("power-goldens-v1.json")
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
