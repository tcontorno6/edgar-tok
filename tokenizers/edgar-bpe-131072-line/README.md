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

# edgar-bpe-131072-line

A byte-level BPE tokenizer trained exclusively on SEC filings, drawn from a
4,356-document, 1.3 GB cleaned EDGAR corpus (2010-2024, ~4,250 companies;
exact training-set size below). Phrase-merge variant: merges may cross spaces within a line, so recurring filing boilerplate fuses into phrase tokens (`Item 1A. Risk Factors` = 2 tokens). Encodes filings in roughly half the tokens of any current general tokenizer.

Every number below is measured on 216 held-out documents no variant ever
trained on; a 450-document cross-form probe (10-Q, 8-K, DEF 14A) confirmed
the margins generalize past the training form. Full methodology, benchmark
tables, and the corpus pipeline: [write-up](https://github.com/tcontorno6/edgar-tok/blob/main/docs/WRITEUP.md) ·
[repository](https://github.com/tcontorno6/edgar-tok).

| metric | value |
|---|---|
| bytes/token on held-out SEC filings | **8.94** |
| tokens needed by GPT-4o (o200k) for the same text | **+86%** |
| tokens needed by GPT-2 | **+95%** |
| tokens needed by Qwen3 | **+103%** |
| median 10-K (GPT-4o: ~65k tokens) | **34,650 tokens** |

## Usage

```python
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("tcontorno/edgar-bpe-131072-line")
tok("Revenues of $3,232,193 for fiscal 2023, an increase of 4.25%.")
```

or with the `tokenizers` library directly:

```python
from tokenizers import Tokenizer
tok = Tokenizer.from_file("tokenizer.json")
```

## Training

Vocab size 131,072, min merge frequency
4, pre-tokenization mode
`line`, 1,500 training
documents, one `<|endoftext|>` special token. Training corpus built from
primary filing documents (iXBRL/HTML cleaned to text with numbers and real
Unicode preserved); 5% held-out split with content-hash deduplication before
any training.

## Caveats

Non-standard pre-tokenization (line-scoped phrase merges) and trained on a seeded 1,500-document subsample for memory tractability (recorded in meta.json). Phrase tokens optimize compression; downstream model quality is an open question (cf. SuperBPE, 2025). A tokenizer is bound to the model trained with it, so
this is a drop-in for new models and tokenizer research, not for existing
checkpoints. Compression is the measured claim; see the write-up for the
full limitations section.
