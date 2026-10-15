# codex-usage-display

[下载发行版](https://github.com/gcyyy/codex-usage-display/releases) · [Windows CI](https://github.com/gcyyy/codex-usage-display/actions/workflows/ci.yml)

Windows Codex 桌面的当日 Token 与 API 等价金额面板。入口位于右上角、最小化按钮左侧，支持拖动、明暗主题和按模型展开。

本项目是独立社区工具，需要 Codex++ 用户脚本支持；不是 OpenAI 官方产品。数据在本机读取，不调用模型 API，不需要 API Key。

## 安装

1. 安装并至少启动过一次 **Codex++ 1.8.0**。完整运行包仅支持已核验的宿主二进制；其他版本或构建会停止安装。
2. 从本仓库 Releases 下载 `codex-usage-display-0.2.0-windows-x64.zip`，核对同页 `SHA256SUMS.txt`，然后完整解压到临时目录。不要只下载 GitHub 的 Source code，也不要覆盖已有安装目录。
3. 双击 **Install.cmd**。它会校验文件、安装采集器和用户脚本，按需备份替换 Codex++ 管理器并配置只读桥接；不关闭或替换官方 Codex。
4. 在 Codex++ 点击一次 **热重载脚本**。正常情况下右上角出现今日用量。

安装到 `%LOCALAPPDATA%\Programs\CodexUsageStatus`，不需要 Python、Node、Rust、管理员权限或 API Key。不会注册系统服务、计划任务或登录启动；重启电脑后先运行安装目录中的 **Start.cmd**，再使用 Codex++。

采集器后台首次索引需要一些时间，健康状态正常但仍在 indexing 时等待即可。详细步骤、升级、卸载与故障处理见 [安装说明](docs/INSTALLATION.md)。

## 升级与卸载

升级时将新版完整 ZIP 解压到另一个临时目录，再运行 Install.cmd。安装器保留已有 home、端口、配对令牌及统计缓存，并保留旧文件备份；安装失败会尝试恢复之前的程序和配置。不要手动解压覆盖正在运行的安装目录。

卸载时运行安装目录的 **Uninstall.cmd**。它停止采集器、移除本工具脚本条目、恢复由安装器替换且尚未被用户修改的宿主程序。其他脚本和宿主设置保留。用户后来修改的文件不会强制删除；本工具的 `.runtime` 数据和恢复备份默认保留。随后在 Codex++ 热重载脚本移除入口。

## 统计口径

按配置时区的自然日汇总本机 `sessions` 与 `archived_sessions`，默认 `Asia/Shanghai`。默认计入桌面会话及其工作子代理；guardian / 自动审查默认单列，CLI 与其他来源可临时切换纳入。

优先使用带稳定响应 ID 的原生逐响应用量，处理复制、归档、分支继承及上下文计数重算，避免父子会话和重复日志重复计数。只保存用量数字、模型及必要身份元数据，不保存提示词、回答、图片地址或工具正文，不修改 Codex 会话、认证或配置。

金额是 **官方 Standard API 单价的等价估算，不是 Codex 订阅扣费或完整账单**。官方价格快照核验于 2026-10-15，覆盖精确 ID `gpt-6.1-sol`、`gpt-6-astra`、`gpt-6-luna`；使用 Decimal 按请求计算缓存及长上下文费率，推理不重复加到输出。

图片输入已包含在日志输入 Token 中，按核验过的模型单价计价一次。未知模型、缺失缓存分类、未核验日志版本、音频与不明媒体不会猜测价格；独立图片生成、工具、搜索、存储、地区附加费、税费及订阅费不计入。详情见 [图片规则](docs/IMAGE_PRICING.md) 和 [日志适配](docs/LOG_ADAPTER.md)。

“部分记录”表示日志覆盖存在待核验项；“已定价部分估算”表示价格覆盖不完整。两者独立。未定价 Token 仍显示，不作为零金额。

## 配置与诊断

安装后的 `%LOCALAPPDATA%\Programs\CodexUsageStatus\.runtime\config.json` 保存本工具配置，首次 home 优先采用 `CODEX_HOME`，否则为当前用户的 `.codex`。可以配置多个 home。此文件包含私有配对令牌，不要提交、截图或分享。

```powershell
# 在安装目录运行
.\codex-usage-collector.exe diagnose
.\Stop.cmd
.\Start.cmd
```

修改时区、home 或端口前先停止采集器；端口或令牌变更后，重新运行当前版本 Install.cmd 更新宿主配对。所有请求仅面向经过配对的 `127.0.0.1` 地址；页面只通过显式公开的只读桥接取数，不放宽 CSP 或 CORS。

## 开发与发布

源码测试支持 Python 3.11+。本机验证的 Windows EXE 使用 Python 3.12.14 / PyInstaller 6.16.0，GitHub CI 使用受支持的 Python 3.13 Windows 构建；宿主桥接使用 Rust 1.99.0 / MSVC、Windows SDK 与 Node 22。最终使用者不需要这些构建工具。

```powershell
python -m unittest discover -s tests -q
npm ci --ignore-scripts
npm run test:ui
.\scripts\Prepare-BridgeSource.ps1
.\scripts\Build-BridgeHost.ps1
.\scripts\Build.ps1 -PythonExe python -WithBridge
```

从干净源码检出复现、GitHub Actions、标签发布和清单校验见 [发布说明](docs/RELEASING.md)。发布包从显式公共文件清单生成，随桥接二进制提供完整修改后宿主源码；本机日志、配对配置、数据库和验收证据都不上传。源码及 Release 均采用 [AGPL-3.0-only](LICENSE)，第三方组件见 [声明](THIRD_PARTY_NOTICES.md)。
