# 测试记录

0.2.0 本机已通过 71 项 Python 回归、6 组界面配置与 60 次热重载、独立 EXE 冒烟，以及实际完整 ZIP 的安装 / 重复升级 / 卸载验证。

验证覆盖：核心数字解析、精确模型计价、缓存与长上下文、图片计价、分支归属与响应去重、HTTP 只读访问控制、用户脚本布局与生命周期，以及安装校验、配置保留、重复升级、失败回滚、安全卸载。

核心与服务使用合成夹具：`python -m unittest discover -s tests -q`。UI 使用独立 Edge / Chromium 临时配置，6 组明暗主题与 DPI、60 次热重载，以及窄屏、CSS 缩放与 CSP 桥接夹具；不连接真实 Codex 页面。

独立 EXE 冒烟使用临时 home 和回环端口，验证初始化、离线索引、原生响应去重、HTTP / bridge 配对、隐藏服务、诊断、单实例与停止重建。安装冒烟从实际发布 ZIP 解压到独立临时目录，使用合成 Codex++ 设置验证安装、重复升级与卸载，避免覆盖真实应用。

过去已进行本机人工验收与真实日志数字交叉核验；相关报告含本机统计和路径，仅保留本机，不进入公共仓库或发行包。公开适配证据只包含上游版本、提交、字段与实现摘要，见 log-version-evidence.json 与 image-pricing-evidence.json。

GitHub 云端 CI 结果以实际 Actions 运行记录为准，工作流配置本身不代表云端构建已经通过。

GitHub Windows CI 已通过：[Tests 38675709047](https://github.com/gcyyy/codex-usage-display/actions/runs/38675709047)。完整桥接发行构建首次验证结果以 release 工作流的实际运行记录为准。
