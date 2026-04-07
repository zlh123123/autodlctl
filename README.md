# autodlctl

`autodlctl` 是一个基于 Playwright 的 AutoDL 控制台 CLI 工具，目标是把实例查询、开关机、详情读取、余额查询和登录状态保存做成可脚本化的命令行流程。

当前版本以 CLI 为主，适合：

- 在没有企业认证 API 的前提下，用浏览器自动化管理 AutoDL 实例
- 把登录态、实例选择、筛选和 SSH 信息提取接到脚本里
- 后续继续扩展成更完整的 AutoDL 自动化工具链

## 功能

- `auth`: 打开浏览器，等待手动登录并保存 Playwright storage state
- `list`: 列出实例并支持筛选、排序、限制条数
- `detail`: 读取实例详情面板和宿主机悬浮信息
- `start`: 启动实例，并在运行后复制 SSH 命令和密码
- `stop`: 关闭实例
- `inspect` / `status`: 输出当前页面可见控件和页面快照
- `balance`: 查询账户余额页中的当前余额
- `run`: 运行一组通用浏览器步骤，便于调试和扩展

## 安装

### 从 PyPI 安装

```bash
pip install autodlctl
playwright install chromium
```

说明：

- `pip install autodlctl` 只安装 Python 包，不会自动下载浏览器
- 首次运行时如果检测到 Chromium 缺失，CLI 会尝试自动执行 `playwright install chromium`
- 更稳妥的方式仍然是先手动执行一次 `playwright install chromium`

### 本地开发安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
playwright install chromium
```

## 快速开始

### 1. 登录并保存状态

```bash
autodlctl auth \
  --headless false \
  --pause-seconds 180 \
  --save-storage-state .autodl/storage_state.json
```

这条命令会打开 AutoDL 控制台，给你一段时间手动登录。命令结束后会把登录态保存到 `.autodl/storage_state.json`。

### 2. 查询实例

```bash
autodlctl list \
  --storage-state .autodl/storage_state.json
```

按条件筛选：

```bash
autodlctl list \
  --storage-state .autodl/storage_state.json \
  --gpu-model 4090 \
  --min-gpu-free 1 \
  --sort-by rentable_until
```

### 3. 查看详情

```bash
autodlctl detail \
  --storage-state .autodl/storage_state.json \
  --instance "你的实例名称或实例 ID"
```

### 4. 开机 / 关机

```bash
autodlctl start \
  --storage-state .autodl/storage_state.json \
  --instance "你的实例名称或实例 ID"
```

```bash
autodlctl stop \
  --storage-state .autodl/storage_state.json \
  --instance "你的实例名称或实例 ID"
```

无卡模式开机：

```bash
autodlctl start \
  --storage-state .autodl/storage_state.json \
  --instance "你的实例名称或实例 ID" \
  --mode nocard
```

### 5. 查询余额

```bash
autodlctl balance \
  --storage-state .autodl/storage_state.json
```

## 通用步骤模式

如果你想调试页面元素或临时跑一串 Playwright 操作，可以用 `run`：

```bash
autodlctl run \
  --storage-state .autodl/storage_state.json \
  --steps '[{"op":"wait_for","selector":"body"},{"op":"title"}]'
```

也支持兼容旧脚本入口：

```bash
python3 tools/autodl_console.py list --storage-state .autodl/storage_state.json
```

## 命令输出

CLI 统一输出 JSON，便于在 shell、Python 或其他脚本中消费。`0.x` 阶段会尽量保持这些顶层键稳定：

- `success`
- `reason`
- `container_id`
- `access`
- `detail`
- `instances`
- `filter`
- `sort`

## 项目结构

```text
src/autodlctl/
  cli.py                # argparse 入口与命令分发
  runtime.py            # 浏览器启动、storage state、资源关闭
  parsing.py            # 文本规范化、cookie 检查、列表过滤排序
  page_ops.py           # 页面交互与详情/tooltip 抓取
  commands/
    generic.py          # run / inspect / status
    instances.py        # start / stop / detail / list / auth
    account.py          # balance
tools/autodl_console.py # 旧入口兼容包装
```

## 开发与测试

```bash
pytest
python -m build
```

如果只想验证 CLI 入口：

```bash
python -m autodlctl --help
autodlctl --help
```

## 发布到 PyPI

项目使用 GitHub Actions + Trusted Publisher。

建议发布流程：

1. 先在 TestPyPI 配置 trusted publisher
2. 在 GitHub Actions 手动触发 `release.yml`，选择 `testpypi`
3. 验证安装与命令入口
4. 在正式 PyPI 配置 trusted publisher
5. 更新版本号
6. 推送 `vX.Y.Z` tag 触发正式发布

本地构建命令：

```bash
python -m build
twine check dist/*
```

## 注意事项

- 这个项目依赖 AutoDL 当前网页结构，页面 DOM 变动后可能需要调整选择器
- storage state 实际上就是浏览器登录态，建议只保存在本地可信环境
- 某些操作会弹出确认框或宿主机悬浮层，CI 无法完全替代真实人工验证
