# Codex++ 只读用量桥接

桥接针对 Codex++ 1.10.0、上游提交 85f9117fe108719c6e4807ec60025a25042345f9。许可 AGPL-3.0-only，来源与补丁哈希在 source.json。完整运行包包含桥接 EXE 和完整修改后源码 bridge/corresponding-source.zip；公共仓库保留受审阅的补丁和构建脚本。

仅显式公开 /usage-status/today、/usage-status/health、/usage-status/capabilities。后端读取独立配对文件，只向固定 127.0.0.1 的已配对端口发送授权 GET，禁用代理和重定向。输入只允许三个布尔统计范围，配置上限 8 KiB、回复上限 1 MiB、超时 3 秒。不返回令牌、路径或网络错误详情，不修改 CSP，不开放通用代理或 /whale/*。

从主项目运行 scripts/Prepare-BridgeSource.ps1，按锁定提交拉取并应用补丁；运行 scripts/Build-BridgeHost.ps1 构建前端并执行前端、桥接和路由测试，再构建 EXE。完整发布构建会核对源码差异、补丁及构建记录一致，参见 docs/RELEASING.md。

最终用户运行完整包 Install.cmd，安装器在写入前校验已有宿主哈希，备份并仅在必要时替换管理器。页面脚本只含 transport=bridge，令牌保留后端。独立 pairing 文件属于私有数据，勿提交；卸载和升级保留其他宿主配置。
