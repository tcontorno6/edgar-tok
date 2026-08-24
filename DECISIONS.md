# DECISIONS.md — judgment calls that could affect the tokenizer's vocabulary

Running log. Every place the corpus pipeline makes a choice that changes what
characters or strings the tokenizer will see gets an entry here, so any of
them can be ablated later. Status: `planned` = agreed approach, not yet coded;
`implemented` = in the current clean.py.

---

## D-001 · Unicode normalization is OFF by default — `planned`
Curly quotes (' ' " "), em/en dashes, the section sign (§), and the
non-breaking hyphen are part of the vocabulary this tokenizer is supposed to
learn. `clean.py` will ship a `--normalize-unicode` flag (off by default) that
maps them to ASCII, purely so the effect can be ablated. Per project spec.

## D-002 · HTML entities decode to real characters — `planned`
EDGAR files write specials as entities (`&#8217;` → ', `&#160;` → NBSP).
The HTML parser decodes them during parsing; that decoding is not optional.
Consequence: the corpus contains the real Unicode characters, which is what
we want (and is consistent with D-001). NBSP specifically is then replaced
with a plain space per spec — that replacement IS a normalization we do by
default, because NBSP-vs-space carries layout information, not meaning.

## D-003 · Newlines come from block-level tags only — `planned`
Text extraction walks the DOM and emits `\n` at block boundaries (`p`, `div`,
`tr`, `li`, `h1–h6`, `br`, `table`) and nothing at inline boundaries (`span`,
`b`, `i`, `ix:*`, `a`, `font`). Why it matters: iXBRL wraps numbers in inline
`ix:nonFraction` tags mid-sentence — a naive per-node join would shred
"revenues of $3,232,193 for fiscal 2023" across four lines, and the
line-frequency header filter and page-number filter both operate on lines.
Within a table row, cells are joined with a single space (so a row reads
"Total revenues 3,232,193 2,905,674"), which keeps label+number adjacency the
tokenizer should see.

## D-004 · Encoding: strict UTF-8, then cp1252 fallback — `planned`
Both sampled filings decode as clean UTF-8. Older EDGAR documents are
sometimes windows-1252. Decode order: `utf-8` (strict) → `cp1252` (never
fails). Rationale: cp1252-decoding a UTF-8 file would garble curly quotes
(vocabulary damage), while utf-8-strict correctly *rejects* cp1252 bytes, so
this order can't misfire silently. Any file that takes the fallback path gets
logged in the manifest.

## D-005 · Expected survival rate revised upward: ~8–15%, not 3–8% — `observed`
Measured on samples before any line filtering: a 2.4 MB iXBRL 10-K yields
14.2% of raw bytes as text; a 148 KB 13D yields 18.7%. The 3–8% intuition is
right for *full submission* `.txt` files (which bundle exhibits, XBRL zips,
and base64 images), but this corpus holds *primary documents only* — markup
overhead is smaller. After display:none removal (~1.2% of raw on the sample)
and line filtering, expect roughly 8–15%. Numbers outside that band per-file
will be flagged in the manifest, not silently accepted.

## D-006 · 13Ds are plain HTML, not iXBRL — `observed`
The sampled 13D contains zero `ix:` tags (iXBRL was never mandated for
Schedule 13D). The same cleaner handles both; the ix-preservation logic is
simply inert on 13Ds. No separate code path.

## D-007 · display:none nodes are dropped, including hidden XBRL facts — `planned`
Per spec. The sampled 10-K carries ~30k chars inside display:none nodes —
mostly the `ix:header` context/unit machinery and `ix:hidden` facts. These are
duplicated metadata (dates, CIKs, member axes), not prose, and would distort
line statistics. Dropped by inline `style` attribute match only; class-based
hiding is not chased (rare in filings, and chasing classes risks dropping
visible content).

## D-009 · `<head>` (and `<noscript>`) dropped entirely — `implemented`
Document `<title>` in filings is a filename or form code ("sc13da10.htm",
"aciw-20231231"), not prose — it would inject filename-like tokens into the
corpus. Dropped along with `<script>`/`<style>`.

## D-010 · Page-number filter covers "Page N", "F-12", and short roman numerals — `implemented`
Case-insensitive: "Page 21" survived v1 because the pattern was lowercase-only
(211 leaked lines corpus-wide, caught in review). Roman-numeral page lines
match `[ivx]{1,5}` only, so ordinary words that happen to be spellable in
roman-numeral letters ("mix", "did") can never match; the cost is that a line
consisting solely of "vi" or "xi" is dropped — accepted as layout, not prose.

## D-011 · EDGAR SGML wrappers stripped before parsing — `implemented`
305 of the 358 seed files are wrapped in EDGAR SGML
(`<DOCUMENT><TYPE>…<FILENAME>…<DESCRIPTION>…<TEXT>` … `</TEXT>`), whose header
fields render as 3–5 junk lines at the top of each cleaned file (form code,
filename, description). When the wrapper signature is present in the first
512 bytes, only the content between the first `<TEXT>` and last `</TEXT>` is
parsed. Manifest notes record `sgml_wrapper_stripped` per file.

## D-008 · Paper-filing stubs are expected input — `observed`
The corpus contains at least one 291-byte SGML stub ("AUTO-GENERATED PAPER
DOCUMENT", accession 9999999997-…): a placeholder for a filing that only
exists on paper. The `--min-chars` guard (default 5000) is the intended
catch; such files land in the manifest as `skipped_short`, not as errors.

## D-012 · Glued bullets ("•completion of…") left as-is — `observed`
~3.2k lines start with a bullet glyph directly abutting its word, because the
source markup holds `•` and the text in adjacent inline elements with no text
node between them. Not repaired: inserting a space would be invented
whitespace, and GPT-2/Llama-style pretokenizers split punctuation from
letters regardless, so BPE merge learning is unaffected. Revisit only if the
trained vocab shows `•word` merges (it should not, given pretokenization).

## D-013 · Corpus expansion samples ≤1 filing per company, spread over years — `implemented (fetch_10ks.py)`
The expansion fetch walks the quarterly master indexes (2013–2024 default),
takes at most one 10-K per CIK, fills per-year quotas from a seeded shuffle,
and excludes accessions already present in the seed corpus. Rationale: company
diversity beats filing count for vocabulary coverage (249 seed companies
already contribute multiple years), and era spread keeps both plain-HTML and
iXBRL generations represented. Amendments (10-K/A) are excluded — they
substantially duplicate the original document's text.
