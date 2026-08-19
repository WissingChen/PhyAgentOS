# demo/cli — 终端 CLI 演示

离线模拟 `python -m PhyAgentOS agent`（非 TUI）会话，渲染成终端画面 MP4，不依赖 API key 与 gateway。

## 1. 对话流程 demo

```bash
python demo/cli/render_demo.py
```

- `timeline.py` — 预设对话时间线（shell 命令 → 横幅 → 用户提问 → spinner → `↳` 进度提示 → 回复 → exit）
- 输出：`paos_cli_demo.mp4`（15.6s）
- 改对话内容：编辑 `timeline.py` 顶部的 `SHELL_CMD` / `USER_MSG` / `HINTS` / `RESPONSE`

## 2. 分选任务会话 demo

```bash
python demo/cli/paos_sorting_demo.py
# 可选: --config 其他会话 JSON
```

- `sorting_session.json` — 会话配置（可编辑）：shell 命令、横幅、用户输入、`hints`（`time` 相对 spinner 开始）、`reply` 逐句（`time` 相对回复开始）
- `sorting_session.py` — 读取 JSON 构建事件时间线
- 输出：`paos_sorting_demo.mp4`（27.7s）
- 改文案或节奏：直接编辑 `sorting_session.json` 的文本与 `time` 时间戳

两个渲染入口共用 `render_demo.py`（窗口绘制、spinner、光标、emoji 渲染）和事件机制 `(时间戳, 事件, 内容)`。

## 说明

- 所有代码只在 `demo/` 下运行，不触碰生产包
- 字体依赖：Noto Sans Mono CJK / DejaVu Sans Mono / Noto Color Emoji（缺字体会渲染成方块）
