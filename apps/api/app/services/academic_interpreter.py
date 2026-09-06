from __future__ import annotations

from typing import Any

from app.services.academic_reporting_audit import append_auditable_fact_tables


def f(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (ValueError, TypeError):
        return str(value)


def format_p(value: Any) -> str:
    if value is None:
        return "—"
    try:
        probability = float(value)
        return "< .001" if probability < 0.001 else f"{probability:.3f}".replace("0.", ".")
    except (ValueError, TypeError):
        return str(value)


def confidence_label(value: float | int | str | None, default: float = 0.95) -> str:
    """Render the declared confidence level without silently relabelling it as 95%."""
    if value is None:
        level = default
    else:
        try:
            level = float(value)
        except ValueError:
            level = default
    percent = level * 100
    return f"{percent:.2f}".rstrip("0").rstrip(".") + "% CI"


def _interval_excludes_zero(interval: dict[str, Any] | None) -> bool | None:
    if not interval or interval.get("lower") is None or interval.get("upper") is None:
        return None
    lower = float(interval["lower"])
    upper = float(interval["upper"])
    return lower > 0 or upper < 0


def _model_uses_logit(result: dict[str, Any]) -> bool:
    return any(
        equation.get("modelFamily") == "binomial_logit"
        or coefficient.get("confidenceInterval", {}).get("method") in {"wald_z", "hc3_z"}
        for equation in result.get("equations", [])
        for coefficient in equation.get("coefficients", [])
    )


def _effect_by_id(result: dict[str, Any], effect_id: str) -> dict[str, Any] | None:
    return next(
        (effect for effect in result.get("effects", []) if effect.get("id") == effect_id), None
    )


def _append_effect_table(tables: list[str], effects: list[dict[str, Any]]) -> None:
    reportable = [effect for effect in effects if effect.get("confidenceInterval")]
    if not reportable:
        return
    tables.append("### 表：Bootstrap 效应与置信区间\n\n")
    tables.append("| 效应 | 估计值 | 下限 | 上限 | 区间是否排除 0 |\n|---|---:|---:|---:|:---:|\n")
    for effect in reportable:
        interval = effect["confidenceInterval"]
        excludes_zero = _interval_excludes_zero(interval)
        tables.append(
            f"| {effect.get('label', effect.get('id', ''))} | {f(effect.get('estimate'))} | "
            f"{f(interval.get('lower'))} | {f(interval.get('upper'))} | "
            f"{'是' if excludes_zero else '否' if excludes_zero is False else '不可判断'} |\n"
        )
    tables.append("\n")


def generate_interpretation_assets(
    result: dict[str, Any], model_spec: dict[str, Any]
) -> tuple[str, str]:
    """Generate deterministic, result-type-aware prose without inventing methods or claims."""
    if result.get("options", {}).get("procedure"):
        from app.services.empirical_procedure_reporting import procedure_interpretation

        return procedure_interpretation(result)
    run = result.get("run") or {}
    template = run.get("template")
    if template is None and result.get("descriptives") is not None:
        template = "empirical"
    template = template or "unknown"

    tables: list[str] = []
    paragraphs: list[str] = []

    if template == "empirical":
        sample = result.get("sample", {})
        options = result.get("options", {})
        paragraphs.append("## 问卷实证证据摘要\n\n")
        paragraphs.append(
            f"本报告基于 {sample.get('rowCount', '—')} 条记录和 "
            f"{sample.get('constructCount', '—')} 个构念生成。相关分析采用 "
            f"{options.get('correlationMethod', 'pearson')} 方法；不同分析区块可能使用成对或区块完整观测，"
            "具体有效样本量应以各表所列 N 为准。\n\n"
        )
        factorability = result.get("factorability", {})
        efa = result.get("efa", {})
        paragraphs.append(
            f"KMO={f(factorability.get('kmo'))}，Bartlett 球形检验 "
            f"p={format_p(factorability.get('bartlett', {}).get('pValue'))}。"
            f"EFA 使用 {efa.get('method', '—')}，提取 {efa.get('factorCount', '—')} 个因子。"
        )
        cfa = result.get("cfa", {})
        if cfa.get("available"):
            paragraphs.append(
                f" 简单结构 CFA 得到 CFI={f(cfa.get('cfi'))}、TLI={f(cfa.get('tli'))}、"
                f"RMSEA={f(cfa.get('rmsea'))}、SRMR={f(cfa.get('srmr'))}。"
            )
            if cfa.get("validForConfirmatoryInterpretation") is False:
                adequacy = sample.get("measurementAdequacy", {})
                paragraphs.append(
                    f" 但完整案例 N={adequacy.get('completeCases', '—')}、"
                    f"每自由参数案例数={f(adequacy.get('casesPerParameter'), 2)}，"
                    "未达到平台的保守确认性解释护栏；该护栏不是通用样本量定理，"
                    "当前 CFA 仅宜作探索或流程演示。"
                )
        else:
            paragraphs.append(f" CFA 未能估计：{cfa.get('reason', '原因未记录')}。")
        paragraphs.append("这些结果是测量证据，不应单独用于证明共同方法偏差不存在或支持因果关系。")
        aggregation = result.get("aggregationDiagnostics")
        if aggregation:
            available = [
                row for row in aggregation.get("constructs", []) if row.get("available")
            ]
            paragraphs.append(
                f"\n\n以“{aggregation.get('groupLabel', '分组变量')}”作为 cluster 标识，"
                f"共为 {len(available)} 个构念计算 ICC(1)、ICC(2)、设计效应与 rwg(j)。"
                "这些指标用于描述组内依赖和一致性，不能脱离构念层级理论自动决定是否聚合。"
            )

        tables.append("### 表：构念信效度摘要\n\n")
        tables.append("| 构念 | α | ω | CR | AVE | 结论状态 |\n|---|---:|---:|---:|---:|:---:|\n")
        for construct in result.get("validity", {}).get("constructs", []):
            status = construct.get("discriminantValidityStatus")
            if status is None:
                fallback = construct.get("discriminantValidityPass")
                status = (
                    "pass" if fallback is True else "fail" if fallback is False else "not_evaluable"
                )
            tables.append(
                f"| {construct.get('label', '')} | {f(construct.get('alpha'))} | "
                f"{f(construct.get('omega'))} | {f(construct.get('compositeReliability'))} | "
                f"{f(construct.get('averageVarianceExtracted'))} | {status} |\n"
            )
        if aggregation:
            tables.append("\n### 表：团队/组织层级聚合诊断\n\n")
            tables.append(
                "| 构念 | cluster 数 | 平均规模 | ICC(1) | ICC(2) | 设计效应 | "
                "平均 rwg(j) | 中位 rwg(j) |\n"
                "|---|---:|---:|---:|---:|---:|---:|---:|\n"
            )
            for row in aggregation.get("constructs", []):
                rwg = row.get("rwg", {})
                tables.append(
                    f"| {row.get('label', '')} | {row.get('clusterCount', '—')} | "
                    f"{f(row.get('averageClusterSize'))} | {f(row.get('icc1'))} | "
                    f"{f(row.get('icc2'))} | {f(row.get('designEffect'))} | "
                    f"{f(rwg.get('mean'))} | {f(rwg.get('median'))} |\n"
                )
        append_auditable_fact_tables(tables, result)
        return "".join(paragraphs), "".join(tables)

    if template == "sem" and result.get("semResult"):
        sem = result["semResult"]
        fit = sem.get("fitIndices", {})
        estimator = model_spec.get("estimation", {}).get("estimator", "ML")
        confidence = (result.get("provenance") or {}).get(
            "confidenceLevel", model_spec.get("estimation", {}).get("confidenceLevel", 0.95)
        )
        interval_label = confidence_label(confidence)
        paragraphs.append("## 结构方程模型结果摘要\n\n")
        if (result.get("claimBoundary") or {}).get("claimMode") == "association":
            paragraphs.append("本模型仅提供关联性证据；横截面数据不建立时间顺序，不生成‘导致’、‘机制’或‘因果效应’结论。\n\n")
        paragraphs.append(
            f"模型使用 {estimator} 估计。χ²({fit.get('df', '—')})={f(fit.get('chiSquare'))}，"
            f"p={format_p(fit.get('pValue'))}，CFI={f(fit.get('cfi'))}，"
            f"TLI={f(fit.get('tli'))}，RMSEA={f(fit.get('rmsea'))}，SRMR={f(fit.get('srmr'))}。"
            "拟合指标应结合模型复杂度、样本量、参数合理性和理论依据共同解释。\n\n"
        )
        significant_paths = [
            path
            for path in sem.get("paths", [])
            if path.get("pValue") is not None and path["pValue"] < 0.05
        ]
        paragraphs.append(
            f"结构模型共估计 {len(sem.get('paths', []))} 条路径，其中 "
            f"{len(significant_paths)} 条路径的双侧检验 p<.05；该描述不等同于因果证明或假设自动成立。"
        )

        tables.append("### 表：结构方程模型拟合指标\n\n")
        tables.append(
            "| χ² | df | p | CFI | TLI | RMSEA | SRMR |\n|---:|---:|---:|---:|---:|---:|---:|\n"
        )
        tables.append(
            f"| {f(fit.get('chiSquare'))} | {fit.get('df', '—')} | {format_p(fit.get('pValue'))} | "
            f"{f(fit.get('cfi'))} | {f(fit.get('tli'))} | {f(fit.get('rmsea'))} | {f(fit.get('srmr'))} |\n\n"
        )
        tables.append("### 表：SEM 结构路径\n\n")
        tables.append(
            f"| 路径 | B | SE | z | p | β | {interval_label} |\n"
            "|---|---:|---:|---:|---:|---:|---:|\n"
        )
        for path in sem.get("paths", []):
            tables.append(
                f"| {path.get('from')} → {path.get('to')} | {f(path.get('estimate'))} | "
                f"{f(path.get('standardError'))} | {f(path.get('statistic'))} | "
                f"{format_p(path.get('pValue'))} | {f(path.get('stdAll'))} | "
                f"[{f(path.get('ciLower'))}, {f(path.get('ciUpper'))}] |\n"
            )
        invariance = result.get("invarianceResult")
        if invariance:
            comparison_by_model = {
                "metric": next(
                    (
                        item
                        for item in invariance.get("comparisons", [])
                        if item.get("comparison") == "metric_vs_configural"
                    ),
                    {},
                ),
                "scalar": next(
                    (
                        item
                        for item in invariance.get("comparisons", [])
                        if item.get("comparison") == "scalar_vs_metric"
                    ),
                    {},
                ),
                "strict": next(
                    (
                        item
                        for item in invariance.get("comparisons", [])
                        if item.get("comparison") == "strict_vs_scalar"
                    ),
                    {},
                ),
            }
            tables.append("\n### 表：多群组测量等值性检验\n\n")
            tables.append(
                "| 模型 | 约束 | χ² | df | CFI | TLI | RMSEA | SRMR | Δχ² | Δdf | p(diff) | ΔCFI | ΔRMSEA |\n"
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
            )
            for model in invariance.get("models", []):
                model_name = str(model.get("model", ""))
                fit_row = model.get("fitIndices", {})
                comparison = comparison_by_model.get(model_name, {})
                chi_square = fit_row.get("robustChiSquare")
                chi_square = (
                    chi_square if chi_square is not None else fit_row.get("chiSquare")
                )
                degrees = fit_row.get("robustDf")
                degrees = degrees if degrees is not None else fit_row.get("df")
                cfi = fit_row.get("robustCfi")
                cfi = cfi if cfi is not None else fit_row.get("cfi")
                tli = fit_row.get("robustTli")
                tli = tli if tli is not None else fit_row.get("tli")
                rmsea = fit_row.get("robustRmsea")
                rmsea = rmsea if rmsea is not None else fit_row.get("rmsea")
                constraints = " + ".join(model.get("constraints", [])) or "configural"
                released = model.get("releasedParameters", [])
                if released:
                    constraints += f"；释放 {', '.join(released)}"
                tables.append(
                    f"| {model_name} | {constraints} | {f(chi_square)} | "
                    f"{degrees if degrees is not None else '—'} | {f(cfi)} | "
                    f"{f(tli)} | {f(rmsea)} | "
                    f"{f(fit_row.get('srmr'))} | {f(comparison.get('deltaChiSquare'))} | "
                    f"{comparison.get('deltaDf', '—')} | {format_p(comparison.get('pValue'))} | "
                    f"{f(comparison.get('deltaCfi'))} | {f(comparison.get('deltaRmsea'))} |\n"
                )
            group_sizes = invariance.get("groupSizes", {})
            group_note = "；".join(
                f"{group} n={size}" for group, size in group_sizes.items()
            )
            release_note = ""
            releases = invariance.get("partialInvarianceReleases", [])
            if releases:
                release_note = (
                    " 部分等值模型的释放项及用户理由："
                    + "；".join(
                        f"{item.get('indicatorId')} ({item.get('constraint')}): "
                        f"{item.get('rationale')}"
                        for item in releases
                    )
                    + "。"
                )
            tables.append(
                "\n注："
                f"估计器为 {invariance.get('estimator', '—')}；{group_note}。"
                "表中优先使用可用的 robust/scaled 拟合指标，Δ 指标均相对前一递进模型计算。"
                "Chen（2007）变化准则仅作为情境相关证据，"
                "不构成自动等值判定；WLSMV 的 scalar 阶段约束阈值而非观测截距。"
                f"{release_note}\n"
            )
            path_comparisons = invariance.get("pathComparisons", [])
            if path_comparisons:
                tables.append("\n### 表：结构路径跨组差异\n\n")
                tables.append(
                    f"| 路径 | 组别比较 | B差值 | SE | z | p | {interval_label} |\n"
                    "|---|---|---:|---:|---:|---:|---:|\n"
                )
                for comparison in path_comparisons:
                    tables.append(
                        f"| {comparison.get('from')} → {comparison.get('to')} | "
                        f"{comparison.get('groupA')} − {comparison.get('groupB')} | "
                        f"{f(comparison.get('difference'))} | "
                        f"{f(comparison.get('standardError'))} | "
                        f"{f(comparison.get('statistic'))} | "
                        f"{format_p(comparison.get('pValue'))} | "
                        f"[{f(comparison.get('ciLower'))}, {f(comparison.get('ciUpper'))}] |\n"
                    )
        append_auditable_fact_tables(tables, result)
        return "".join(paragraphs), "".join(tables)

    method = "Logistic/OLS 组合方程" if _model_uses_logit(result) else "OLS 回归方程"
    paragraphs.append(f"## {template.replace('model_', 'Model ')} 结果摘要\n\n")
    paragraphs.append(
        f"本分析使用 {method} 估计。系数、标准误和置信区间应按每个方程记录的方法解释；"
        "横截面间接关联不能单独建立时间顺序或因果机制。\n\n"
    )

    for equation in result.get("equations", []):
        tables.append(f"### 表：{equation.get('id', '')} 回归结果\n\n")
        tables.append(
            "| 预测项 | B | SE | t/z | p | β | partial f² |\n|---|---:|---:|---:|---:|---:|---:|\n"
        )
        for coefficient in equation.get("coefficients", []):
            tables.append(
                f"| {coefficient.get('label', coefficient.get('term', ''))} | "
                f"{f(coefficient.get('estimate'))} | {f(coefficient.get('standardError'))} | "
                f"{f(coefficient.get('statistic'))} | {format_p(coefficient.get('pValue'))} | "
                f"{f(coefficient.get('standardizedEstimate'))} | {f(coefficient.get('cohenF2'))} |\n"
            )
            if coefficient.get("averageMarginalEffect") is not None:
                tables.append(
                    f"\nAME（{coefficient.get('marginalEffectType', 'marginal')}）："
                    f"{f(coefficient.get('averageMarginalEffect'))}，"
                    f"区间 [{f((coefficient.get('marginalEffectConfidenceInterval') or {}).get('lower'))}, "
                    f"{f((coefficient.get('marginalEffectConfidenceInterval') or {}).get('upper'))}]。\n"
                )
        tables.append("\n")
    _append_effect_table(tables, result.get("effects", []))

    if template in {"model_2", "model_3"}:
        paragraphs.append(
            "X 对 Y 的条件效应在 W 与 Z 的第 16、50、84 百分位组合上进行探查；"
            "简单斜率表中的每一行对应一组 W、Z 条件。"
        )
        if template == "model_3":
            paragraphs.append(
                "Model 3 同时估计 X×W、X×Z、W×Z 和 X×W×Z；"
                "三阶交互应结合联合条件效应解释。\n"
            )
    elif template in {"model_4", "model_5"}:
        indirect = _effect_by_id(result, "effect_indirect")
        if indirect and indirect.get("confidenceInterval"):
            interval = indirect["confidenceInterval"]
            paragraphs.append(
                f"间接效应估计为 {f(indirect.get('estimate'))}，"
                f"{interval.get('replicates', '—')} 次 {interval.get('method', 'bootstrap')} 抽样区间为 "
                f"[{f(interval.get('lower'))}, {f(interval.get('upper'))}]；"
                f"该区间{'排除' if _interval_excludes_zero(interval) else '未排除'} 0。"
            )
        if template == "model_5" and result.get("probes"):
            paragraphs.append(
                "X→Y 直接路径随 W 变化；简单斜率及 Johnson–Neyman 结果用于解释该条件直接效应。"
            )
    elif template == "model_6":
        indirects = [
            effect
            for effect in result.get("effects", [])
            if effect.get("id")
            in {
                "effect_indirect_1",
                "effect_indirect_2",
                "effect_indirect_3",
                "effect_total_indirect",
            }
        ]
        paragraphs.append("特定间接效应结果如下：\n")
        for effect in indirects:
            interval = effect.get("confidenceInterval")
            paragraphs.append(
                f"- {effect.get('label')}：估计值 {f(effect.get('estimate'))}，区间 "
                f"[{f(interval.get('lower') if interval else None)}, {f(interval.get('upper') if interval else None)}]，"
                f"区间{'排除' if _interval_excludes_zero(interval) else '未排除'} 0。\n"
            )
        contrasts = [
            effect for effect in result.get("effects", []) if effect.get("type") == "contrast"
        ]
        if contrasts:
            paragraphs.append("具体间接效应的 Bootstrap 两两差异如下：\n")
            for effect in contrasts:
                interval = effect.get("confidenceInterval")
                paragraphs.append(
                    f"- {effect.get('label')}：差异 {f(effect.get('estimate'))}，区间 "
                    f"[{f(interval.get('lower') if interval else None)}, "
                    f"{f(interval.get('upper') if interval else None)}]，"
                    f"区间{'排除' if _interval_excludes_zero(interval) else '未排除'} 0。\n"
                )
    elif template in {
        "model_7",
        "model_8",
        "model_14",
        "model_15",
        "model_21",
        "model_22",
        "model_58",
        "model_59",
    }:
        index = _effect_by_id(result, "effect_index")
        if index:
            interval = index.get("confidenceInterval")
            paragraphs.append(
                f"调节中介指数为 {f(index.get('estimate'))}，区间 "
                f"[{f(interval.get('lower') if interval else None)}, {f(interval.get('upper') if interval else None)}]，"
                f"区间{'排除' if _interval_excludes_zero(interval) else '未排除'} 0。\n"
            )
        conditional = [
            effect for effect in result.get("effects", []) if effect.get("type") == "conditional"
        ]
        if conditional:
            paragraphs.append("条件间接效应：\n")
            for effect in conditional:
                interval = effect.get("confidenceInterval")
                paragraphs.append(
                    f"- {effect.get('label')}：{f(effect.get('estimate'))}，区间 "
                    f"[{f(interval.get('lower') if interval else None)}, {f(interval.get('upper') if interval else None)}]。\n"
                )
        if template in {"model_58", "model_59"}:
            paragraphs.append(
                "第一、第二阶段均被同一 W 调节时，条件间接效应是 W 的非线性函数；"
                "因此报告代表值上的 Bootstrap 区间，不报告单一线性调节中介指数。\n"
            )
        if template in {"model_21", "model_22"}:
            paragraphs.append(
                "第一阶段由 W 调节、第二阶段由 Z 调节，条件间接效应是 W 与 Z 的联合函数；"
                "因此报告 W×Z 代表值网格上的 Bootstrap 区间，不报告单一调节中介指数。\n"
            )
        if result.get("probes"):
            paragraphs.append(
                "简单斜率属于被调节路径的条件效应，不是条件间接效应；"
                "表中效应、SE、检验、区间与 Johnson–Neyman 曲线使用同一模型协方差矩阵。"
            )
        for item in result.get("johnsonNeymanResults", []):
            jn = item.get("result", {})
            observed = jn.get("observedBoundaries", [])
            paragraphs.append(
                f" {item.get('predictorLabel', '预测变量')}×"
                f"{item.get('moderatorLabel', '调节变量')}在观测范围内的 "
                f"Johnson–Neyman 临界点为 "
                f"{'、'.join(f(value) for value in observed) if observed else '无'}；"
                "显著区域仅按当前置信水平和标准误口径解释。"
            )
    elif template.startswith("model_"):
        indirect = [
            effect
            for effect in result.get("effects", [])
            if effect.get("type") in {"indirect", "conditional"}
        ]
        indices = [
            effect
            for effect in result.get("effects", [])
            if effect.get("type") == "index"
        ]
        if indirect:
            paragraphs.append(
                "系统按有向路径分别计算特定间接效应，并同时给出总间接效应；"
                "含调节的路径在第 16、50、84 百分位条件网格上报告。"
                "推断以各效应的 Bootstrap 区间为准，不以组成路径单个系数的显著性替代。\n"
            )
        if indices:
            paragraphs.append(
                "“polynomial index”是条件间接效应关于 W、Z 的多项式系数。"
                "一次项可对应常见线性调节中介指数；W²、W×Z 等高阶项应按联合函数解释，"
                "不得当作单一线性指数或独立因果效应。\n"
            )
        if result.get("probes"):
            paragraphs.append(
                "同一路径同时受 W 与 Z 调节时，简单斜率由完整的主效应、二阶交互和三阶交互"
                "协方差矩阵联合计算；单独固定其中一个调节变量的边际解释并不充分。\n"
            )

    append_auditable_fact_tables(tables, result)
    return "".join(paragraphs), "".join(tables)
