# Tokenizer benchmark — held-out SEC filings

Eval set: 216 documents, 64.4 MB (never seen in training).

\* starred tokenizers are evaluated on unicode-normalized input — their native distribution (DECISIONS D-018).

## Compression (bytes per token — higher is better)

| tokenizer | vocab | total tokens | bytes/token | vs edgar-bpe-65536 | median 10-K (tokens) |
|---|---|---|---|---|---|
| edgar-bpe-65536 | 65,536 | 13,236,022 | 4.866 | — | 64,517 |
| edgar-bpe-65536-norm* | 65,536 | 13,201,893 | 4.879 | +0.3% tokens | 64,417 |
| edgar-bpe-65536-digits | 65,536 | 12,224,989 | 5.269 | +7.6% tokens | 59,624 |
| edgar-bpe-65536-line | 65,536 | 7,986,961 | 8.065 | +39.7% tokens | 38,376 |
| edgar-bpe-131072-line | 131,072 | 7,208,013 | 8.936 | +45.5% tokens | 34,650 |
| gpt2 | 50,257 | 14,082,201 | 4.574 | -6.4% tokens | 68,215 |
| cl100k | 100,277 | 13,513,792 | 4.766 | -2.1% tokens | 65,472 |
| o200k | 200,019 | 13,416,315 | 4.801 | -1.4% tokens | 65,049 |
| qwen3 | 151,669 | 14,652,606 | 4.396 | -10.7% tokens | 70,372 |

## Slices (bytes/token)

| tokenizer | 10K | 13D | pre-2019 | 2019+ |
|---|---|---|---|---|
| edgar-bpe-65536 | 4.867 | 4.228 | 4.780 | 4.943 |
| edgar-bpe-65536-norm* | 4.880 | 4.236 | 4.793 | 4.956 |
| edgar-bpe-65536-digits | 5.270 | 4.545 | 5.231 | 5.302 |
| edgar-bpe-65536-line | 8.068 | 5.966 | 7.907 | 8.205 |
| edgar-bpe-131072-line | 8.939 | 6.910 | 8.731 | 9.120 |
| gpt2 | 4.575 | 3.740 | 4.495 | 4.644 |
| cl100k | 4.767 | 4.050 | 4.707 | 4.819 |
| o200k | 4.802 | 4.091 | 4.741 | 4.854 |
| qwen3 | 4.397 | 3.773 | 4.320 | 4.463 |

## Domain patterns (mean tokens per instance — lower is better)

| pattern | n in eval | edgar-bpe-65536 | edgar-bpe-65536-norm* | edgar-bpe-65536-digits | edgar-bpe-65536-line | edgar-bpe-131072-line | gpt2 | cl100k | o200k | qwen3 |
|---|---|---|---|---|---|---|---|---|---|---|
| dollar_amount | 70,876 | 3.89 | 3.89 | 1.72 | 3.07 | 2.91 | 3.97 | 4.1 | 4.1 | 5.89 |
| percentage | 27,380 | 3.09 | 3.09 | 1.34 | 2.8 | 2.53 | 3.09 | 4.09 | 4.09 | 5.03 |
| basis_points | 630 | 2.0 | 2.0 | 2.0 | 2.26 | 2.21 | 2.15 | 2.27 | 2.27 | 2.49 |
| cusip_like | 42 | 4.29 | 4.29 | 4.29 | 5.48 | 5.36 | 4.67 | 4.64 | 4.64 | 7.93 |
| rule_section_citation | 17,047 | 3.46 | 3.46 | 3.44 | 2.67 | 2.56 | 3.66 | 4.33 | 4.33 | 5.18 |
| section_symbol | 308 | 4.73 | 4.73 | 3.05 | 4.34 | 4.17 | 4.78 | 5.03 | 5.03 | 8.6 |
| big_number | 28,307 | 5.01 | 5.01 | 2.68 | 4.07 | 3.79 | 5.37 | 6.01 | 6.01 | 10.38 |

## Canonical examples (tokens)

| text | edgar-bpe-65536 | edgar-bpe-65536-norm* | edgar-bpe-65536-digits | edgar-bpe-65536-line | edgar-bpe-131072-line | gpt2 | cl100k | o200k | qwen3 |
|---|---|---|---|---|---|---|---|---|---|
| `$1,234.56` | 6 | 6 | 2 | 5 | 4 | 6 | 6 | 6 | 9 |
| `$3,232,193` | 6 | 6 | 3 | 5 | 5 | 6 | 6 | 6 | 10 |
| `4.25%` | 4 | 4 | 1 | 3 | 3 | 4 | 5 | 5 | 6 |
| `150bps` | 2 | 2 | 2 | 3 | 3 | 2 | 3 | 3 | 5 |
| `88160R101` | 4 | 4 | 4 | 5 | 5 | 4 | 5 | 5 | 10 |
| `Rule 206(4)-1` | 6 | 6 | 6 | 5 | 5 | 6 | 7 | 7 | 9 |
| `§251(h)` | 5 | 5 | 5 | 4 | 4 | 5 | 4 | 4 | 6 |
| `Item 1A. Risk Factors` | 6 | 6 | 6 | 2 | 2 | 6 | 7 | 7 | 7 |
| `RevenueFromContractWithCustomerExcludingAssessedTax` | 9 | 9 | 9 | 12 | 12 | 10 | 10 | 10 | 10 |
| `basis points` | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| `EBITDA margin` | 2 | 2 | 2 | 3 | 3 | 4 | 4 | 2 | 4 |
| `the Company’s` | 4 | 3 | 4 | 2 | 2 | 5 | 3 | 3 | 3 |
