# edgar-tok

A domain-specific BPE tokenizer for SEC financial filings.

**Hypothesis:** general-purpose tokenizers (GPT-2, Llama 3, Qwen3) waste tokens
on financial text because they never learned merges for CUSIPs (`88160R101`),
basis points (`150bps`), tickers (`$SGRY`), dollar figures (`$1,234.56`),
percentages (`4.25%`), regulatory citations (`Rule 206(4)-1`, `§251(h)`), and
XBRL/GAAP terminology. Deliverable: a published tokenizer + benchmark table +
write-up.

**Current phase: 1 — corpus construction.** No model or tokenizer training yet.

## Layout

```
edgar-tok/
├── docs/
│   ├── FETCHER.md            # reverse-engineering of the old EDGAR fetcher (Task 1)
│   ├── CORPUS_REPORT_v1.md   # inspection results + verdict on the seed corpus (Task 3)
│   └── samples/              # 3 example cleaned documents for eyeballing
├── DECISIONS.md              # every judgment call that could affect the vocabulary
├── clean.py                  # iXBRL/HTML -> clean text, parallel            [done]
├── inspect_corpus.py         # corpus statistics + domain-pattern rates      [done]
├── fetch_10ks.py             # resumable bulk 10-K fetch (overnight job)     [ready to run]
├── edgar_min/                # EDGAR client vendored from ma-target-screener (no DB)
├── data/                     # gitignored — corpus is rebuildable, git holds only code
│   ├── clean/                # cleaned .txt + manifest.csv (from clean.py)
│   └── raw/                  # expansion 10-Ks + fetch_manifest.csv (from fetch_10ks.py)
├── requirements.txt
└── setup.ps1                 # venv + deps + git init (one-time)
```

Seed corpus (Phase 1 input): `..\ma-target-screener\data\filings\stage2\` —
358 primary documents (249 10-K, 109 13D; 249 companies; 0.69 GB; 2010–2023),
read in place, never modified.

## Setup (one-time, PowerShell)

```powershell
cd C:\Users\Tyler\Desktop\edgar-tok
powershell -ExecutionPolicy Bypass -File .\setup.ps1
.\.venv\Scripts\Activate.ps1
```

## Running Phase 1

**1. Clean the seed corpus** (~5 s on the 24-core box; deterministic — this
reproduces exactly the corpus described in docs/CORPUS_REPORT_v1.md):

```powershell
python clean.py --input ..\ma-target-screener\data\filings\stage2 --output data\clean
python inspect_corpus.py --corpus data\clean
```

**2. Expand the corpus** (overnight; resumable — re-run the same command after
any interruption). The SEC requires a real-contact User-Agent on every request:

```powershell
$env:EDGAR_USER_AGENT = "Tyler Contorno tyler.contorno1234@gmail.com"
# smoke tests first:
python fetch_10ks.py --dry-run --index-cache-src ..\ma-target-screener\data\cache\edgar
python fetch_10ks.py --limit 3 --index-cache-src ..\ma-target-screener\data\cache\edgar
# the real run:
python fetch_10ks.py --target 4000 --index-cache-src ..\ma-target-screener\data\cache\edgar
```

`--index-cache-src` points at the old project's 60 already-downloaded quarterly
master indexes (read-only) so 2013–2024 selection needs no index downloads;
only 2025+ quarters would be fetched fresh. Expect ~4,000 filings ≈ 8–12 GB
over a few hours (bandwidth-bound; request budget is ~17 min at 8 req/s).

**3. Clean the expansion** (same cleaner, new input):

```powershell
python clean.py --input data\raw --output data\clean_expansion
python inspect_corpus.py --corpus data\clean_expansion
```

## Running Phase 2 (train + benchmark)

```powershell
pip install -r requirements.txt                  # picks up tokenizers + transformers
python split_corpus.py                           # held-out eval set FIRST (D-014)
python train_tokenizer.py --vocab-size 32768 65536 131072
python train_tokenizer.py --vocab-size 65536 --normalize    # D-001 ablation twin
python benchmark.py --ours tokenizers\edgar-bpe-32768 tokenizers\edgar-bpe-65536 tokenizers\edgar-bpe-131072 tokenizers\edgar-bpe-65536-norm
```

Phase 2.5 — the pre-tokenization ladder (D-019), after the standard runs:

```powershell
python train_tokenizer.py --vocab-size 65536 --pretok digits
python train_tokenizer.py --vocab-size 65536 131072 --pretok line
python benchmark.py --ours tokenizers\edgar-bpe-65536 tokenizers\edgar-bpe-65536-digits tokenizers\edgar-bpe-65536-line tokenizers\edgar-bpe-131072-line
```

Results land in `docs\BENCHMARK.md` + `docs\benchmark_per_doc.csv`. Baselines:
GPT-2 and Qwen download from the Hugging Face hub; cl100k/o200k (GPT-4 /
GPT-4o) come from OpenAI's official BPE files via tiktoken;
**Llama 3 is license-gated** — accept it at
huggingface.co/meta-llama/Meta-Llama-3-8B, then `pip install huggingface_hub[cli]`
and `hf auth login`, and rerun. Unavailable baselines are skipped
with a warning, never fatal.

Cross-form probe (D-020) — measure generalization to forms never trained on:

```powershell
python fetch_10ks.py --forms "10-Q,8-K,DEF 14A" --target 450 --years 2015-2024 --out data\raw_probe --index-cache-src ..\ma-target-screener\data\cache\edgar
python clean.py --input data\raw_probe --output data\clean_probe --min-chars 1500
python benchmark.py --ours tokenizers\edgar-bpe-65536 tokenizers\edgar-bpe-65536-digits tokenizers\edgar-bpe-65536-line tokenizers\edgar-bpe-131072-line --eval-dir data\clean_probe --out-dir docs\probe
```

## Phase plan

1. **Corpus** — seed cleaned ✔ (357 docs, 82 MB, ~20.5M tokens); expansion
   fetch ready to run.
2. **Train** — BPE on the cleaned corpus (multiple vocab sizes; the
   `--normalize-unicode` ablation is pre-wired via DECISIONS.md D-001).
3. **Benchmark** — tokens/byte and tokens/document vs GPT-2, Llama 3, Qwen3 on
   held-out filings, with per-pattern breakdowns. XBRL companyfacts JSON as a
   numerics-dense targeted set (fetch per company via
   `edgar_min.EdgarClient.company_facts` — they are NOT in the old cache; see
   docs/FETCHER.md).
4. **Write-up** — [docs/WRITEUP.md](docs/WRITEUP.md); tokenizers published to
   the Hugging Face Hub via `publish_hf.py`.

## License

MIT — see [LICENSE](LICENSE).
