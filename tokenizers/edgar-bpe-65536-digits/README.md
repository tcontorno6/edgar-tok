---
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

# edgar-bpe-65536-digits

A byte-level BPE tokenizer trained exclusively on SEC filings, drawn from a
4,356-document, 1.3 GB cleaned EDGAR corpus (2010-2024, ~4,250 companies;
exact training-set size below). Number-aware variant: dollar amounts, percentages, and comma-grouped figures are kept whole during pre-tokenization, so BPE can fuse them.

Every number below is measured on 216 held-out documents no variant ever
trained on; a 450-document cross-form probe (10-Q, 8-K, DEF 14A) confirmed
the margins generalize past the training form. Full methodology, benchmark
tables, and the corpus pipeline: [write-up](https://github.com/tcontorno6/edgar-tok/blob/main/docs/WRITEUP.md) ·
[repository](https://github.com/tcontorno6/edgar-tok).

| metric | value |
|---|---|
| bytes/token on held-out SEC filings | **5.27** |
| mean tokens per dollar amount (GPT-4o: 4.1) | **1.72** |
| mean tokens per percentage, e.g. `4.25%` = 1 token (GPT-4o: 4.1) | **1.34** |
| tokens needed by GPT-2 for the same text | **+15%** |

## Usage

```python
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("tcontorno/edgar-bpe-65536-digits")
tok("Revenues of $3,232,193 for fiscal 2023, an increase of 4.25%.")
```

or with the `tokenizers` library directly:

```python
from tokenizers import Tokenizer
tok = Tokenizer.from_file("tokenizer.json")
```

## Training

Vocab size 65,536, min merge frequency
2, pre-tokenization mode
`digits`, 4,140 training
documents, one `<|endoftext|>` special token. Training corpus built from
primary filing documents (iXBRL/HTML cleaned to text with numbers and real
Unicode preserved); 5% held-out split with content-hash deduplication before
any training.

## Caveats

Non-standard pre-tokenization (digit runs kept whole): compression comparisons against standard tokenizers should say so. Downstream model quality not evaluated. A tokenizer is bound to the model trained with it, so
this is a drop-in for new models and tokenizer research, not for existing
checkpoints. Compression is the measured claim; see the write-up for the
full limitations section.
