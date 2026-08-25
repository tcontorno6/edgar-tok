#!/usr/bin/env python3
"""publish_hf.py — publish edgar-tok tokenizers to the Hugging Face Hub.

For each tokenizer directory given, this script:
  1. writes a tokenizer_config.json so `AutoTokenizer.from_pretrained(...)`
     works out of the box,
  2. generates a model card (README.md) with that variant's benchmark
     numbers, training summary, and caveats,
  3. creates the Hub repo <your-username>/<dir-name> and uploads the folder.

One-time setup:
  1. Create a free account at https://huggingface.co/join
  2. Make a WRITE token: Settings -> Access Tokens -> Create new token (Write)
  3. pip install -U "huggingface_hub[cli]"   (already present via transformers)
  4. hf auth login        (paste the token)

Then:
  python publish_hf.py tokenizers\\edgar-bpe-65536 tokenizers\\edgar-bpe-65536-digits tokenizers\\edgar-bpe-131072-line
  python publish_hf.py --dry-run ...   # generate files locally, upload nothing

Your Hub username is read from the logged-in token (no flag needed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_URL = "https://github.com/tcontorno6/edgar-tok"
WRITEUP_URL = f"{REPO_URL}/blob/main/docs/WRITEUP.md"

# Per-variant benchmark blurbs (held-out eval, 216 docs / 64.4 MB; see repo).
VARIANTS: dict[str, dict] = {
    "edgar-bpe-65536": dict(
        headline="The fair-fight variant: identical pre-tokenization rules to "
                 "GPT-2/GPT-4/GPT-4o/Qwen3, so the comparison isolates vocabulary.",
        stats=[
            ("bytes/token on held-out SEC filings", "4.87"),
            ("tokens needed by GPT-2 for the same text", "+6.4%"),
            ("tokens needed by GPT-4 (cl100k)", "+2.1%"),
            ("tokens needed by GPT-4o (o200k, 200k vocab)", "+1.4%"),
            ("tokens needed by Qwen3", "+10.7%"),
        ],
        caveats="Trained with standard GPT-2-style byte-level pre-tokenization; "
                "no special caveats.",
    ),
    "edgar-bpe-65536-digits": dict(
        headline="Number-aware variant: dollar amounts, percentages, and "
                 "comma-grouped figures are kept whole during pre-tokenization, "
                 "so BPE can fuse them.",
        stats=[
            ("bytes/token on held-out SEC filings", "5.27"),
            ("mean tokens per dollar amount (GPT-4o: 4.1)", "1.72"),
            ("mean tokens per percentage, e.g. `4.25%` = 1 token (GPT-4o: 4.1)", "1.34"),
            ("tokens needed by GPT-2 for the same text", "+15%"),
        ],
        caveats="Non-standard pre-tokenization (digit runs kept whole): "
                "compression comparisons against standard tokenizers should "
                "say so. Downstream model quality not evaluated.",
    ),
    "edgar-bpe-131072-line": dict(
        headline="Phrase-merge variant: merges may cross spaces within a line, "
                 "so recurring filing boilerplate fuses into phrase tokens "
                 "(`Item 1A. Risk Factors` = 2 tokens). Encodes filings in "
                 "roughly half the tokens of any current general tokenizer.",
        stats=[
            ("bytes/token on held-out SEC filings", "8.94"),
            ("tokens needed by GPT-4o (o200k) for the same text", "+86%"),
            ("tokens needed by GPT-2", "+95%"),
            ("tokens needed by Qwen3", "+103%"),
            ("median 10-K (GPT-4o: ~65k tokens)", "34,650 tokens"),
        ],
        caveats="Non-standard pre-tokenization (line-scoped phrase merges) and "
                "trained on a seeded 1,500-document subsample for memory "
                "tractability (recorded in meta.json). Phrase tokens optimize "
                "compression; downstream model quality is an open question "
                "(cf. SuperBPE, 2025).",
    ),
}

TOKENIZER_CONFIG = {
    "tokenizer_class": "PreTrainedTokenizerFast",
    "model_max_length": 1000000000,
    "eos_token": "<|endoftext|>",
}


def model_card(name: str, meta: dict, variant: dict) -> str:
    stats_rows = "\n".join(f"| {k} | **{v}** |" for k, v in variant["stats"])
    return f"""---
license: mit
language: en
tags:
- tokenizer
- bpe
- finance
- sec-filings
- edgar
library_name: transformers
---

# {name}

A byte-level BPE tokenizer trained exclusively on SEC filings, drawn from a
4,356-document, 1.3 GB cleaned EDGAR corpus (2010-2024, ~4,250 companies;
exact training-set size below). {variant["headline"]}

Every number below is measured on 216 held-out documents no variant ever
trained on; a 450-document cross-form probe (10-Q, 8-K, DEF 14A) confirmed
the margins generalize past the training form. Full methodology, benchmark
tables, and the corpus pipeline: [write-up]({WRITEUP_URL}) ·
[repository]({REPO_URL}).

| metric | value |
|---|---|
{stats_rows}

## Usage

```python
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("{{namespace}}/{name}")
tok("Revenues of $3,232,193 for fiscal 2023, an increase of 4.25%.")
```

or with the `tokenizers` library directly:

```python
from tokenizers import Tokenizer
tok = Tokenizer.from_file("tokenizer.json")
```

## Training

Vocab size {meta.get("vocab_size"):,}, min merge frequency
{meta.get("min_frequency")}, pre-tokenization mode
`{meta.get("pretokenizer", "gpt2")}`, {meta.get("n_train_docs"):,} training
documents, one `<|endoftext|>` special token. Training corpus built from
primary filing documents (iXBRL/HTML cleaned to text with numbers and real
Unicode preserved); 5% held-out split with content-hash deduplication before
any training.

## Caveats

{variant["caveats"]} A tokenizer is bound to the model trained with it, so
this is a drop-in for new models and tokenizer research, not for existing
checkpoints. Compression is the measured claim; see the write-up for the
full limitations section.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+", type=Path, help="tokenizer directories to publish")
    ap.add_argument("--dry-run", action="store_true",
                    help="write README/config into the local dirs, upload nothing")
    ap.add_argument("--private", action="store_true", help="create repos as private")
    args = ap.parse_args()

    namespace = "YOUR-HF-USERNAME"
    if not args.dry_run:
        from huggingface_hub import HfApi
        api = HfApi()
        namespace = api.whoami()["name"]
        print(f"logged in as: {namespace}")

    for d in args.dirs:
        if not (d / "tokenizer.json").exists():
            print(f"!! {d}: no tokenizer.json — skipped", file=sys.stderr)
            continue
        meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
        variant = VARIANTS.get(d.name, dict(
            headline="Experimental variant; see repo for details.",
            stats=[("vocab size", f"{meta.get('vocab_size', '?'):,}")],
            caveats="See the repository's DECISIONS.md.",
        ))

        (d / "tokenizer_config.json").write_text(
            json.dumps(TOKENIZER_CONFIG, indent=2), encoding="utf-8")
        card = model_card(d.name, meta, variant).replace("{namespace}", namespace)
        (d / "README.md").write_text(card, encoding="utf-8")
        print(f"prepared {d.name}: tokenizer_config.json + README.md")

        if args.dry_run:
            continue
        repo_id = f"{namespace}/{d.name}"
        api.create_repo(repo_id, repo_type="model", private=args.private, exist_ok=True)
        api.upload_folder(folder_path=str(d), repo_id=repo_id, repo_type="model")
        print(f"published: https://huggingface.co/{repo_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
