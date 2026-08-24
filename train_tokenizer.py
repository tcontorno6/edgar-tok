#!/usr/bin/env python3
"""train_tokenizer.py — train byte-level BPE tokenizers on the filing corpus.

Design (DECISIONS D-015):
  * Byte-level BPE with GPT-2-style pre-tokenization (the ByteLevel
    pre-tokenizer's regex splits text into word/number/punct chunks before
    merging), matching the family every baseline uses — so the benchmark
    measures VOCABULARY, not architecture differences.
  * No unknown token needed: byte-level can encode anything.
  * One special token: <|endoftext|> as a document separator for later
    training use.
  * --normalize trains the ablation twin (D-001/D-018): the exact same
    curly-quote/dash map clean.py ships is applied to the training stream,
    so no second corpus is materialized on disk.

Usage (from edgar-tok, after split_corpus.py):
  python train_tokenizer.py --vocab-size 32768 65536 131072
  python train_tokenizer.py --vocab-size 65536 --normalize
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path

from tokenizers import Regex, Tokenizer, decoders, models, pre_tokenizers, trainers

from clean import _NORMALIZE_MAP  # single source of truth for the ablation map

# --- pre-tokenization ladder (DECISIONS D-019) -----------------------------
# BPE merges can never cross pre-tokenization chunk boundaries, so the chunking
# rule sets the compression ceiling:
#   gpt2   — ByteLevel's GPT-2 regex (words/digit-runs/punct split apart).
#            Same rules as the baselines: the fair-fight variant.
#   digits — like gpt2, but number expressions ($1,234.56 / 4.25% / 3,232,193)
#            stay whole, so BPE can learn them as 1-2 tokens.
#   line   — chunks are whole lines (capped at 256 bytes): merges may cross
#            spaces, so recurring filing boilerplate can fuse into phrase
#            tokens. Maximum compression; carries a "non-standard
#            pre-tokenization" asterisk in comparisons.
_DIGITS_PATTERN = r" ?\$?\d[\d,]*(?:\.\d+)?%?| ?\p{L}+| ?[^\s\p{L}\d]+|\s+"
_LINE_PATTERN = r"[^\n]{1,256}|\n+"

PRETOK_MODES = ("gpt2", "digits", "line")


def build_pre_tokenizer(mode: str):
    if mode == "gpt2":
        return pre_tokenizers.ByteLevel(add_prefix_space=False)
    pattern = _DIGITS_PATTERN if mode == "digits" else _LINE_PATTERN
    return pre_tokenizers.Sequence([
        pre_tokenizers.Split(Regex(pattern), behavior="isolated"),
        pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False),
    ])

DEMO_STRINGS = [
    "Revenues of $3,232,193 for fiscal 2023, an increase of 4.25%.",
    "CUSIP No. 88160R101",
    "approximately 150bps of margin expansion",
    "pursuant to Rule 206(4)-1 and §251(h) of the DGCL",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
]


def load_paths(file_list: Path, max_docs: int | None, seed: int) -> list[Path]:
    paths = [Path(ln) for ln in file_list.read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    if max_docs and len(paths) > max_docs:
        import random
        rng = random.Random(seed)
        paths = sorted(rng.sample(paths, max_docs))
    return paths


def iter_docs(paths: list[Path], normalize: bool) -> Iterator[str]:
    table = str.maketrans(_NORMALIZE_MAP) if normalize else None
    for p in paths:
        text = p.read_text(encoding="utf-8")
        yield text.translate(table) if table else text


def train_one(file_list: Path, vocab_size: int, min_frequency: int,
              normalize: bool, out_root: Path, pretok: str = "gpt2",
              max_docs: int | None = None, sample_seed: int = 42) -> Path:
    paths = load_paths(file_list, max_docs, sample_seed)
    tok = Tokenizer(models.BPE())
    tok.pre_tokenizer = build_pre_tokenizer(pretok)
    tok.decoder = decoders.ByteLevel()
    trainer_kwargs = dict(
        vocab_size=vocab_size,
        min_frequency=min_frequency,
        special_tokens=["<|endoftext|>"],
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
        show_progress=True,
    )
    if pretok == "line":
        # allow phrase-length tokens, but cap so a pathological 256-byte line
        # can't become a single vocab entry
        trainer_kwargs["max_token_length"] = 64
    trainer = trainers.BpeTrainer(**trainer_kwargs)
    t0 = time.time()
    tok.train_from_iterator(iter_docs(paths, normalize), trainer=trainer)
    dt = time.time() - t0

    name = (f"edgar-bpe-{vocab_size}"
            + ("" if pretok == "gpt2" else f"-{pretok}")
            + ("-norm" if normalize else ""))
    out_dir = out_root / name
    out_dir.mkdir(parents=True, exist_ok=True)
    tok.save(str(out_dir / "tokenizer.json"))

    meta = {
        "name": name, "vocab_size": vocab_size, "min_frequency": min_frequency,
        "pretokenizer": pretok,
        "normalize_unicode": normalize, "train_seconds": round(dt, 1),
        "train_list": file_list.as_posix(),
        "train_list_sha256": hashlib.sha256(file_list.read_bytes()).hexdigest()[:16],
        "n_train_docs": len(paths),
        "subsampled": bool(max_docs and max_docs < sum(
            1 for ln in file_list.read_text().splitlines() if ln.strip())),
        "sample_seed": sample_seed,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    print(f"\n=== {name}: trained in {dt:.0f}s -> {out_dir}/tokenizer.json")
    print("demo tokenizations (token counts; '|' marks boundaries):")
    for s in DEMO_STRINGS:
        enc = tok.encode(s)
        pretty = "|".join(t.replace("Ġ", "_") for t in enc.tokens)
        print(f"  [{len(enc.ids):>2} tok] {s}")
        print(f"           {pretty[:150]}")
    return out_dir


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-list", type=Path, default=Path("data/splits/train_docs.txt"))
    ap.add_argument("--vocab-size", type=int, nargs="+", default=[65536])
    ap.add_argument("--min-frequency", type=int, default=2)
    ap.add_argument("--normalize", action="store_true",
                    help="train the unicode-normalized ablation twin (D-018)")
    ap.add_argument("--pretok", choices=PRETOK_MODES, default="gpt2",
                    help="pre-tokenization mode (D-019): gpt2 = baseline-fair; "
                         "digits = whole-number chunks; line = phrase merges")
    ap.add_argument("--max-train-docs", type=int, default=None,
                    help="seeded subsample of training docs (memory control for "
                         "line mode — its merge index scales with unique lines; "
                         "recommended 1500 for --pretok line on the full corpus)")
    ap.add_argument("--sample-seed", type=int, default=42)
    ap.add_argument("--out-dir", type=Path, default=Path("tokenizers"))
    args = ap.parse_args()

    if not args.train_list.exists():
        print(f"{args.train_list} not found — run split_corpus.py first", file=sys.stderr)
        return 1
    for v in args.vocab_size:
        train_one(args.train_list, v, args.min_frequency, args.normalize,
                  args.out_dir, args.pretok, args.max_train_docs, args.sample_seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
