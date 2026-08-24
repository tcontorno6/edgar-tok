#!/usr/bin/env python3
"""benchmark.py — compression benchmark: edgar-tok tokenizers vs general baselines.

Measures, on the HELD-OUT eval documents only (D-014):
  * bytes per token (higher = better compression) and total token counts,
    overall and sliced by form (10K / 13D) and era (pre/post-2019, roughly
    the iXBRL mandate line),
  * per-pattern token costs: for each domain pattern (dollar amounts,
    percentages, CUSIPs, citations, ...), every match found in the eval set
    is tokenized standalone with a leading space (D-017) and the mean
    tokens-per-instance reported,
  * a canonical-examples table for the write-up.

Baselines load from the Hugging Face hub by id and are skipped with a
warning if unavailable (no account, gated license, offline). Llama 3 is
gated: accept the license on its model page, `huggingface-cli login`, rerun.
No PyTorch needed — tokenizers only.

Usage (from edgar-tok, after train_tokenizer.py):
  python benchmark.py --ours tokenizers/edgar-bpe-65536
  python benchmark.py --ours tokenizers/edgar-bpe-32768 tokenizers/edgar-bpe-65536 ^
                      --baselines gpt2=gpt2 qwen3=Qwen/Qwen3-8B llama3=meta-llama/Meta-Llama-3-8B
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import statistics as st
import sys
from pathlib import Path

# --- domain patterns (benchmark-facing subset; counts mirror inspect_corpus) ---
PATTERNS: dict[str, re.Pattern] = {
    "dollar_amount": re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?"),
    "percentage": re.compile(r"\d+(?:\.\d+)?\s?%"),
    "basis_points": re.compile(r"\b\d+\s?bps\b|\bbasis\s+points?\b", re.I),
    "cusip_like": re.compile(r"\b(?=[0-9A-Z]{9}\b)(?=[0-9A-Z]*[A-Z])[0-9A-Z]{8}[0-9]\b"),
    "rule_section_citation": re.compile(r"\b(?:Rule|Section|Regulation|Item)\s+\d+[\w.()\-]*", re.I),
    "section_symbol": re.compile(r"§\s?\d[\w.()\-]*"),
    "big_number": re.compile(r"\b\d{1,3}(?:,\d{3}){2,}\b"),          # 1,234,567+
    "gaap_camelcase": re.compile(r"\b(?:[A-Z][a-z]+){4,}\b"),        # RevenueFromContractWith...
}

CANONICAL = [
    "$1,234.56", "$3,232,193", "4.25%", "150bps", "88160R101",
    "Rule 206(4)-1", "§251(h)", "Item 1A. Risk Factors",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "basis points", "EBITDA margin", "the Company’s",
]


class Tok:
    """Uniform counting wrapper over local tokenizer.json dirs and HF ids."""

    def __init__(self, name: str, count_fn, vocab: int):
        self.name, self._count, self.vocab = name, count_fn, vocab

    def count(self, text: str) -> int:
        return self._count(text)


def load_ours(path: Path) -> Tok:
    """Load a trained tokenizer dir. If its meta.json says it was trained with
    --normalize, evaluate it on normalized input too (D-018): the system under
    test is (normalizer + tokenizer), so feeding it raw curly quotes it never
    saw would measure a deployment mistake, not the ablation. Starred name
    marks this in the report."""
    import json as _json
    from tokenizers import Tokenizer
    f = path / "tokenizer.json" if path.is_dir() else path
    tk = Tokenizer.from_file(str(f))
    name = path.name if path.is_dir() else path.stem
    count = lambda s: len(tk.encode(s).ids)
    meta_p = (path if path.is_dir() else path.parent) / "meta.json"
    if meta_p.exists() and _json.loads(meta_p.read_text()).get("normalize_unicode"):
        from clean import _NORMALIZE_MAP
        table = str.maketrans(_NORMALIZE_MAP)
        count = lambda s: len(tk.encode(s.translate(table)).ids)
        name += "*"
    return Tok(name, count, tk.get_vocab_size())


def load_baseline(name: str, hf_id: str) -> Tok | None:
    try:
        from transformers import AutoTokenizer
        tk = AutoTokenizer.from_pretrained(hf_id)
        return Tok(name, lambda s: len(tk(s, add_special_tokens=False)["input_ids"]),
                   len(tk))
    except Exception as exc:
        print(f"  ! baseline '{name}' ({hf_id}) unavailable — skipped "
              f"({type(exc).__name__}: {str(exc)[:100]})", file=sys.stderr)
        return None


def era(p: Path) -> str:
    m = re.match(r"^\d{10}_\d{10}(\d{2})", p.stem)
    return "2019+" if m and int(m.group(1)) >= 19 else "pre-2019"


def form(p: Path) -> str:
    return p.stem.rsplit("_", 1)[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-list", type=Path, default=Path("data/splits/eval_docs.txt"))
    ap.add_argument("--ours", nargs="+", type=Path, required=True,
                    help="dir(s) containing tokenizer.json from train_tokenizer.py")
    ap.add_argument("--baselines", nargs="*",
                    default=["gpt2=gpt2", "qwen3=Qwen/Qwen3-8B",
                             "llama3=meta-llama/Meta-Llama-3-8B"],
                    help="name=hf_id pairs; unavailable ones are skipped")
    ap.add_argument("--max-docs", type=int, default=None, help="cap eval docs (quick runs)")
    ap.add_argument("--pattern-sample", type=int, default=2000,
                    help="max instances per pattern to tokenize (seeded)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", type=Path, default=Path("docs"))
    args = ap.parse_args()

    docs = [Path(ln) for ln in args.eval_list.read_text(encoding="utf-8").splitlines()
            if ln.strip()]
    if args.max_docs:
        docs = docs[: args.max_docs]
    print(f"eval set: {len(docs)} held-out documents")

    toks: list[Tok] = [load_ours(p) for p in args.ours]
    for spec in args.baselines:
        name, _, hf_id = spec.partition("=")
        t = load_baseline(name, hf_id or name)
        if t:
            toks.append(t)
    print("tokenizers:", ", ".join(f"{t.name}(v={t.vocab:,})" for t in toks))

    # --- corpus-level compression -----------------------------------------
    rows = []           # per (tokenizer, doc): tokens
    texts: list[tuple[Path, str, int]] = [
        (p, t := p.read_text(encoding="utf-8"), len(t.encode("utf-8"))) for p in docs]
    total_bytes = sum(b for _, _, b in texts)

    results = {}
    for tk in toks:
        per_doc = []
        for p, text, nbytes in texts:
            n = tk.count(text)
            per_doc.append((p, n, nbytes))
            rows.append({"tokenizer": tk.name, "doc": p.name, "tokens": n, "bytes": nbytes})
        tot = sum(n for _, n, _ in per_doc)
        slice_bpt = {}
        for label, pred in [("10K", lambda p: form(p) == "10K"),
                            ("13D", lambda p: form(p) == "13D"),
                            ("pre-2019", lambda p: era(p) == "pre-2019"),
                            ("2019+", lambda p: era(p) == "2019+")]:
            sel = [(n, b) for p, n, b in per_doc if pred(p)]
            if sel:
                slice_bpt[label] = sum(b for _, b in sel) / max(1, sum(n for n, _ in sel))
        med_10k = st.median([n for p, n, _ in per_doc if form(p) == "10K"] or [0])
        results[tk.name] = {"vocab": tk.vocab, "tokens": tot,
                            "bpt": total_bytes / tot, "median_10k_tokens": med_10k,
                            "slices": slice_bpt}
        print(f"  {tk.name}: {tot/1e6:.2f}M tokens, {total_bytes/tot:.3f} bytes/token")

    # --- per-pattern instance costs ---------------------------------------
    rng = random.Random(args.seed)
    all_text = "\n".join(t for _, t, _ in texts)
    pattern_rows = []
    for pname, pat in PATTERNS.items():
        found = pat.findall(all_text)
        found = [f if isinstance(f, str) else f[0] for f in found]
        if not found:
            continue
        sample = found if len(found) <= args.pattern_sample else rng.sample(found, args.pattern_sample)
        row = {"pattern": pname, "instances_in_eval": len(found)}
        for tk in toks:
            row[tk.name] = round(st.mean(tk.count(" " + s) for s in sample), 2)
        pattern_rows.append(row)

    canon_rows = []
    for s in CANONICAL:
        row = {"text": s}
        for tk in toks:
            row[tk.name] = tk.count(" " + s)
        canon_rows.append(row)

    # --- write outputs -----------------------------------------------------
    args.out_dir.mkdir(parents=True, exist_ok=True)
    md = args.out_dir / "BENCHMARK.md"
    with md.open("w", encoding="utf-8") as fh:
        fh.write("# Tokenizer benchmark — held-out SEC filings\n\n")
        fh.write(f"Eval set: {len(docs)} documents, {total_bytes/1e6:.1f} MB "
                 f"(never seen in training).\n\n")
        if any(t.name.endswith("*") for t in toks):
            fh.write("\\* starred tokenizers are evaluated on unicode-normalized "
                     "input — their native distribution (DECISIONS D-018).\n\n")
        fh.write("## Compression (bytes per token — higher is better)\n\n")
        base_bpt = results[toks[0].name]["bpt"]
        fh.write("| tokenizer | vocab | total tokens | bytes/token | vs "
                 + toks[0].name + " | median 10-K (tokens) |\n|---|---|---|---|---|---|\n")
        for name, r in results.items():
            rel = (base_bpt / r["bpt"] - 1) * -100  # fewer tokens than ref = positive %
            fh.write(f"| {name} | {r['vocab']:,} | {r['tokens']:,} | {r['bpt']:.3f} | "
                     f"{'—' if name == toks[0].name else f'{rel:+.1f}% tokens'} | "
                     f"{int(r['median_10k_tokens']):,} |\n")
        fh.write("\n## Slices (bytes/token)\n\n| tokenizer | 10-K | 13D | pre-2019 | 2019+ |\n|---|---|---|---|---|\n")
        for name, r in results.items():
            s = r["slices"]
            fh.write(f"| {name} | " + " | ".join(
                f"{s.get(k, float('nan')):.3f}" if k in s else "—"
                for k in ("10K", "13D", "pre-2019", "2019+")) + " |\n")
        fh.write("\n## Domain patterns (mean tokens per instance — lower is better)\n\n")
        cols = [t.name for t in toks]
        fh.write("| pattern | n in eval | " + " | ".join(cols) + " |\n|" + "---|" * (len(cols) + 2) + "\n")
        for row in pattern_rows:
            fh.write(f"| {row['pattern']} | {row['instances_in_eval']:,} | "
                     + " | ".join(str(row[c]) for c in cols) + " |\n")
        fh.write("\n## Canonical examples (tokens)\n\n")
        fh.write("| text | " + " | ".join(cols) + " |\n|" + "---|" * (len(cols) + 1) + "\n")
        for row in canon_rows:
            fh.write(f"| `{row['text']}` | " + " | ".join(str(row[c]) for c in cols) + " |\n")

    with (args.out_dir / "benchmark_per_doc.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["tokenizer", "doc", "tokens", "bytes"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nwrote {md} and {args.out_dir/'benchmark_per_doc.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
