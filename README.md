# 研径 ResearchPath

ResearchPath 是一个 Windows 本地优先、点按式、按需执行的实证研究工作台。React 负责交互，FastAPI 负责任务、分析索引和本地持久化，R 负责统计估计；原始数据默认留在本机。

产品介绍页：[researchpath-pied.vercel.app](https://researchpath-pied.vercel.app/)；页面源码位于 [`pages/`](pages/)。

## 当前产品

已有数据的日常路径固定为三个一级工作区：

1. **数据（Data）**：导入后直接查看数据，按需进入变量、量表、质量、结构、合并和派生工具；不要求先完成一条长流水线。
2. **分析（Analyze）**：从唯一方法库搜索并选择方法，方法自身决定当前数据是否可运行；变量、角色、参数和运行检查都属于当前方法。
3. **输出（Output）**：按 AnalysisDocument 查看不可变运行、主要结果、非当前设置结果和模型/高级分析的服务端运行引用；统计结果仍由对应 job/result 服务权威保存。

研究规划和功效可在没有活动数据集时独立打开，与“分析已有数据”的工作流分离。时间结构、依赖结构和研究设计作为方法适用性上下文，而不是顶层导航。

### 方法入口

统一方法库覆盖当前已接线的基础实证、测量、回归、纵向/日记、PROCESS/SEM、实验、多层、功效、多重插补和高级测量能力。`executionAvailable=true` 只表示当前 runner 可执行，不等于独立验证完成或论文主分析资格。

常见 PROCESS 模型可直接表单配置，无需先进入画布：

- 简单中介：Model 4，X/M/Y；
- 并行中介：Model 4 多中介规格，X/M1/M2/Y；
- 链式中介：Model 6，X/M1/M2/Y；
- 简单调节：Model 1，X/W/Y；
- 第一阶段调节中介：Model 7，X/M/W/Y；
- 第二阶段调节中介：Model 14，X/M/W/Y。

完整 PROCESS 55 个当前预编程编号和高级 PROCESS/SEM 画布均可使用；常见表单与高级编辑共用 ModelSpec、冻结、校验和统计执行路径。

### 输出与恢复

Output 使用服务端 `AnalysisIndex` 保存 AnalysisDocument、运行引用、方法身份和上游数据/测量版本。它不复制统计结果：

- empirical 结果由 empirical job/report 服务负责；
- PROCESS/SEM 由 model job/result 服务负责；
- advanced/MI 由 advanced job/result 服务负责；
- 浏览器 localStorage 只保留即时草稿和界面状态；即使缓存丢失，Output 也可从持久化 job state 重建运行索引。

完整能力边界见 [产品边界](docs/00-产品边界.md)、[产品工作流与交互](docs/01-产品工作流与交互.md) 和 [能力矩阵](docs/07-能力矩阵与路线图.md)。

## 桌面轻应用

首次安装：

```powershell
./scripts/setup.ps1
./scripts/install-app.ps1
```

安装脚本会构建生产前端，并在桌面创建带专用图标的“研径 ResearchPath”快捷方式。以后双击图标即可在 Edge 独立应用窗口中使用：

- 无地址栏、标签栏和常驻终端；
- FastAPI 在 `127.0.0.1:9999` 同源托管 API 与生产静态文件；
- 使用独立 Edge 配置目录，不影响日常浏览器资料；
- 同一时间只允许一个实例；
- 关闭应用窗口后自动清理对应的本地服务；
- 日志：`.researchpath/logs/`。

根目录 `启动研径.cmd` 是没有快捷方式时的备用入口。升级前端代码后，重新运行 `scripts/install-app.ps1` 即可刷新生产构建和快捷方式。

## 开发与验证

使用 PowerShell 7：

```powershell
./scripts/dev.ps1
./scripts/harness.ps1 -Mode Quick
./scripts/harness.ps1 -Mode Targeted -BaseRef HEAD
./scripts/harness.ps1 -Mode Full
```

开发模式使用 Vite `127.0.0.1:5173` 和 FastAPI `127.0.0.1:9999`，会保留终端以显示生命周期；它与面向日常使用的桌面轻应用是两条独立入口。

- Quick：架构、lint、类型和契约漂移；
- Targeted：根据变更文件选择定向 API/R/Web/E2E，未知或高风险路径自动升级；
- Full：用于跨领域大改动或发布候选，覆盖 Python、R `testthat`、Web、完整 E2E、构建和 bundle。

详细规则见 [工程开发与验证](docs/04-工程开发与验证.md)。

## 项目结构

| 目录 | 内容 |
| --- | --- |
| `apps/web/` | React/Vite 前端、Data/Analyze/Output 工作台与 AnalysisIndex 客户端 |
| `apps/api/` | FastAPI API、AnalysisIndex、本地任务、持久化和导出 |
| `engine/R/` | 模型、实证、高级方法 R 入口与单测 |
| `specs/` | JSON Schema 与跨语言统计契约 |
| `scripts/` | 安装、开发、验证、备份和维护 |
| `tests/` | Playwright E2E 与可访问性/响应式验收 |
| `docs/` | 当前产品、统计、架构、验证和发布文档 |

机器可读入口见 [project.manifest.json](project.manifest.json)，文档按 [docs/README.md](docs/README.md) 阅读。

## 产品原则

- 原始数据只读，派生数据、测量、模型和分析对象版本化；
- 方法只在统一方法库选择一次，方法局部守门，不使用全局 `analysisReady` 代替真实前提；
- 每次运行显式提交；修改设置不覆盖已提交结果；
- 同一数据、规格、版本和种子应可复现；
- 统计方法、回退、警告和实际执行路径必须对用户可见；
- 不自动搜索显著模型，不把横截面关联写成因果；
- OutputIndex 只保存身份和运行引用，不复制或改写统计真值；
- 能力声明以当前注册表、契约、实现和验证证据为准。

## 使用与授权

ResearchPath 采用保留所有权的专有许可，不是开源软件。仓库公开可见仅用于审阅；除 GitHub 服务条款为站内查看和 fork 提供的必要权利外，不授予使用、复制、修改、再分发、托管或制作衍生作品的许可。完整条款见 [LICENSE](LICENSE)，第三方材料和官方 PROCESS for R 5.0 宏边界见 [NOTICE.md](NOTICE.md)。
