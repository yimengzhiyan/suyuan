"""评测脚本。

    python eval/run_eval.py --data eval/dataset.jsonl [--limit N] [--strict] [--baseline] [--no-cache]

逐条结果写入 eval/results/<时间戳>.jsonl，终端打印汇总：
  - 判定准确率：完全一致得 1 分；「部分属实」对标签「不实」默认得 0.5 分，--strict 时得 0 分；「证据不足」得 0 分
  - 官方信源命中率：关键证据 / 全部证据中含 tier<=2（政府/官方、中央媒体）的样本比例
  - 平均耗时、平均搜索调用数
  - --baseline：额外让大模型不联网直接判定，作为对比列
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from suyuan.llm import LLM  # noqa: E402
from suyuan.search import YuanbaoSearch  # noqa: E402
from suyuan.verify import VERDICTS, Verifier  # noqa: E402

BASELINE_SYSTEM = """你是事实核查员。请根据你已有的知识判断下面这条网络传闻是否属实。
输出 JSON：{"verdict": "属实/不实/部分属实/证据不足 四选一", "confidence": 0~1, "reasoning": "一两句理由"}"""


def load_dataset(path: Path) -> list[dict]:
    rows = []
    for n, line in enumerate(path.read_text("utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"跳过第 {n} 行（JSON 错误：{e}）", file=sys.stderr)
            continue
        if "_comment" in obj:
            continue
        if not obj.get("text") or obj.get("label") not in ("属实", "不实"):
            print(f"跳过第 {n} 行（缺 text 或 label 不合法）", file=sys.stderr)
            continue
        obj.setdefault("id", f"line-{n}")
        rows.append(obj)
    return rows


def score(pred: str, label: str, strict: bool) -> float:
    if pred == label:
        return 1.0
    if pred == "部分属实" and label == "不实" and not strict:
        return 0.5
    return 0.0


def baseline(llm: LLM, text: str) -> dict:
    try:
        data = llm.chat_json(BASELINE_SYSTEM, f"传闻：{text[:2000]}", max_tokens=400)
    except Exception as e:  # noqa: BLE001
        return {"verdict": "证据不足", "confidence": 0.0, "error": str(e)}
    v = str(data.get("verdict") or "").strip()
    return {
        "verdict": v if v in VERDICTS else "证据不足",
        "confidence": data.get("confidence"),
        "reasoning": data.get("reasoning", ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "eval" / "dataset.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--strict", action="store_true", help="部分属实不给半分")
    ap.add_argument("--baseline", action="store_true", help="额外跑不联网的大模型直接判定")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"找不到数据集 {data_path}，可参考 eval/dataset.example.jsonl", file=sys.stderr)
        return 2
    rows = load_dataset(data_path)
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print("数据集为空", file=sys.stderr)
        return 2

    search = YuanbaoSearch(use_cache=not args.no_cache)
    llm = LLM()
    verifier = Verifier(search, llm)

    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl"

    results = []
    with out_path.open("w", encoding="utf-8") as f:
        for i, row in enumerate(rows, 1):
            print(f"[{i}/{len(rows)}] {row['id']} {row['text'][:40]}", file=sys.stderr)
            t0 = time.time()
            try:
                rep = verifier.verify(row["text"])
            except Exception as e:  # noqa: BLE001
                print(f"  失败：{e}", file=sys.stderr)
                res = {"id": row["id"], "label": row["label"], "pred": "证据不足", "score": 0.0,
                       "error": str(e), "elapsed": round(time.time() - t0, 2), "search_calls": 0,
                       "official_hit_key": False, "official_hit_any": False}
            else:
                res = {
                    "id": row["id"],
                    "label": row["label"],
                    "pred": rep.verdict,
                    "score": score(rep.verdict, row["label"], args.strict),
                    "confidence": rep.confidence,
                    "official_hit_key": any(e.tier <= 2 for e in rep.key_evidence),
                    "official_hit_any": any(e.tier <= 2 for e in rep.evidence),
                    "origin": rep.origin.url if rep.origin else None,
                    "origin_date": rep.origin.date_parsed.isoformat() if rep.origin and rep.origin.date_parsed else None,
                    "key_evidence": [e.url for e in rep.key_evidence],
                    "source": row.get("source", ""),
                    "elapsed": rep.stats.get("elapsed", 0),
                    "search_calls": rep.stats.get("search_calls", 0),
                    "llm_calls": rep.stats.get("llm_calls", 0),
                    "warnings": rep.warnings,
                    "claims": [c.text for c in rep.claims],
                    "reasoning": rep.reasoning,
                    "official_stance": rep.official_stance,
                }
            if args.baseline:
                b = baseline(llm, row["text"])
                res["baseline_pred"] = b["verdict"]
                res["baseline_score"] = score(b["verdict"], row["label"], args.strict)
            print(f"  标签={res['label']} 判定={res['pred']} 得分={res['score']}"
                  + (f" 基线={res['baseline_pred']}" if args.baseline else ""), file=sys.stderr)
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            f.flush()
            results.append(res)

    n = len(results)
    avg = lambda k: sum(r.get(k, 0) or 0 for r in results) / n  # noqa: E731
    print(f"\n==== 评测汇总（{n} 条，{'严格' if args.strict else '部分属实对不实计 0.5'}）====")
    print(f"判定准确率        {avg('score'):.1%}")
    if args.baseline:
        print(f"基线准确率(不联网) {avg('baseline_score'):.1%}")
    print(f"证据不足比例      {sum(r['pred'] == '证据不足' for r in results) / n:.1%}")
    print(f"官方信源命中率    关键证据 {avg('official_hit_key'):.1%} / 全部证据 {avg('official_hit_any'):.1%}")
    print(f"平均耗时          {avg('elapsed'):.1f} 秒")
    print(f"平均搜索调用      {avg('search_calls'):.1f} 次（不含缓存命中）")
    print(f"逐条结果          {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
