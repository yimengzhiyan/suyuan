"""命令行入口。

    python cli.py "传闻文本"
    python cli.py --file rumor.txt --json out.json
    python cli.py "传闻文本" --no-llm      # 不调用大模型，只测检索与分级
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from suyuan.llm import LLM
from suyuan.report import render_markdown
from suyuan.search import YuanbaoSearch
from suyuan.verify import Verifier


def main() -> int:
    ap = argparse.ArgumentParser(description="溯源：基于元宝搜索的网络传闻求证与溯源")
    ap.add_argument("text", nargs="?", help="传闻文本")
    ap.add_argument("--file", help="从文件读取传闻文本")
    ap.add_argument("--json", dest="json_out", help="把完整结果写入该 JSON 文件")
    ap.add_argument("--no-cache", action="store_true", help="不使用搜索缓存")
    ap.add_argument("--no-llm", action="store_true", help="跳过大模型，只做检索与分级")
    args = ap.parse_args()

    if args.file:
        text = Path(args.file).read_text("utf-8")
    elif args.text:
        text = args.text
    else:
        ap.error("请提供传闻文本或 --file")
    text = text.strip()
    if not text:
        ap.error("传闻文本为空")

    try:
        search = YuanbaoSearch(use_cache=not args.no_cache)
        llm = None if args.no_llm else LLM()
    except Exception as e:  # noqa: BLE001
        print(f"初始化失败：{e}", file=sys.stderr)
        return 2

    from suyuan import gate

    g = gate.check(text, llm)
    if not g.allowed:
        print(f"[溯源] 已拒绝（{g.category}）：{g.reason}", file=sys.stderr)
        print(gate.REFUSAL_TEXT.get(g.category, g.reason))
        sys.exit(2)
    report = Verifier(search, llm).verify(text, progress=lambda m: print(f"[溯源] {m}", file=sys.stderr))
    print(render_markdown(report))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), "utf-8")
        print(f"[溯源] JSON 已写入 {args.json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
