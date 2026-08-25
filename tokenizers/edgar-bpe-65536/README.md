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

# edgar-bpe-65536

A byte-level BPE tokenizer trained exclusively on SEC filings, drawn from a
4,356-document, 1.3 GB cleaned EDGAR corpus (2010-2024, ~4,250 companies;
exact training-set size below). The fair-fight variant: identical pre-tokenization rules to GPT-2/GPT-4/GPT-4o/Qwen3, so the comparison isolates vocabulary.

Every number below is measured on 216 held-out documents no variant ever
trained on; a 450-document cross-form probe (10-Q, 8-K, DEF 14A) confirmed
the margins generalize past the training form. Full methodology, benchmark
tables, and the corpus pipeline: [write-up](https://github.com/tcontorno6/edgar-tok/blob/main/docs/WRITEUP.md) ·
[repository](https://github.com/tcontorno6/edgar-tok).

| metric | value |
|---|---|
| bytes/token on held-out SEC filings | **4.87** |
| tokens needed by GPT-2 for the same text | **+6.4%** |
| tokens needed by GPT-4 (cl100k) | **+2.1%** |
| tokens needed by GPT-4o (o200k, 200k vocab) | **+1.4%** |
| tokens needed by Qwen3 | **+10.7%** |

## Usage

```python
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("tcontorno/edgar-bpe-65536")
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
`gpt2`, 4,140 training
documents, one `<|endoftext|>` special token. Training corpus built from
primary filing documents (iXBRL/HTML cleaned to text with numbers and real
Unicode preserved); 5% held-out split with content-hash deduplication before
any training.

## Caveats

Trained with standard GPT-2-style byte-level pre-tokenization; no special caveats. A tokenizer is bound to the model trained with it, so
this is a drop-in for new models and tokenizer research, not for existing
checkpoints. Compression is the measured claim; see the write-up for the
full limitations section.
