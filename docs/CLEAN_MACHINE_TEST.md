# 干净 Windows 电脑验收

目标环境是 Windows x64、只有已登录的官方 Codex，没有 Codex++、Python、Node、Rust 或 Git。WebView2 可能缺失，应在安装过程中补齐。不要为模拟干净环境卸载日常电脑的软件；使用另一台电脑或可回滚的虚拟机。

## 当前证据与边界

2026-10-15 新增 `scripts/Test-CleanMachine.ps1`，兼容系统自带 Windows PowerShell 5.1。本机 PATH 隔离冒烟已通过：独立 EXE、合成 Token/金额、缺少 Codex++ 设置时拒绝安装、重复安装保留配置、后台健康、无渲染器令牌、卸载与保留其他设置。

这只是本机隔离测试。它**不会卸载机器上的运行时，不会运行上游 Codex++ 安装器，不会替换真实 Codex++，也不会连接真实 Codex 页面**。测试用合成设置文件覆盖采集器安装流程；不得称为全新电脑端到端通过。报告的 `endToEndUI` 始终为 `not-tested`，需要人工验收另行补充。

## 获取材料

1. 按 README 下载并验证完整 Release ZIP，然后完整解压到新目录。
2. 从同一源码版本取 `scripts/Test-CleanMachine.ps1` 和 `scripts/Install-CodexPlus.ps1`，保存到本地。v0.2.5 完整 ZIP 已包含这两个脚本；使用包内版本，不要修改 SHA256SUMS.json。
3. 记录源码 commit、ZIP 文件名及 SHA-256、Windows 版本、官方 Codex 版本。不要记录认证或会话内容。

## A. 安装前的独立 EXE 冒烟

不需要安装 Codex++，也不要求启动 Codex。把 `D:\Downloads\...` 换成实际解压路径：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Test-CleanMachine.ps1 `
  -Mode Smoke `
  -PackageRoot 'D:\Downloads\codex-usage-status' `
  -Output '.\smoke-report.json'
if ($LASTEXITCODE -ne 0) { throw '冒烟测试失败，暂不安装' }
```

脚本仅在本进程临时修改 PATH，排除 Python/Node/Rust/Git，并清空 PYTHONPATH/PYTHONHOME；退出时恢复。它在 `%TEMP%\codex-usage-smoke-<随机ID>` 创建独立 home、设置和端口；固定合成数据为 110,000 Token，估算 $0.186。

测试先验证完整包，再验证采集器拒绝缺失宿主设置，之后用**合成宿主配置**测试采集器安装、重复升级、隐藏后台、diagnose、配对令牌隔离和发行包自带卸载脚本。不会使用 `--install-bridge` 替换真实管理器。临时目录中保留测试数据和备份供诊断；其中只有合成内容，不必递归清理真实安装目录。

通过条件：进程退出码为 0，报告 `status: passed`，全部检查存在。任何失败都不能用“本机有开发环境”作为忽略理由。

## B. 真正从零安装 Codex++ 与面板

按 README 的“从只有 Codex开始安装”逐步操作：

1. 记录“安装前没有 Codex++/开发工具”的环境事实。
2. 下载固定 1.10.0 安装器、核对 SHA-256；缺少 WebView2 时从微软获取并验证签名安装。
3. 打开 Codex++，确认官方应用路径、保持原有登录/供应商，通过管理器启动 Codex，保存用户脚本设置。
4. 从校验后的完整包执行 Install.cmd，点击“热重载脚本”。
5. 不要把“命令退出成功”作为全部验收，继续 C 和 D。

上游版本和本包绑定，不要在验收途中升级 Codex++。如官方 Codex 正在执行工作，先保存工作再处理上游要求的重新启动；本采集器安装步骤本身不会停止官方 Codex。

## C. 安装后只读检查

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Test-CleanMachine.ps1 `
  -Mode Installed `
  -Output '.\installed-report.json'
if ($LASTEXITCODE -ne 0) { throw '安装后检查失败' }
```

非默认安装目录追加 `-InstallDirectory 'D:\Apps\CodexUsageStatus'`。脚本读取安装回执定位实际宿主和脚本，检查服务健康、脚本桥接模式/启用状态、宿主哈希；不停止或修改实际服务，不打印配对令牌。索引 `indexing` 不是服务故障，可待其变成 `ready` 后再执行一次。

## D. 必须人工完成的界面验收

| 项目 | 成功条件 |
| --- | --- |
| 冷启动 | Codex++ 可以打开；通过它启动/连接官方 Codex |
| 入口 | 右上角出现今日用量；不会遮挡窗口控制按钮 |
| 展开 | 模型列表、金额、统计范围与价格覆盖可操作 |
| 数字刷新 | 等索引完成后刷新；有当日用量时出现数据 |
| 零记录 | 无当日会话时显示零/暂无用量，不能误报失败 |
| 版本差异 | v0.2.5 必须显示彩色分段条；热重载后验收 |
| 主题/DPI | 本机浅色/深色、显示缩放下仍能打开及关闭 |
| 重启后 | 重启电脑，运行 Start.cmd，再经 Codex++ 启动后仍可用 |
| 卸载 | 在可回滚测试机运行 Uninstall.cmd 后入口移除，其他配置保持 |

可以使用既有当天会话验收，不必额外调用模型。真实截图只截面板，隐藏会话名称、个人路径及其他应用内容。

## 报告模板

```text
日期 / 测试人：
Windows 版本与架构：
官方 Codex 版本：
安装前：Codex++ 是否缺失 / 开发运行时是否缺失 / WebView2 是否缺失
Codex++ 安装包版本与 SHA-256：
本项目 ZIP 名称、SHA-256 与脚本 commit：
Smoke 报告：passed / failed
Installed 报告：passed / failed
首次启动、界面刷新、主题/DPI、重启、卸载：逐项 passed / failed / 未测试
问题及已脱敏的固定错误消息：
```

可以分享两个脚本生成的摘要 JSON；脚本报告不含 home、账号、模型用量或令牌。不要分享 `.runtime/config.json`、`usage-status.json`、`installation.json` 或完整用户日志。

## CI 与截图复现

release 工作流构建完整 ZIP 后执行同一个 PowerShell Smoke 测试，单独上传 `clean-machine-smoke-report`。GitHub runner 预装很多组件；通过该任务只证明 PATH 隔离场景，不能代替 B–D。

维护者在开发环境设置 `UPDATE_DOC_SCREENSHOTS=1` 后执行 `npm run test:ui`，会输出 `docs/images/usage-light.png` 与 `usage-dark.png`。两张图仅截独立夹具中的面板，不访问真实 Codex 或用户会话。
