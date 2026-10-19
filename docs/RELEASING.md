# 构建与 GitHub 发布

仓库建议名 codex-usage-display，许可证 AGPL-3.0-only。不要把本机工作目录直接打 ZIP 上传。dist、.runtime、.reference、.buildtools、已配对脚本、本机验收 JSON 与用户规范文件已排除版本控制。

## 构建环境

Windows x64；本机 Python 3.12.14，云端 Python 3.13（Actions 不提供 3.12.14 的 Windows 发行构建），requirements-build.lock 锁定构建依赖；Node 22、npm 锁文件；Rust 1.99.0 的 x86_64-pc-windows-msvc 工具链；Visual Studio C++ Build Tools 与 Windows SDK。桥接原生依赖按上游锁文件构建，首次需要访问 GitHub、npm 和 crates.io。

当前桥接基线为 Codex++ 1.10.0，源码准备目录为 `.reference/CodexPlusPlus-1.10.0`。`integration/source.json` 记录固定上游提交、补丁哈希与已核验宿主哈希。旧版 1.8.0 补丁仅为历史记录，不参与当前构建。

## 从干净源码复现

```powershell
python -m unittest discover -s tests -q
npm ci --ignore-scripts
npm run test:ui
.\scripts\Prepare-BridgeSource.ps1
.\scripts\Build-BridgeHost.ps1
.\scripts\Build.ps1 -PythonExe python -WithBridge
python -m scripts.installation_smoke
python -m scripts.export_source
```

Prepare-BridgeSource 只向新目录拉取 integration/source.json 锁定的公开上游提交，核对补丁哈希后应用，不修改已存在的参考树。Build-BridgeHost 不生成或改写补丁，必须通过前端、桥接和路由测试；发布时再次核对全部源码差异与被审阅补丁一致，并核对二进制构建记录。

输出完整包 `dist/codex-usage-display-VERSION-windows-x64.zip`，包含修改后的完整宿主源码 `bridge/corresponding-source.zip` 与上游许可证。主项目源码另外输出 `dist/codex-usage-display-VERSION-source.zip`，SHA256SUMS.txt 覆盖两个下载文件。内部 SHA256SUMS.json 覆盖包内所有公开文件。哈希用于完整性检查，本项目没有签名或自动更新信任机制。

## GitHub Actions

CI 在 push / pull_request 执行单元、服务和 UI 测试。release 工作流在 v* 标签或手动触发时构建 Windows 包、桥接、安全检查和安装冒烟，上传构建产物。只有版本标签与代码版本一致时才创建 GitHub **草稿 Release**；默认不自动公开草稿。

正式版本步骤：同步 collector/__init__.py、package.json、package-lock.json 的版本，更新 CHANGELOG.md，提交并推送，再推送相同的 vVERSION 标签。等待 release 工作流成功后打开草稿，检查完整 ZIP、源码 ZIP、SHA256SUMS.txt 和版本说明，再点击 Publish release。GitHub 自动生成的 Source code 附件不含构建产物，不能替代完整安装包。

构建检查需要 contents:read；只有发布草稿的独立 job 使用 contents:write。PR 不获得发布写权限，不执行 pull_request_target。初次 CI 尚未成功前，不能把工作流配置等同于已通过云端构建。

## 手动创建首次仓库

安装并登录 GitHub CLI 后，在干净的本项目 Git 仓库执行：

```powershell
gh repo create codex-usage-display --public --source . --remote origin --push
git tag v0.2.0
git push origin v0.2.0
```

首次发布前检查 git ls-files，不应含任何 .runtime、配对文件、本机验收报告、数据库或个人绝对路径。可以先使用本机已经测试的 Release 附件创建草稿；不要将失败或未运行的 CI 宣称为通过。

## 复用已核验的桥接构建

当只修改采集器或安装流程时，可在 Windows release 手动运行页面填写先前成功的同仓库 release run ID。流程校验运行来源、通过状态、精确上游提交、补丁 SHA、桥接版本及二进制哈希；任何不一致都会停止。桥接源码和补丁有变更时必须留空 ID，从头构建。采集器、安装回归、完整包和源码包每次重新构建与验证。

标签或手动运行默认只更新草稿。只有明确选择 publish=true 且全部检查和远端附件 SHA-256 均通过后，才会公开 Release。
