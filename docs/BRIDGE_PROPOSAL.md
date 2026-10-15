# 最小 Codex++ 公开桥接接口提案

这是宿主接口契约。2026-10-15 用户已明确授权构建、备份替换本机 Codex++；对应 opt-in 实现位于 `integration/codex-plus-1.8.0-usage-bridge.patch`。补丁不修改 CSP 或官方 Codex 安装包。构建及安装结果以 `dist/bridge-host-build.json`、`docs/bridge-installation.json` 为准；补丁存在不代表已经完成真实页面联通。

目标是在 `app://` 页面维持原有 CSP，通过 `window.codexPlus.call` 取得本项目只读汇总。当前公开白名单没有该路由，上游维护记录中直接 HTTP loopback 被 CSP 阻止；详见 [兼容性证据](COMPATIBILITY.md)。

## 接口

新增两个显式开放的路由：

- `/usage-status/today`：输入仅允许 `{includeInternal:boolean, includeCLI:boolean, includeOther:boolean}`，缺省均为 false。返回本项目 `/v1/today` schemaVersion=1 契约。
- `/usage-status/health`：空对象输入，返回只读健康信息。
- `/usage-status/capabilities`：空对象输入，返回 bridgeVersion=1、readOnly=true 和是否已配对；不返回端口或令牌。

`window.codexPlus.call('/usage-status/today', options)` 经过已有公开调用层；不要暴露通用 URL 代理、任意文件读取或命令执行。本项目提供显式 `pair --transport bridge` 模式，适用于已安装本机补丁或提供相同公开契约的宿主；这个参数仅生成脚本，不能给未支持的宿主安装接口。

## 宿主约束

1. 用户明确授权安装并启用“本地用量采集器”。本机补丁使用 Codex++ 独立状态文件 `usage-status.json`，包含 schemaVersion=1、enabled、port、pairingToken；支持宿主既有 CODEX_PLUS_STATE_DIR 隔离。不向 renderer 暴露令牌，不读取 Codex 认证文件。
2. helper 请求目标固定为 `http://127.0.0.1:<已配对端口>/v1/today` 或 `/v1/health`。只准数字端口，禁止调用方传入 URL、Host、路径、请求方法、请求体或请求头；拒绝重定向。
3. helper 使用 Bearer 令牌，保留精确 Host。helper 本地请求无 Origin；采集器只在授权通过时接受。页面保留原有 CSP，不开放 `null` Origin 或全来源 CORS。
4. `today` 输入检查三项布尔值并拒绝未知字段，再生成固定查询字符串。限制返回大小建议 1 MiB，超时建议 3 秒。检查 schemaVersion 与汇总结构；不转发原始日志或路径。
5. helper 不负责启动任意程序或改写会话；重复查询由采集器单 worker 合并，客户端取消不撤销索引事务。
6. 增加公开接口版本 / capability，使第三方可以判断接口是否存在。为缺失配置、离线、授权失败、超时分别提供稳定错误代码，禁止回显令牌或用户路径。

## 实际验收步骤

记录真实 Windows / Codex / Codex++ 版本与对应源码提交；确认接口 capability。启用已配对脚本，观察真实入口与返回数据，核对人工合成 home 之后再使用本机数据。验证切换聊天、窗口缩放、明暗主题与十次热重载仅保留一个入口；关闭脚本后没有监听器和轮询。按 100% / 125% / 150% 系统缩放检查；获取仅包含卡片的真实明暗截图，避免附带聊天正文。

这个扩展接口无需开放 `/whale/*`、私有 React 状态或 Electron Node 权限。若真实宿主后续明确允许受控 HTTP loopback，则也可对 HTTP 模式做同样的 origin、CSP、访问控制和生命周期验收，再决定是否采用桥接。
