# ResearchPath UX / IA PRD 收口验收

> 状态日期：2026-09-06
> 范围：`ResearchPath_UX_IA_Reorganization_PRD_v1.0` 的 Phase 0–7。  
> 原则：只记录活动代码可证明的实现；自动化检查不冒充真实参与者用户研究。

## 1. 收口结论

Data / Analyze / Output 主线已通过 PR #3 合并到 main；PR #2 的全部提交包含在 #3 中，GitHub 同时将 #2 标记为已合并。最终实现已有完整 hosted Full 检查与依赖审计成功记录。本次直接复用已有验证，没有为合并重跑测试或增加检查条件。

主线合并不等于两份 PRD 已逐条完成。下表“已实现”表示该阶段核心迁移已落地。草稿持久化和体验尾项已通过 PR #4 合并，密集页面三断点回归已通过 PR #5 合并；PR #5 的 hosted Full 在执行项目测试前被外部 Hayes 数据源 TLS 证书名称错误阻断，因此不把该次红灯写成测试失败或验证完成。真实参与者用户测试尚未执行，自动化结果不能替代实际任务完成率、时间和主观体验。

## 2. Phase 0–7 验收矩阵

| Phase | PRD 目标 | 当前实现证据 | 状态 |
| --- | --- | --- | --- |
| 0 能力冻结 | UI 简化不丢能力 | `methodRegistry.json`、capability/method parity tests、PROCESS 55 catalog guards | 已实现 |
| 1 新应用外壳 | Data / Analyze / Output | `App.tsx`、`AppWorkspaceTabs.tsx`；旧“方法目录/路径与 SEM”不再是一级工作区 | 已实现 |
| 2 数据工作区 | Data/Variable/Scale、按需工具、局部确认 | `DataWorkspace*`、`VariableTable*`、`MeasurementWorkspace*`、DataGrid | 已实现 |
| 3 统一方法库 | 单一方法发现、方法局部守门、通用配置 | `ContextCapabilityCatalog`、method library presets、availability resolver | 已实现 |
| 4 Output / AnalysisDocument | 稳定分析对象、不可变运行、stale、复制、server/rebuild index | `AnalysisIndexService`、`AnalysisIndexRecoveryMixin`、hidden analysis-index routes、`OutputWorkspace`、server/local bridge | 已实现 |
| 5 PROCESS/SEM 表单 | 常见 PROCESS + 基础 SEM 表单，复杂模型回高级编辑 | Model 1/4/6/7/14 common forms、parallel Model 4、`SemQuickSetupForm` | 已实现 |
| 6 高级方法迁移 | 统一发现/标题/运行检查/Output，保留专用配置器 | experiment/multilevel/power/MI/measurement/longitudinal/diary method-scoped adapters | 已实现 |
| 7 视觉/A11y/发布 | 去大面积 glass、响应式、键盘/屏读、文档、发布证据、迁移清理 | `workbench.css`、`expert-model.css`、删除 `liquid-glass.css`、skip link、forced colors、PRD E2E | 核心迁移与现有自动化检查通过；完整体验验收见第 10 节 |

## 3. Phase 4：最终 Output 架构

### 3.1 服务端 AnalysisIndex

`apps/api/app/services/analysis_index.py` 保存项目级 AnalysisDocument 与 AnalysisRun 的导航身份和上游版本。索引文件使用既有 atomic JSON IO，不保存统计表、系数、诊断或图。持久化 CRUD 与 job 重建职责已拆分：`AnalysisIndexService` 负责索引读写与身份约束，`analysis_index_recovery.py` 负责从经过既有身份校验的任务状态重建导航引用；两个 service 都保持在仓库 source-line ceiling 内。

### 3.2 结果真值不迁移

- empirical → 既有 empirical job/report；
- PROCESS/SEM → 既有 model job/result；
- advanced/MI → 既有 advanced job/result。

Output 选择 run 后才读取权威状态/结果。AnalysisIndex 只解决“项目中有哪些分析/运行”和刷新恢复问题。

### 3.3 可重建索引

AnalysisIndex 可遍历经过原有 path/identity 校验的 persisted model/empirical/advanced job state。浏览器 localStorage 被清除或 AnalysisIndex 缺失时，服务端仍可恢复 run reference。显式登记与重建会复用同一 run 的既有 analysisId，避免重复 AnalysisDocument；模型和高级任务的测量身份从持久化 context lineage 恢复，stale 判定不会因索引重建而放松。

## 4. Phase 5：常见 PROCESS 表单

统一方法库直接提供 Model 4 简单中介、Model 4 两中介并行中介、Model 6 两中介链式中介、Model 1 简单调节、Model 7 第一阶段调节中介、Model 14 第二阶段调节中介，以及完整 PROCESS 高级目录。进入 common form 后不再出现第二个模型选择器。

所有表单只写现有 ModelSpec 并复用 validation/freeze/run/result。Model 14 的中心化对象按真实被调节路径使用 M/W；Model 1/7 使用 X/W。基础 SEM 继续提供两构念 X→Y form-first 路径，复杂测量、多组、高阶和约束模型回到 SEM Studio。

## 5. Phase 6：高级方法迁移

ICC/rwg、两层 Gaussian LMM、实验、解析功效等高频方法使用 common form；panel/diary、Monte Carlo、MI 和高级测量保留专用配置器，但共享统一方法库、标题/运行检查和 Output。没有因 UX 迁移替换 R runner、放宽统计门禁或提高 maturity/publication eligibility。

## 6. Phase 7：视觉与可访问性

- `liquid-glass.css` 已删除；routine Data/Analyze/Output 使用 `workbench.css`，专家 PROCESS/SEM 隔离在 `expert-model.css`；
- 1366/1024/760/420px 响应式，390px 浏览器检查页面级横向溢出；
- APG Data/Analyze/Output tabs、skip link、focus-visible、reduced motion、higher contrast、Windows forced-colors；
- `tests/e2e/prd-workbench.spec.ts` 覆盖三工作区键盘、skip-link、computed backdrop-filter、axe 和 390×844 溢出。

这些是机械可用性/无障碍证据，不是用户访谈或真实任务研究。

## 7. 迁移清理

新三工作区是已有数据的唯一一级路径；旧 empirical/model/method views 只作为 Analyze 内部 surface；global `analysisReady` 不再决定能否进入 Analyze；legacy glass stylesheet 已删除；localStorage 历史索引降级为兼容缓存；旧统计 runner、旧结果和兼容草稿没有因 UI 迁移被删除。

## 8. 文档同步

根 `README.md`、`docs/00`、`docs/01`、`docs/03`、`docs/README.md` 和本验收矩阵已同步。仓库没有独立于这些源文件之外的产品官网内容生成链；若未来另有外部站点仓库，应由其自己的发布流程同步，不能在本仓库伪造已更新状态。

## 9. 最终门禁证据

### 9.1 首轮 release-validation

首轮完整 hosted quality gate 已实际执行。R lock、R numeric baselines 与 R statistical test lane 没有进入失败列表；失败集中在两个静态工程 lane：

- `python-quality`：新增 AnalysisIndex 代码使 `reportOptionalMemberAccess` 从冻结最大值 1 增至 6，并使显式 `Any` 用量从 206 增至 210；
- `web-and-contracts`：Biome 报出 2 个冗余 Hook dependency 和 4 个测试中的 forbidden non-null assertion。

后续 `[skip ci]` 修复将 API route 返回类型改为 `JsonObject`，recovery 逻辑使用明确非空对象窄化并拆分到独立 service，Web Hook dependency 与测试断言按现有 lint 规则修正。**没有修改 Pyright baseline、Biome 规则、统计 contract 或数值基线来让门禁变绿。**

### 9.2 第二轮 release-validation

第二轮完整 hosted quality gate 已实际执行并进一步收敛失败面：

- `web-and-contracts` 已通过：Biome、PROCESS 55 browser preset parity 和 generated contracts 均成功；
- R lock、R numeric baseline 与 R statistical test lane 继续通过；
- 架构、changelog governance、source-line ceiling 和 inline-style budget 均通过；
- 唯一失败任务为 `python-quality`：`reportOptionalMemberAccess` 5（baseline 1），`reportOptionalSubscript` 2（baseline 1）。显式 `Any` 已恢复到冻结上限内。

第三候选继续在代码侧消除 Optional 类型不确定性：必填 AnalysisIndex token 使用 `Literal` overload 证明返回值必为 `str`，不再把必填身份扩散成 `str | None`。同时 `check-python-types.py` 在规则超基线时输出对应 Pyright 文件/行号诊断；其阈值和通过/失败判定未改变。

### 9.3 第三轮 release-validation

第三轮完整 hosted quality gate 已实际执行。Web/contract、R/统计、架构、changelog、source-line 和 style budget 均继续通过，最终失败列表仍只有 `python-quality`。增强后的诊断把新增问题精确定位到 `analysis_index_recovery.py` 中对 persisted `options` 的重复读取：4 个新增 `reportOptionalMemberAccess` 和 1 个新增 `reportOptionalSubscript`。日志中另有 `test_dataset_import.py` 的 1 个 member access + 1 个 subscript，它们正是仓库冻结 baseline 已允许的原有诊断。

第四候选将 persisted `options` 只读取一次，并在后续访问前明确窄化为非空 `JsonObject`。这覆盖第三轮全部新增 Optional 诊断，不改变 job 重建语义，也不调整 Pyright baseline。

### 9.4 已合并实现的验证

- [最终实现的 GitHub Actions](https://github.com/linkingoscar/nicetry/actions/runs/33880125546) 已成功完成 `scripts/test.ps1`、依赖审计、构建证据生成与上传；这是 Full 检查及审计记录，不冒称额外执行了完整 Release 模式。
- 自动化 PRD workbench E2E 已包含在该成功运行中。DEBT-202/203/204/208/209/210/211 据此关闭，不再列为待验证工作。
- 真实参与者用户测试：**未执行；需要外部参与者，不能由代码仓库自动补造。**

## 10. 合并后的实际尾项

本次对照两份 PRD 和活动代码确认以下差距；这是明确发现的待办清单，不是逐条验收全部需求的完成率统计。这些尾项不阻止已验证的主线合并。

| 尾项 | 当前边界 | 跟踪 |
| --- | --- | --- |
| 方法快捷访问 | 最近方法与收藏已实现，等待合并候选 Full 验证 | DEBT-212 |
| 完整数据表体验 | 完整案例分页、查找、排序与固定行号列已实现，等待合并候选 Full 验证 | DEBT-212 |
| 多结果批量导出 | 已复用既有权威导出路由实现多选结果逐项下载，等待合并候选 Full 验证 | DEBT-212 |
| 日常界面降噪 | 索引实现和内部 ID 已移入技术详情，等待合并候选 Full 验证 | DEBT-212 |
| 可编辑草稿持久化 | 已增加服务端版本正文、冲突检测和本地兼容缓存，等待合并候选 Full 验证 | DEBT-205 |
| 密集页面适配与试用 | Data、方法目录、实证配置、PROCESS、SEM 与 Output 历史的 1024/760/420 回归已随 PR #5 合并；hosted Full 被外部数据下载证书错误阻断，真实用户试用仍待执行 | DEBT-206 / 外部参与者 |

本轮实现不改变统计引擎和结果契约。真实用户试用仍需外部参与者，并按 [真人可用性验证方案](11-真人可用性验证方案.md) 记录；DEBT-206 只在合并后的测试代码实际完成一次 Windows/R/Chromium 执行后关闭。
