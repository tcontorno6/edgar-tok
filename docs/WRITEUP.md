# Half the tokens: what I learned training a BPE tokenizer on SEC filings

*Tyler Contorno · August 2026 · code, corpus pipeline, and full benchmark tables: [github.com/tcontorno6/edgar-tok](https://github.com/tcontorno6/edgar-tok)*

Every LLM reads text through a tokenizer, and every tokenizer was trained on
someone's corpus. General-purpose tokenizers were trained on the open web,
so I wanted to measure what that costs on a domain the web underrepresents:
SEC filings, where the text is full of `$1,234.56`, `4.25%`, `150bps`,
CUSIPs, `Rule 206(4)-1`, and GAAP terminology. This is not academic to me. A
screener I built pays per token to have an LLM read 10-Ks, and a full 10-K
runs 50-150k tokens.

So I built a corpus of 4,356 cleaned filings (1.3 GB of text extracted from
raw EDGAR iXBRL, 2010-2024, ~4,250 companies), held out 5% of documents that
no tokenizer ever trained on, trained byte-level BPE tokenizers on the rest,
and benchmarked them against the tokenizers actually shipping today: GPT-2,
GPT-4 (cl100k), GPT-4o/o-series (o200k), and Qwen3. The metric is bytes per
token on the held-out documents: how much filing one token carries.

## Results

| tokenizer | vocab | bytes/token | tokens needed vs mine (65k) | median 10-K |
|---|---|---|---|---|
| **edgar-65k** (same rules as baselines) | 65,536 | **4.87** | baseline | 64,517 |
| **edgar-65k-digits** (numbers kept whole) | 65,536 | **5.27** | 7% fewer | 59,624 |
| **edgar-131k-line** (phrase merges) | 131,072 | **8.94** | 45% fewer | **34,650** |
| GPT-2 | 50,257 | 4.57 | +6.4% | 68,215 |
| GPT-4 · cl100k | 100,277 | 4.77 | +2.1% | 65,472 |
| GPT-4o · o200k | 200,019 | 4.80 | +1.4% | 65,049 |
| Qwen3 | 151,669 | 4.40 | +10.7% | 70,372 |

Four findings, in increasing order of how much they surprised me.

**1. Domain vocabulary alone buys single digits, and that's the honest
number.** Under identical pre-tokenization rules (the fair fight), my 65k
tokenizer beats every current tokenizer, but thinly: GPT-4o's o200k needs
just 1.4% more tokens. The catch is what it took o200k to get there:
**200,019 vocabulary entries to my 65,536**. Filing text is roughly 78%
ordinary English, which web tokenizers already handle well, and the
domain-specific mass is concentrated in patterns that make up a few percent
of characters. A domain tokenizer's real fair-fight claim is vocabulary
*efficiency*: matching the largest general vocabulary ever shipped at a
third of its size.

**2. The current generation has split into camps on financial text, and one
camp fell behind 2019.** Qwen3 needs 10.7% more tokens than my tokenizer,
and more tokens than GPT-2, because it deliberately splits every digit into
its own token (a choice made to help arithmetic reasoning). A dollar amount
costs it 5.9 tokens against GPT-2's 4.0. OpenAI went the other way, and
o200k improved substantially over GPT-2 overall. Yet even OpenAI's modern
tokenizers lost ground on numerals: 4.1 tokens per dollar amount and 4.1
per percentage, against GPT-2's 4.0 and 3.1. Their gains are all prose.
Financial text is numbers; nobody is optimizing for it.

**3. The big compression isn't in vocabulary at all. It's in
pre-tokenization.** BPE merges cannot cross the chunk boundaries drawn
before merging starts, and standard GPT-2-style rules split digit runs at
punctuation and forbid merges across spaces. Relax the first rule and
`4.25%` becomes **one token** (digits mode averages 1.7 tokens per dollar
amount, 2.4x better than o200k). Relax the second and recurring boilerplate
fuses into phrase tokens (`Item 1A. Risk Factors` = 2 tokens). The phrase
tokenizer encodes filings in **half the tokens of anything shipping**:
GPT-4o needs 86% more, GPT-2 95% more, Qwen3 103% more. A median 10-K fits
in 34,650 tokens instead of 65-70k. Label it honestly: that variant changed
the rules, not just the training data, and phrase tokens are a compression
win with unproven downstream-model tradeoffs (see SuperBPE, 2025, for
evidence the idea can work for models too).

**4. It generalizes past its training form, measured rather than assumed.**
The corpus is ~96% annual reports, so I fetched 450 filings of forms the
tokenizer never saw (10-Qs, 8-Ks, merger proxies) as a second eval set.
Every margin held: +1.5% vs o200k, +7.0% vs GPT-2, +11.2% vs Qwen3. The
phrase tokenizer kept about 85% of its advantage, transferring almost
losslessly to 10-Qs (quarterly reports reuse annual-report boilerplate
nearly verbatim) and weakest to proxies. One ablation came back a clean
null: preserving filings' real Unicode (curly quotes, section signs, em
dashes) instead of flattening to ASCII cost 0.3%. Keeping authentic text is
free.

## Limitations, stated plainly

A tokenizer is married to its model's weights, so nobody can drop this into
Llama or GPT. The practical consumers are anyone training or
vocabulary-extending a financial model, and anyone quantifying the token tax
of general-purpose APIs on filings (6-11% under same rules, roughly 2x
against a filings-native design). Compression is the only thing measured
here, not downstream model quality. The phrase tokenizer trained on a
seeded 1,500-doc subsample for memory tractability (recorded in its
metadata). And the corpus is SEC disclosure documents; brokerage
statements, earnings calls, and analyst notes are different dialects I
didn't measure.

Everything is reproducible from the repo: the iXBRL cleaning pipeline
(selectolax, ~25s for 358 filings), the resumable EDGAR fetcher, the split
with content-hash deduplication, training and benchmark scripts, and a
DECISIONS.md logging all 20 judgment calls that could have shaped the
vocabulary. Prior work that deserves the pointer: SEC-BERT and FinBERT
(financial-vocabulary models), EDGAR-CORPUS (a much larger public filing
corpus, 1993-2020), and SuperBPE (superword tokenization).

*Built with Claude as pair-engineer; every number above is from held-out
evaluation.*
