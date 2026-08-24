# Corpus report — v1 (seed corpus, 358 filings)

*Produced 2026-08-23 by `clean.py` + `inspect_corpus.py` on the 358 seed
filings from ma-target-screener. Run: 357 ok, 1 skipped (the 291-byte
paper-filing stub, by design), 0 errors. 691.7 MB raw → 82.4 MB clean
(11.9% survival — inside the revised 8–15% expectation from DECISIONS D-005).*

## Verdict

**Clean enough to train a v1 tokenizer on.** The text is coherent English
prose with the domain vocabulary the project hypothesizes: 88k dollar
amounts (1,075 per million chars), 33k percentages (400/M), 21k rule/section
citations (261/M), 585 literal `§`, ~80k curly quotes, 9k em-dashes — all
preserved as real Unicode per D-001. Zero XBRL leakage: no `us-gaap:`
strings, no `ix:` tags, no HTML tags survive anywhere in the corpus, and the
canary value (`3,232,193` inside an `ix:nonFraction` in the CIK-2178 10-K)
comes through intact. Numbers keep their label context in flattened tables
("Total revenues 3,366,917 2,025,204 1,022,422"), which is exactly the
adjacency a financial tokenizer should see.

Three findings you should know about before Phase 2, none of which block
training:

1. **Ticker-like `$SGRY` tokens basically don't exist here (2 occurrences
   in 82M chars).** Filings write "our common stock"; cashtags are
   analyst/social-media dialect. If `$TICKER` compression matters for the
   benchmark, this corpus will not teach it — that vocabulary needs a
   different source (or drop it from the hypothesis for the filing-trained
   model and measure it as an out-of-domain probe, which is arguably the
   more interesting experiment).
2. **CUSIP density is real but thin: 310 "CUSIP" keyword hits, 119
   9-char-with-letter CUSIP-shaped tokens.** They live almost entirely in
   the 109 13D cover pages. All-digit CUSIPs can't be distinguished from
   plain 9-digit numbers by regex, so the true count is somewhat higher.
   Expanding the corpus with more 13Ds — or keeping the planned
   companyfacts/13D evaluation set — is the right lever if CUSIP merges are
   a first-class goal.
3. **Digits are 3.5% of characters.** Most of a 10-K's numeric mass sits in
   tables whose markup weight we strip; what survives is the numbers
   themselves plus prose. That is a fine training mix, but if you want a
   numerals-heavy ablation corpus later, the XBRL companyfacts JSON (fetched
   per company, one API call each — they are NOT in your old cache, see
   FETCHER.md) is the dense source.

## Known imperfections, quantified (deliberate keeps, not bugs)

- **Repeated short table labels survive across documents** ("Shares" ×466,
  "Total assets" ×351, "PART II" ×382, "None." ×664). The header filter is
  per-document (by design — it targets running headers); these lines repeat
  ≤5× within any single document and are legitimate, high-value domain
  vocabulary, so they stay.
- **626 lines exceed 2,000 chars.** Spot-checking shows most are real long
  paragraphs (e.g. an Avon 10-K's Venezuela currency discussion), not
  broken tables. Harmless for BPE training.
- **614 digit-dense lines** (>50% digits) — flattened financial-table rows.
  Kept on purpose; they carry the `1,234,567`-style patterns the tokenizer
  must learn.
- **~3.2k bullet glyphs glued to their word** ("•completion of…") where the
  source markup put `•` and text in adjacent inline elements with no text
  space. Left as-is (D-012): GPT-2/Llama-style pretokenizers split
  punctuation from letters anyway, so merge learning is unaffected.
- **Checkbox glyphs** ☐ ×1,101, þ ×240, ☑ ×86 — authentic EDGAR cover-page
  artifacts (þ is a Wingdings checked-box that filers embed literally).
  Kept: they are part of what SEC text really looks like.
- **Signature blocks and exhibit boilerplate remain** ("/s/ Kevin J.
  Roycraft", POA language). Authentic filing text, in-domain; removing it
  would be curation, not cleaning.

## Fixed during review (v1 → v1.1 of clean.py)

- EDGAR SGML wrappers (`<DOCUMENT><TYPE>…<TEXT>`) were leaking 3–5 header
  junk lines (form code, filename, description) at the top of **305 of 358**
  files → now stripped pre-parse (D-011).
- "Page 21"-style lines survived because the page filter was
  case-sensitive — 211 leaked lines corpus-wide → filter now
  case-insensitive (D-010); zero survive.

## Headline numbers

| metric | value |
|---|---|
| documents | 357 (248 10-K + 109 13D) |
| size | 82.1M chars ≈ 82 MB ≈ **20.5M tokens** (chars÷4) |
| doc length | median 237k chars; p10 9.9k (13Ds); p90 487k; max 830k |
| composition | 77.7% letters · 15.8% whitespace · 3.5% digits · 2.9% punct/symbols |
| survival | median ratio 0.143; spread p5 0.050 / p95 0.327; 4 explained outliers |

Full inspector output follows.

---

```
========================================================================
CORPUS
========================================================================
  files:            357
  total size:       82.1M chars (~82 MB as UTF-8)
  doc length chars: mean 230,000  median 236,658  p10 9,924  p90 487,148  min 5,452  max 830,475
  rough tokens:     ~20.5M (chars / 4)

CHARACTER COMPOSITION
  letters        63,808,920  (77.71%)
  digits          2,885,853  ( 3.51%)
  whitespace     13,004,199  (15.84%)
  punctuation     2,410,488  ( 2.94%)
  other                 377  ( 0.00%)
  notable chars: '’'×49,750  '“'×28,953  '—'×9,170  '§'×585  '☐'×1,101  'þ'×240  '☑'×86

DOMAIN PATTERNS (count | per million chars)
  dollar_amount ($1,234.56 / $77 million)                    88,228 |   1074.5
  percentage (4.25%)                                         32,847 |    400.0
  basis_points (150bps / basis points)                          670 |      8.2
  cusip_keyword ('CUSIP')                                       310 |      3.8
  cusip_like (9-char alnum w/ letter, e.g. 88160R101)           119 |      1.4
  ticker_like ($SGRY)                                             2 |      0.0
  rule_section_citation (Rule 206(4)-1, Section 13(d), Item 1A)    21,415 |    260.8
  section_symbol (§251(h))                                      497 |      6.1
  us_gaap_leak (us-gaap: — should be ~0)                          0 |      0.0
  ix_tag_leak (<ix: — should be 0)                                0 |      0.0

JUNK HUNT
  lines >2000 chars (run-on table rows): 626
  digit-dense lines (>50% digits, len>20): 614
  top 15 most frequent surviving lines corpus-wide:
      664×  None.
      466×  Shares
      382×  PART II
      380×  PART III
      372×  PART I
      367×  PART IV
      353×  SIGNATURES
      351×  Total assets
      344×  Accumulated
      337×  (1)
      334×  (2)
      324×  Report of Independent Registered Public Accounting Firm
      324×  Cash and cash equivalents
      318×  (a)
      304×  Amount
  ratio outliers outside [0.03, 0.45]: 4
    0.0220  0000817135_000134100416001257_13D.htm
    0.0288  0000035214_000003521420000009_10K.htm
    0.4542  0001371446_000106299316009083_13D.htm
    0.9361  0001493761_000104432112000034_13D.htm

========================================================================
RANDOM SAMPLE — 0001654151_000165415123000003_10K.txt, lines 456..496
========================================================================
  | The term of individual patents depends upon the legal term of the patents in the countries in which they are obtained. In most countries in which we file, the p
  | In the U.S., the term of a patent covering an FDA-approved drug may, in certain cases, be eligible for a patent term extension under the Drug Price Competition 
  | 
  | Waxman Act, as compensation for the loss of patent term during FDA regulatory review process. The period of extension may be up to five years, but cannot extend
  | In addition to patent protection, we also rely on trade secret protection for our proprietary information that is not amenable to, or that we do not consider ap
  | 
  | Government Regulation
  | Government authorities in the U.S. at the federal, state, and local level and in other countries extensively regulate, among other things, the research and clin
  | Drugs are also subject to other federal, state, and local statutes and regulations. The process of obtaining regulatory approvals and the subsequent compliance 
  | U.S. Drug Development
  | In the U.S., the FDA regulates drugs under the Federal Food, Drug, and Cosmetic Act (FDCA) and its implementing regulations. Drugs are also subject to other fed
  | •completion of extensive preclinical, sometimes referred to as nonclinical, laboratory tests, animal studies, and formulation studies all performed in accordanc
  | •submission to the FDA of an IND, which must become effective before human clinical trials may begin and must be updated annually;
  | •performance of adequate and well-controlled human clinical trials in accordance with applicable IND and other clinical trial-related regulations, sometimes ref
  | •submission to the FDA of a NDA for a new drug;
  | 
  | •a determination by the FDA within 60 days of its receipt of a NDA to file the NDA for review;
  | •satisfactory completion of an FDA pre-approval inspection of the manufacturing facility or facilities at which the active pharmaceutical ingredient (API) and f
  | •potential FDA audit of the clinical trial sites that generated the data in support of the NDA; and
  | •FDA review and approval of the NDA prior to any commercial marketing or sale of the drug in the U.S.
  | The data required to support a NDA are generated in two distinct development stages: preclinical and clinical. For new chemical entities, the preclinical develo
  | The clinical-stage of development involves the administration of the drug candidate to human subjects under the supervision of qualified investigators, generall
  | Clinical trials are generally conducted in three sequential phases that may overlap or be combined, known as Phase 1, Phase 2, and Phase 3 trials. Phase 1 trial
  | A pivotal study is a clinical study that adequately meets regulatory agency requirements for the evaluation of a drug candidate's efficacy and safety such that 
  | 
  | Progress reports detailing the results of the clinical trials must be submitted at least annually to the FDA and written IND safety reports must be submitted to
  | A manufacturer of an investigational drug for a serious disease or condition is required to make available, such as by posting on its website, its policy on eva
  | Moreover, the Right to Try Act, among other things, provides a federal framework for certain patients to access certain investigational new drug products that h
  | NDA and the FDA Review Process
  | Following trial completion, trial data are analyzed to assess safety and efficacy. The results of preclinical studies and clinical trials are then submitted to 
  | Under the Prescription Drug User Fee Act (PDUFA), as amended, each NDA must be accompanied by a user fee. The FDA adjusts the PDUFA user fees on an annual basis
  | Within 60 days following submission of an original NDA, the FDA reviews the application to determine if it is substantially complete before the agency accepts i
  | 
  | event, the application must be resubmitted with the additional information. The resubmitted application also is subject to review before the FDA accepts it for 
  | After the NDA submission is accepted for filing, the FDA reviews the NDA to determine, among other things, whether the proposed drug is safe and effective for i
  | Before approving a NDA, the FDA typically conducts a pre-approval inspection of the manufacturing facilities for the new drug to determine whether they comply w
  | There is no assurance that the FDA will ultimately approve a drug product for marketing in the U.S. and we may encounter significant difficulties or costs durin
  | Special FDA Expedited Review and Approval Programs
  | The FDA has various programs, including fast track designation, priority review, accelerated approval, and breakthrough designation, that are intended to expedi
  | 
```
