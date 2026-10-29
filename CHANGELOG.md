# Changelog

## 1.0.10b2.dev0 — Linux amd64 维护版

### Go 内核迁移到自有仓库

- 内核来源从「上游固定 commit + 本仓补丁」改为用户自有 fork
  [`Helel1/requests`](https://github.com/Helel1/requests) 的固定 commit
  `8ddcf6496005c5cb9acaf3f18d38159b7ef43269`（fork 自上游 `wangluozhe/requests`
  `46ef52bb8356b38d2e3acf496cec3b7f9bc04a95`）。修复已作为 commit 存在于该 fork，
  因此 `PATCH_PATHS` 置空、构建元数据 `kernel.patches` 为 `[]`。
- `patches/go-fix-46ef52b.diff` 退役：内容与 `8ddcf64` 逐行一致，仅作历史记录保留，
  不再参与构建。
- Go module path 仍为 `github.com/wangluozhe/requests`，本轮不重写 63 处 import；
  本仓不是新的 `go get` 模块路径。
- 许可与历史不变：fork 保留原 `LICENSE`（GPL-3.0）与完整上游历史，版权归原作者。
- CI 与 `tests/installed_wheel_smoke.py` 的内核来源同步改为该 fork 与新 commit。

### 维护版内容

（本小节记录该版本开发过程中的构建方式；内核来源已由上节「Go 内核迁移到自有仓库」取代，
`PATCH_PATHS` 现为 `()`，下文「应用补丁」的描述仅适用于迁移前的阶段。）

- 内核库改用「固定上游 commit + 本仓补丁」构建：上游 `wangluozhe/requests`
  `46ef52bb8356b38d2e3acf496cec3b7f9bc04a95` + `patches/go-fix-46ef52b.diff`
  （包含连接池/会话释放、Cookie/Header 解析、bool 零值等前序修复，以及对应的 Go 回归测试）。
- 新增 `tools/build_go_lib.py`：`build_go_library()` 从 Go 仓库 `git archive` 固定 commit
  到独立 staging 目录、应用补丁、`go build -trimpath -buildmode=c-shared` 构建内核库，
  输出库文件、Go 源码快照 tar、`build_info.json` 与 Python build stage。build stage 只按
  允许列表复制打包所需文件（不含 `out/`、旧平台二进制、临时报告与凭据），目标固定
  Linux amd64，其它 GOOS/GOARCH 会被拒绝。
- 新增 `requests_go.get_build_info()`：返回 Python 版本、实际加载的库路径和内核构建元数据。
- 修正内核库加载：`REQUESTGO_DEPPATH` 现在优先于默认库；Linux x86_64 明确选择
  `requests-go-amd64.so`（不再因 `"x86" in machine()` 误判 32 位）；只接受 Linux
  x86_64/aarch64、macOS x86_64/arm64、64 位 Windows amd64，其它 OS/架构（含 Windows
  arm64 与 32 位）给出明确错误而不猜库名。
- 打包：新增 `pyproject.toml`，wheel 标记为 `py3-none-linux_x86_64`（不再冒充 `py3-none-any`），
  wheel 只携带本次构建的 Linux amd64 库；源码树直接打包会被 `setup.py` 拒绝并要求 build stage。
- 许可：保留原 MIT `LICENSE`，新增 Go 内核 GPL-3.0 许可证 `LICENSE-GPL-3.0` 与 `THIRD_PARTY_NOTICES.md`。
- CI：新增 `.github/workflows/linux-build.yml`（`pull_request` / `workflow_dispatch`，只构建与测试，不发布）。

已知限制：本轮只在 Linux x86_64 上构建与验证；wheel 未冒充 manylinux，
其它平台二进制未重建。
