# Third-party notices

`requests_go` 分发的是 Python 包 + 编译后的 Go 内核库（`requests-go-amd64.so`），
两者许可不同，下面按组件如实记录。

## 1. Python 包（本仓库）

- 许可证：MIT，见 `LICENSE`（`Copyright (c) 2023 LeeGene`）。
- 本仓库中源自 [psf/requests](https://github.com/psf/requests) 的派生代码
  （如 `requests_go/sessions.py`、`requests_go/structures.py` 等）遵循其上游
  Apache-2.0 许可（`Copyright Kenneth Reitz` 及贡献者）。

## 2. Go 内核库

- 上游：`https://github.com/wangluozhe/requests`
- 本维护版构建来源：`https://github.com/Helel1/requests`（用户自有 fork，fork 自上述上游）
- 许可：GNU GPL v3（见 `LICENSE-GPL-3.0`，逐字节复制自上游 `LICENSE`）。fork 保留原
  `LICENSE` 与完整上游历史，版权归原作者，修改版按 GPL-3.0 在 fork 的 README 中显著声明。
- 本维护版的二进制由 fork 的 commit
  `8ddcf6496005c5cb9acaf3f18d38159b7ef43269`（基于上游 `46ef52bb8356b38d2e3acf496cec3b7f9bc04a95`）
  直接构建，**不额外应用补丁**；构建产物同时附带 Go 源码快照 tar
  （`requests-go-src-<commit>.tar.gz`），其中包含 `LICENSE`、`go.mod`、`go.sum` 与完整源码树。
  `patches/go-fix-46ef52b.diff` 已退役，仅作历史记录。
- 该「固定 commit + 源码快照」用于构建可复现与审计，**不构成法律意义上的
  source offer**，也不代表已完成全部合规审查。

## 3. Go 依赖

`go.sum` 中的依赖（`github.com/wangluozhe/chttp`、`github.com/refraction-networking/utls`、
`golang.org/x/crypto`、`github.com/andybalholm/brotli`、`github.com/google/uuid` 等）
各自遵循其上游许可。**本轮未逐一核验这些依赖的许可证**（未联网获取、无 module cache），
分发前需补齐；本文件不对其许可做断言。

## 4. 未核实项

- `github.com/wangluozhe/chttp` 的许可证：待核。
- `go.sum` 其余传递依赖：待核。
- Python 运行时依赖（`requests`、`six`、`PySocks`）由使用者环境提供，不在本 wheel 内分发。
