# 测试记录

## 2026-10-15：安装文档与无开发运行时验收

新增 `Test-CleanMachine.ps1` 已在 Windows PowerShell 5.1 下运行，通过 18 个检查点：隐藏开发工具 PATH、校验包、合成 Token/金额、缺失宿主设置时拒绝安装、重复升级、后台服务、脚本无令牌、卸载和保留其他设置。先验证本机构建的 0.2.0 包；公开 Release 包的独立复验见下方记录。报告明确标记 `endToEndUI: not-tested`。

随后从 GitHub 下载公开 `v0.2.0` 完整 ZIP（SHA-256：`60f61fee212c44a74223c8d359660367fcd8a8cba84a4d244bc199cea0d6ce0f`），在另一个解压目录运行相同脚本，18 个检查点全部通过。公开包与本机构建分开验证，不混用二进制或清单。

上游 v1.8.0 的 ZIP 已下载，SHA-256 为 `9b1a495d156242c747ff2b914d6ab141200948313db06f42e964cd0d410e694c`，内含 EXE 的 SHA-256 与现有宿主白名单 `48f062f9de96904c4c8169a8ccb0ee978fcca0d33cb1c75df9dee67c453a5d3d` 一致。安装器哈希来自上游 Release 资产元数据；没有在当前日常电脑重装 Codex++。

`Install-CodexPlus.ps1` 的仅下载模式已实际下载官方 setup.exe 并通过固定 SHA-256 校验；伪造安装器夹具被哈希检查拒绝。新机安装与 WebView2 安装分支未实际执行。Python 74 项回归与 UI 6 组配置/60 次热重载也已通过。

没有第二台干净 Windows 电脑或虚拟机。缺少 Codex++/WebView2 的真实首次安装、系统无预装 DLL、重启与完整 UI 链路仍待按 [验收文档](CLEAN_MACHINE_TEST.md) 复现。PATH 隔离及 GitHub runner 都不能代替此项。

README 深浅主题截图来自当前 main 的独立合成 UI 夹具。截图不含真实账号或日志；公开 0.2.0 的界面早于彩色 Token 分段条。

## 既有版本测试

0.2.0 本机已通过 74 项 Python 回归、6 组界面配置与 60 次热重载、独立 EXE 冒烟，以及实际完整 ZIP 的安装 / 重复升级 / 卸载验证。

验证覆盖：核心数字解析、精确模型计价、缓存与长上下文、图片计价、分支归属与响应去重、HTTP 只读访问控制、用户脚本布局与生命周期，以及安装校验、配置保留、重复升级、失败回滚、安全卸载。

核心与服务使用合成夹具：`python -m unittest discover -s tests -q`。UI 使用独立 Edge / Chromium 临时配置，6 组明暗主题与 DPI、60 次热重载，以及窄屏、CSS 缩放与 CSP 桥接夹具；不连接真实 Codex 页面。

独立 EXE 冒烟使用临时 home 和回环端口，验证初始化、离线索引、原生响应去重、HTTP / bridge 配对、隐藏服务、诊断、单实例与停止重建。安装冒烟从实际发布 ZIP 解压到独立临时目录，使用合成 Codex++ 设置验证安装、重复升级与卸载，避免覆盖真实应用。

过去已进行本机人工验收与真实日志数字交叉核验；相关报告含本机统计和路径，仅保留本机，不进入公共仓库或发行包。公开适配证据只包含上游版本、提交、字段与实现摘要，见 log-version-evidence.json 与 image-pricing-evidence.json。

GitHub 云端 CI 结果以实际 Actions 运行记录为准，工作流配置本身不代表云端构建已经通过。

GitHub Windows CI 已通过：[Tests 38675709047](https://github.com/gcyyy/codex-usage-display/actions/runs/38675709047)。完整桥接发行构建首次验证结果以 release 工作流的实际运行记录为准。

独立后台进程按 PyInstaller 文档设置 PYINSTALLER_RESET_ENVIRONMENT，外部管理器启动时恢复 Windows 标准 DLL 搜索路径，避免安装器退出后后台复用临时解包目录。参见 https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html 。
