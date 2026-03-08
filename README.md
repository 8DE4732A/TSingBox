# TSingBox

基于 `Textual` 的 `sing-box` 终端客户端（TUI），支持：

- 订阅拉取与节点管理
- 路由与 DNS 偏好配置
- Cloudflare WARP 账户生成与落地
- 生成运行时配置并重启 `sing-box`
- 内存日志 + 文件日志（`~/.config/tsingbox/logs/app.log`）

## 环境要求

- Python >= 3.11
- `uv`
- 本机可执行 `sing-box`（用于应用配置时重启进程）

## 快速开始

```bash
uv sync --extra dev
uv run python -m tsingbox
```

## 测试

```bash
uv run --extra dev pytest
```

## 项目结构

- `src/tsingbox/app.py`：应用入口与组件装配
- `src/tsingbox/ui/`：Textual 界面
- `src/tsingbox/services/`：业务逻辑（订阅、WARP、配置构建、进程控制）
- `src/tsingbox/data/`：SQLite 与仓储层
- `tests/`：测试用例

## 设计文档

详细设计请见 `spec.md`。
