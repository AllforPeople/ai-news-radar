#!/usr/bin/env python3
"""
push_to_wechat.py
从 data/latest-24h.json 读取 AI News Radar 的最新新闻数据，
生成纯文本摘要（3-5条精选），输出到 stdout，
供 OpenClaw cron 任务捕获后推送到微信。

依赖：Python 3.8+，仅标准库

用法：
    python scripts/push_to_wechat.py --data-dir data --top-n 5
    python scripts/push_to_wechat.py --data-url https://xxx.github.io/ai-news-radar/data/latest-24h.json

数据源：
    - 本地 data/latest-24h.json（GitHub Actions 工作流生成）
    - 或远程 Pages URL（跨机器读取，无需 clone）
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ── 数据读取 ──────────────────────────────────────────────

def load_json_from_file(path: Path) -> dict:
    """从本地文件读取 JSON。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_json_from_url(url: str) -> dict:
    """从远程 URL 读取 JSON（用于跨机器场景）。"""
    req = urllib.request.Request(url, headers={"User-Agent": "AI-News-Radar-WeChat/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_latest_json(data_dir: Path) -> dict | None:
    """找到 data/ 目录下最新的 news JSON 文件。

    优先查找 latest-24h.json（AI 过滤后的精选），
    其次 latest-24h-all.json（全量），最后按 mtime 排序。
    """
    candidates = [
        data_dir / "latest-24h.json",
        data_dir / "latest-24h-all.json",
    ]
    for p in candidates:
        if p.exists():
            print(f"[push_to_wechat] 使用: {p}", file=sys.stderr)
            return load_json_from_file(p)

    # fallback：按 mtime 找最新的
    json_files = sorted(data_dir.glob("*.json"), key=os.path.getmtime, reverse=True)
    if not json_files:
        return None
    print(f"[push_to_wechat] 使用: {json_files[0]}", file=sys.stderr)
    return load_json_from_file(json_files[0])


def load_data(args: argparse.Namespace) -> dict | None:
    """根据命令行参数加载数据。"""
    if args.data_url:
        print(f"[push_to_wechat] 从远程加载: {args.data_url}", file=sys.stderr)
        return load_json_from_url(args.data_url)
    return find_latest_json(args.data_dir)


# ── 数据提取 ──────────────────────────────────────────────

def extract_items(data: dict) -> list[dict]:
    """从 AI News Radar JSON 中提取 items 列表。

    数据结构（latest-24h.json）：
    {
        "generated_at": "2026-05-31T05:00:57Z",
        "window_hours": 24,
        "total_items": 401,
        "site_stats": [...],
        "items": [
            {
                "id": "...",
                "site_id": "tophub",
                "site_name": "TopHub",
                "source": "36氪 · 24小时热榜",
                "title": "新闻标题",
                "title_zh": "中文标题",
                "title_bilingual": "中英双语标题",
                "url": "https://...",
                "published_at": "2026-05-31T10:00:00Z",
                "ai_is_related": true,
                "ai_score": 0.71,
                "ai_label": "agent_workflow",
                "ai_signals": ["智能体"],
                "ai_noise": []
            }, ...
        ]
    }
    """
    if "items" in data and isinstance(data["items"], list):
        return data["items"]
    if isinstance(data, list):
        return data
    return []


# ── 格式化 ────────────────────────────────────────────────

# 微信一行约 20 个中文字，考虑到手机窄屏，每条摘要控制在 80-100 字以内
MAX_SUMMARY_CHARS = 100

def format_item(item: dict, index: int, show_source: bool = True) -> str:
    """格式化单条新闻为微信纯文本。"""
    title = (
        item.get("title_zh")
        or item.get("title_bilingual")
        or item.get("title")
        or "无标题"
    )
    source = item.get("source", "")
    url = item.get("url", "")
    label = item.get("ai_label", "")

    # 标签映射（中文友好）
    label_map = {
        "agent_workflow": "Agent/工作流",
        "ai_general": "AI 综合",
        "model_release": "模型发布",
        "ai_tools": "AI 工具",
        "research": "研究论文",
    }
    label_cn = label_map.get(label, label) if label else ""

    lines = [f"【{label_cn}】{index}. {title}"]
    if source:
        lines[-1] += f" - {source}"
    return "\n".join(lines)


def generate_report(data: dict, top_n: int = 5) -> str:
    """生成纯文本日报。"""
    items = extract_items(data)

    if not items:
        return "今日暂无 AI 资讯更新。"

    items = items[:top_n]
    total = data.get("total_items", len(extract_items(data)))

    now = datetime.now(tz=timezone(timedelta(hours=8)))
    date_str = now.strftime("%Y年%m月%d日")

    lines = [
        f"AI 每日晨报 - {date_str}",
        "-" * 20,
        "",
    ]

    for i, item in enumerate(items, 1):
        lines.append(format_item(item, i))
        lines.append("")

    lines.append(f"以上为今日 AI 精选，共 {min(top_n, total)} 条。")

    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="从 AI News Radar data/ 生成微信推送摘要"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="data/ 目录路径（默认: data/）",
    )
    parser.add_argument(
        "--data-url",
        type=str,
        default="",
        help="远程 data JSON URL（可用于跨机器读取，无需 clone 整个仓库）",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="展示前 N 条新闻（默认: 5）",
    )
    args = parser.parse_args()

    data = load_data(args)
    if data is None:
        print("错误：未找到任何新闻数据文件。", file=sys.stderr)
        sys.exit(1)

    report = generate_report(data, args.top_n)
    print(report)


if __name__ == "__main__":
    main()
