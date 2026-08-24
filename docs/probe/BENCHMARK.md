# Tokenizer benchmark — held-out SEC filings

Eval set: 450 documents, 48.8 MB (never seen in training).

## Compression (bytes per token — higher is better)

| tokenizer | vocab | total tokens | bytes/token | vs edgar-bpe-65536 | median 10-K (tokens) |
|---|---|---|---|---|---|
| edgar-bpe-65536 | 65,536 | 10,266,453 | 4.755 | — | 0 |
| edgar-bpe-65536-digits | 65,536 | 9,582,240 | 5.094 | +6.7% tokens | 0 |
| edgar-bpe-65536-line | 65,536 | 6,633,285 | 7.359 | +35.4% tokens | 0 |
| edgar-bpe-131072-line | 131,072 | 6,016,670 | 8.113 | +41.4% tokens | 0 |
| gpt2 | 50,257 | 10,988,193 | 4.442 | -7.0% tokens | 0 |
| cl100k | 100,277 | 10,503,897 | 4.647 | -2.3% tokens | 0 |
| o200k | 200,019 | 10,422,929 | 4.683 | -1.5% tokens | 0 |
| qwen3 | 151,669 | 11,416,254 | 4.276 | -11.2% tokens | 0 |

## Slices (bytes/token)

| tokenizer | 10Q | 8K | DEF14A | pre-2019 | 2019+ |
|---|---|---|---|---|---|
| edgar-bpe-65536 | 4.754 | 4.384 | 4.768 | 4.690 | 4.789 |
| edgar-bpe-65536-digits | 5.242 | 4.696 | 4.996 | 5.081 | 5.101 |
| edgar-bpe-65536-line | 8.044 | 7.378 | 6.895 | 7.300 | 7.390 |
| edgar-bpe-131072-line | 8.917 | 8.132 | 7.574 | 8.034 | 8.154 |
| gpt2 | 4.432 | 4.005 | 4.466 | 4.386 | 4.472 |
| cl100k | 4.610 | 4.288 | 4.689 | 4.625 | 4.659 |
| o200k | 4.641 | 4.323 | 4.729 | 4.658 | 4.696 |
| qwen3 | 4.160 | 3.929 | 4.384 | 4.246 | 4.292 |

## Domain patterns (mean tokens per instance — lower is better)

| pattern | n in eval | edgar-bpe-65536 | edgar-bpe-65536-digits | edgar-bpe-65536-line | edgar-bpe-131072-line | gpt2 | cl100k | o200k | qwen3 |
|---|---|---|---|---|---|---|---|---|---|
| dollar_amount | 51,109 | 4.03 | 1.98 | 3.28 | 3.07 | 4.16 | 4.34 | 4.34 | 6.54 |
| percentage | 24,943 | 3.04 | 1.45 | 2.84 | 2.6 | 3.05 | 4.04 | 4.04 | 5.05 |
| basis_points | 446 | 2.01 | 2.01 | 2.37 | 2.34 | 2.31 | 2.55 | 2.55 | 2.97 |
| cusip_like | 19 | 4.79 | 5 | 6 | 5.74 | 5.11 | 5.16 | 5.11 | 8.89 |
| rule_section_citation | 14,897 | 4.07 | 3.9 | 3.4 | 3.18 | 4.17 | 4.79 | 4.79 | 5.75 |
| section_symbol | 557 | 5.33 | 4.46 | 4.71 | 4.69 | 5.37 | 5.54 | 5.53 | 8.93 |
| big_number | 25,164 | 5.01 | 2.68 | 4.09 | 3.81 | 5.37 | 6.01 | 6.01 | 10.37 |

## Canonical examples (tokens)

| text | edgar-bpe-65536 | edgar-bpe-65536-digits | edgar-bpe-65536-line | edgar-bpe-131072-line | gpt2 | cl100k | o200k | qwen3 |
|---|---|---|---|---|---|---|---|---|
| `$1,234.56` | 6 | 2 | 5 | 4 | 6 | 6 | 6 | 9 |
| `$3,232,193` | 6 | 3 | 5 | 5 | 6 | 6 | 6 | 10 |
| `4.25%` | 4 | 1 | 3 | 3 | 4 | 5 | 5 | 6 |
| `150bps` | 2 | 2 | 3 | 3 | 2 | 3 | 3 | 5 |
| `88160R101` | 4 | 4 | 5 | 5 | 4 | 5 | 5 | 10 |
| `Rule 206(4)-1` | 6 | 6 | 5 | 5 | 6 | 7 | 7 | 9 |
| `§251(h)` | 5 | 5 | 4 | 4 | 5 | 4 | 4 | 6 |
| `Item 1A. Risk Factors` | 6 | 6 | 2 | 2 | 6 | 7 | 7 | 7 |
| `RevenueFromContractWithCustomerExcludingAssessedTax` | 9 | 9 | 12 | 12 | 10 | 10 | 10 | 10 |
| `basis points` | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| `EBITDA margin` | 2 | 2 | 3 | 3 | 4 | 4 | 2 | 4 |
| `the Company’s` | 4 | 4 | 2 | 2 | 5 | 3 | 3 | 3 |
