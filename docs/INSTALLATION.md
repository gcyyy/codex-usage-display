# Windows 安装、升级与卸载

## 安装条件

如果电脑只有官方 Codex、没有 Codex++，先按 [README 的首次安装步骤](../README.md#从只有-codex开始安装) 补装核验的上游 Codex++ 1.8.0，必要时安装微软 WebView2，再实际打开管理器、确认 Codex 路径并保存用户脚本设置。仓库的 `scripts/Install-CodexPlus.ps1` 可下载校验并辅助首次安装，已有版本不会被覆盖。v0.2.1 完整包已包含该辅助脚本。

完整包无需 Python、Node 或 Rust；Codex++ 界面仍需 WebView2。上游 1.8.0 安装器不自动补装 WebView2。另一台电脑的复现步骤与仅依赖 Windows PowerShell 5.1 的验收脚本见 [干净电脑验收](CLEAN_MACHINE_TEST.md)。

Windows x64，已安装并启动过 Codex++。本版绑定 Codex++ 1.8.0 的核验构建，使用文件 SHA-256 判断兼容性，不能只看版本字符串。宿主不匹配时安装器在写入前停止，不覆盖新版或其他构建。

完整包 `codex-usage-display-VERSION-windows-x64.zip` 包含采集器、固定入口脚本、桥接程序、修改后桥接完整源码、许可证及每个文件的哈希清单。`collector-only` 包仅供已有兼容公开桥接的维护者使用，不能直接用于初次安装。

## 第一次安装

下载 Release ZIP 与同页 SHA256SUMS.txt。用 PowerShell 核对下载文件：

```powershell
Get-FileHash .\codex-usage-display-0.2.1-windows-x64.zip -Algorithm SHA256
```

将结果与发布页清单比较，再完整解压。运行 Install.cmd 会验证内部 SHA256SUMS.json，然后安装到当前用户目录，无需管理员权限。程序未做代码签名；如果系统拦截，应先确认来源及哈希，按本机策略处理，不需要关闭系统防护。

运行 Install.cmd 表示安装本项目采集器、脚本和包内 Codex++ 桥接。仅按路径及已核验文件哈希识别管理器进程，替换时结束并重启该管理器，不停止官方 Codex。若多开工作进程仍占用同一 EXE，会在写入前提示先关闭这些多开窗口。被替换文件备份在安装目录的 .installation-backups 下。安装结束在 Codex++ 点击“热重载脚本”。

## 固定路径

| 内容 | 默认位置 |
| --- | --- |
| 采集器与启动入口 | `%LOCALAPPDATA%\Programs\CodexUsageStatus` |
| 本工具配置和缓存 | 上述目录的 `.runtime` |
| 安装回执 | 上述目录的 `installation.json`，包含本机路径，仅保留本机 |
| 用户脚本 | `%APPDATA%\Codex++\user_scripts\codex-usage-status.js` |
| 独立桥接配对 | `%USERPROFILE%\.codex-session-delete\usage-status.json`，或 CODEX_PLUS_STATE_DIR 指定目录 |

config.json、usage-status.json、installation.json 与备份都不属于公共发行内容，勿上传。

## 日常使用

安装时自动隐藏启动采集器。没有注册开机自启；电脑重启后运行安装目录 Start.cmd 即可，重复启动会复用已有实例。Stop.cmd 停止本工具。启动与诊断不要求完整索引立即结束，面板会自动刷新。

## 升级与恢复

新版完整包解压到独立临时目录，再运行 Install.cmd，保留原配置与缓存。安装器先完整校验、检查兼容性，再停止本工具并替换，最后验证服务启动。新旧版本不应同时修改同一个索引。

安装中途异常会按磁盘备份 journal.json 逐项恢复旧文件，并尝试重新启动旧程序。强制断电或进程被终止时不会自动运行回滚；保留备份并按 journal 中的原路径和备份对应恢复，勿删除整个 Codex 数据目录。

只读桥接被 Codex++ 更新覆盖后，需要新的兼容桥接包；不要给现有二进制随意加入兼容哈希。需要重新核验、构建、测试之后才能扩展支持。

## 卸载

运行安装目录 Uninstall.cmd。卸载程序从单独临时 EXE 运行，以解除 Windows 对安装目录 EXE 的占用。只删除安装清单中未被修改的文件，恢复安装器保存的原宿主及独立配对。卸载不会恢复整个 user_scripts.json，而是只处理本工具的脚本键，保留用户后来添加的脚本。

修改过的宿主或文件保留并给出提示；.runtime 和 .installation-backups 默认保留，供复查或重装。随后在 Codex++ 热重载移除已加载入口。不要删除官方 .codex、认证、会话或其他应用目录。

## 命令行与非默认路径

```powershell
.\codex-usage-collector.exe verify-package --package-root .
.\codex-usage-collector.exe install --package-root . --install-bridge
# 明确给出非默认安装目录、脚本目录、管理器 EXE、桥接状态目录：
.\codex-usage-collector.exe install --package-root . --install-bridge `
  --install-dir 'D:\Apps\CodexUsageStatus' `
  --codex-plus-dir 'D:\CodexPlusConfig' `
  --host-exe 'D:\Apps\Codex++\codex-plus-plus.exe' `
  --host-state 'D:\CodexPlusState'
```

非默认 host-state 必须与宿主实际使用的 CODEX_PLUS_STATE_DIR 一致。自定义安装位置卸载时：`scripts\Uninstall.ps1 -InstallDirectory 'D:\Apps\CodexUsageStatus'`。

## 故障处理

- `Release checksum mismatch`：重新下载并完整解压，勿混用多个版本的文件。
- `Unsupported Codex++ binary`：当前宿主不是已核验构建；保留原程序，等待兼容包或自行复现核验。
- `Install and launch Codex++ first`：确认用户脚本配置目录存在且是当前用户实际使用的目录。
- `Collector exited`：用 diagnose 检查配置、端口与单实例；不要开放外网端口。
- “采集器未连接”：先运行 Start.cmd，然后 diagnose，再检查桥接配对。
- “部分记录 / 已定价部分估算”：展开价格口径与覆盖情况，查看具体日志或模型诊断；这不等于后台离线。
