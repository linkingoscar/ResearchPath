# 工程债务登记

仅登记有仓库或复现证据的问题；验证缺口不等同于已证实的计算错误。尚未指定责任人，由项目维护者安排。原始诊断材料不提交到仓库。

| 编号 | 优先级 | 状态 | 债务与影响 | 证据 | 关闭条件 |
| --- | --- | --- | --- | --- | --- |
| TD-001 | P1 | ASCII 路径验证通过，兼容性限制保留 | Rtools 在非 ASCII 物理库路径下无法链接原生 R 包；使用 ASCII 实体目录可解除安装阻塞 | ASCII 目录的 setup 与 Full 通过，qs2 源码加载检查、163 包 R lock 与 glmmTMB/TMB ABI 检查通过；`scripts/check-r-build-path.R` | 实现并验证兼容中文工作区的实体构建/运行时布局；保持固定依赖版本，R lock 与 Full 均通过 |
| TD-002 | P2 | 未解决 | renv restore 存在 NULL 条目失败，当前依靠逐包加载及锁校验兜底；退出码不能独立表示完整安装 | `scripts/setup.ps1` 的 restore 注释与验证路径 | 在干净环境中完整 restore 成功退出，并保留逐包版本、加载和锁校验 |
| TD-003 | P2 | 保守控制中 | 模块影响映射需随新入口和测试扩充；未登记路径会触发 Full，增加验证成本 | `scripts/test-impact-map.json`；解析器的 Unmapped / No tests 回退 | 常用功能有准确的模块归属与行为测试；保持缺失映射的 Full 回退，不能以空清单跳过测试 |
| TD-004 | P1 | 验证缺口 | 39 个活动统计切片中，26 个未满足完整内部证据要求、9 个内部验证、4 个外部验证；功能宽度超过独立数值验证覆盖 | `specs/capability-evidence.json` | 按切片补齐估计目标、失败边界和独立数值证据，由登记规则派生成熟度，不手工提高等级 |
| TD-005 | P2 | 待外部执行 | 真人可用性方案仍待执行，不能据自动化测试宣称易用性达标 | `docs/09-真人可用性验证方案.md` | 外部参与者完成预定任务并形成可追溯结果，实际缺陷完成修复与复测 |
| TD-006 | P2 | 未解决 | Python 类型基线允许合计 228 条诊断和 206 处显式 Any；按类别计数可能使旧错误额度被新错误复用 | `apps/api/pyright-baseline.json`、`scripts/check-python-types.py` | 逐步降低基线并按具体诊断定位阻止新增错误；不得提高容忍上限 |
| TD-007 | P2 | 本地 Full 通过，待远端验证 | 日常 CI 已接入三级规则及模块选择，本地完整环境验证通过；需补齐远端代表性分支的运行证据 | `.github/workflows/ci.yml`、`docs/engineering/CHANGELOG.md` | PR/main 的代表性 Quick、Targeted、Full 分支运行通过；检查必需状态配置符合发布要求 |
| TD-008 | P2 | 未解决 | 用户安装入口仍复用开发环境准备，连带安装编译工具及浏览器测试依赖 | `README.md`、`scripts/setup.ps1` | 提供面向使用者的可复现安装/升级路径，开发与测试依赖按需准备 |
| TD-009 | P2 | 验证前置条件缺口 | R 有 32 项因缺少本地数值基准或公开数据资产而跳过；API 的 1 项符号链接备份边界测试因 WinError 1314 跳过；Full 成功不能证明这些用例已验证 | `engine/R/tests/testthat/test-*-goldens.R`、`test-public-data-*.R` 的资产检查；`test_backup_rejects_link_or_reparse_point` 的本机权限限制 | 提供合规、可复现的验证资产准备流程，并在支持文件符号链接的测试环境执行边界测试；保留来源及 oracle 独立性证据，不通过取消 skip 或放宽容差伪造通过 |

## TD-001 当前处理边界

- `R.dll`、`RcppParallel.dll` 和 `tbb.dll` 确实存在，失败不能解释为文件未安装。
- Rtools 的链接器无法解析原中文 `-L` 路径；R 的路径规范化又会撤销 junction 和 subst 对用户库路径的别名效果。
- 在 ASCII 实体目录中，qs2、jsonlite 及完整依赖恢复已验证；未删除或改变 `renv.lock`、未升级包或放宽统计容差。
- 下载的 glmmTMB 二进制与锁定 TMB 存在 ABI 差异，已由现有安装脚本源码重编并通过 ABI 检查。
- 源码构建路径检查只让非 ASCII 路径失败提前且可解释。ASCII 目录中的验证没有覆盖工具链对中文实体路径的兼容性，因此该限制仍保留登记。

## 更新规则

记录新证据、缓解措施和明确关闭条件。只有关闭条件实际满足才标记完成；计划、代码存在、测试进程退出或局部通过不能替代所需验证。
