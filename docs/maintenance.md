# 维护版构建说明

本维护版的 Linux amd64 wheel 不是从源码树直接打包，而是由本项目的 Go 源 fork 固定 commit
编译出的内核库，加上本仓 Python 包，在独立 build stage 中打包而成。

## 来源

| 组件 | 来源 | 说明 |
| --- | --- | --- |
| Python 包 | 本仓库工作树 | 前序已验收修复，版本 `1.0.10b2.dev0` |
| Go 内核库 | `https://github.com/Helel1/requests` commit `8ddcf6496005c5cb9acaf3f18d38159b7ef43269` | 用户自有 fork（fork 自 `wangluozhe/requests` @ `46ef52b`）；只读，`git archive` 提取，不修改 Go 仓库 |
| 内核修复 | 已包含在上述 commit 中 | 6 个源码文件 + Go 回归测试 `sessions_lifecycle_test.go` + `-tags probe` 用的 `libs_dist/probe_exports.go`；构建时**不再应用任何补丁**（`PATCH_PATHS = ()`，元数据 `kernel.patches` 为 `[]`） |
| 已退役补丁 | `patches/go-fix-46ef52b.diff` | 仅作历史记录保留，内容与 `8ddcf64` 逐行一致，不参与构建 |
| 构建工具链 | Go 1.24.0（`go.mod` 要求 `go 1.24.0`） | CI 用 `actions/setup-go`；本地用既有 VPS 工具链 |

构建产物里同时保留 **Go 源码快照 tar**（`requests-go-src-<commit>.tar.gz`，含 `LICENSE`、
`go.mod`、`go.sum` 与完整源码树），作为二进制对应的源码。

Go module path 仍是 `github.com/wangluozhe/requests`（`go.mod` 未改）。本仓不是新的 `go get`
模块路径，本轮也不重写仓内 63 处 import；这样 fork 与上游保持逐行可比。

## 构建

```bash
# 1) 生成内核库 + Go 源码快照 + Python build stage + wheel
python -m tools.build_go_lib <go_repo_dir> <output_dir>

# 输出目录结构
# <output_dir>/requests-go-amd64.so        编译出的内核库
# <output_dir>/build_info.json             内核构建元数据
# <output_dir>/requests-go-src-<c>.tar.gz  对应 Go 源码快照
# <output_dir>/go-src/                     解包的 Go 源码（编译用）
# <output_dir>/stage/                      仅含新库的 Python build stage
# <output_dir>/dist/*.whl                  可安装 wheel（py3-none-linux_x86_64）
```

`build_go_library(go_source_dir, output_dir, go_binary="go", go_ref=..., patch_paths=...,
env=None, python=None, build_dist=True)` 返回路径 dict
（`library`、`source_tar`、`build_info`、`stage_dir`、`dist_dir`、`wheel`、`commit` 等）。

目标是固定的 Linux amd64：库名、wheel 标记和元数据都只描述这一目标，
`env` 里出现不同的 `GOOS`/`GOARCH`/`CGO_ENABLED` 会直接报错，构建前还会用
`go env GOOS GOARCH` 复核实际目标，不会出现把 arm64 产物标成 amd64 的情况。

工具自身不下载源码、不安装工具链：源码目录必须已存在且包含该 commit，Go 由调用方准备。
`env` 可传 `GOPROXY`、`GOPATH`、`GOMODCACHE`、`GOCACHE`、`GOFLAGS`；**`go build` 自身会按
`GOPROXY` 下载缺失的模块**（依赖已缓存或 `GOPROXY=off` 时不会联网）。已有输出目录不会被
静默清空，重复使用会直接报错。

stage 只复制允许列表：`requests_go/` 包、`tools/`、`patches/`、`tests/`、`docs/`，以及
`setup.py`、`pyproject.toml`、`MANIFEST.in`、`LICENSE`、`LICENSE-GPL-3.0`、
`THIRD_PARTY_NOTICES.md`、`README.md`、`CHANGELOG.md`。旧平台二进制、`out/`、`dist/`、
临时报告与凭据不会进入 stage，因此输出目录放在仓库内也不会把上一次构建复制进自己。

## 内核来源更新流程

内核修复现在直接以 commit 存在于 `Helel1/requests`，不再经由本仓补丁。改内核的流程：

1. 在 Go 仓（`origin` = `Helel1/requests`，`upstream` = `wangluozhe/requests`）的新分支上修改并
   提交，`go test -race -count=1 .` 通过后 push，取新 commit SHA；
2. 同步三处来源，三者必须一致：`tools/build_go_lib.py` 的 `UPSTREAM_COMMIT`、
   `.github/workflows/linux-build.yml` 的 `ref:`、`tests/installed_wheel_smoke.py` 的
   `EXPECTED_COMMIT`；
3. 用新 commit 重新构建并跑校验（见下节）。

`UPSTREAM_REPO` / 元数据里的 `upstream_*` 键名保持不变，含义是「内核由哪个 Go 源仓的哪个
commit 构建」，现在指向用户自有 fork 而不是原作者仓。

`patches/go-fix-46ef52b.diff` 已退役：它记录了 `46ef52b → 8ddcf64` 的差异，仅供对照，
**不要**再把它加回 `PATCH_PATHS`，否则修复会被重复应用。

Go 回归测试在提取目录里运行（`sessions_lifecycle_test.go` 在包根目录）：

```bash
cd <output_dir>/go-src
go test -race -count=1 .
```

## 校验

```bash
# 生产库不得包含 probe 符号（探针构建才带 -tags probe）
nm -D --defined-only <output_dir>/requests-go-amd64.so | grep -c probe_   # 期望 0

# Python 回归（在 build stage 或已安装环境）
python -m unittest discover -s tests -v

# wheel 平台标记
unzip -p <output_dir>/dist/*.whl '*/WHEEL' | grep -E '^(Tag|Root-Is-Purelib):'
# 期望 Tag: py3-none-linux_x86_64 / Root-Is-Purelib: false
```

## 运行时自检

```python
import requests_go
info = requests_go.get_build_info()
info["python_version"]      # 1.0.10b2.dev0
info["library_path"]        # 实际加载的 .so 路径
info["kernel"]["upstream_commit"]   # 内核来源 commit（override 时为 None）
info["kernel_metadata"]     # "bundled" / "override-unknown" / "missing-unknown"
```

用 `REQUESTGO_DEPPATH` 指向外部库时，`kernel` 为 `None`、`kernel_metadata` 为
`override-unknown`：内置元数据不能代表外部库的身份。

## 边界

- 本维护版只在 Linux x86_64 上构建与验证；wheel 标记为 `py3-none-linux_x86_64`，
  未冒充 manylinux，也未声称跨平台。
- 仓库里其它平台的历史二进制（macOS、Windows、Linux arm64）本轮未重建，也未打进 wheel。
- 许可说明见 `THIRD_PARTY_NOTICES.md`；内核来源是用户自有 Go fork 的固定 commit
  （GPL-3.0，版权归原作者），固定 commit 是构建可复现的输入，不构成法律意义上的
  source offer，也不代表已完成全部合规审查。
