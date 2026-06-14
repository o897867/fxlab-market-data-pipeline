# MacroPulse — Central-Bank Communication Parsing & Event-Attribution

*中文版：[WRITEUP.zh.md](WRITEUP.zh.md)*

> An LLM-driven pipeline that turns Fed FOMC statements and minutes into structured
> hawk-dove metrics, tracks wording changes across meetings, scores each release with
> a calibrated rubric, and backtests those scores against the gold market's actual
> reaction — with an evaluation harness wired into CI as the project's backbone.

Built as the second phase of **FXLab** (a market-data pipeline on AWS S3/Lambda/EC2),
reusing its data lake and minute-level XAU price feed.

---

## Why this exists

A central bank's policy stance lives in the *wording* of its statements. Markets move
on the delta between this meeting's language and last meeting's. The thesis: that delta
is measurable, and a model's hawk-dove read can be checked against ground truth — the
price reaction — rather than graded on vibes.

So MacroPulse is not "an LLM that scores Fed statements." It is a scored system with an
**evaluation loop**: every score is (a) sourced to a verbatim quote, (b) regression-tested
when prompts change, and (c) backtested against the market and routed to human review when
the two disagree.

---

## Architecture (five layers)

```
 Ingestion  →  Diff engine  →  Extraction  →  Attribution  →  Serving
 (S3 raw)      (red-line)      (hawk-dove)    (vs XAU)        (FastAPI + React)
                                    ↑
                              Eval harness (CI regression + drift + adjudication queue)
```

### 1. Ingestion (`macropulse/`)
A Lambda-style scraper pulls Fed FOMC **statements** and **full minutes** from the FOMC
calendar page (the single reliable source — the yearly press-release archive omits
statements, and the "minutes released" press blurb is *not* the minutes body). Documents
are deduped by content hash and written to the S3 raw layer with an idempotent manifest.

Backfill covers ~3 years: **44 statements + 43 minutes** (~2.3M chars). A real bug caught
here: Fed pages don't declare a charset, so `requests` decoded UTF-8 as Latin-1 and turned
en-dashes (`April 28–29`) into mojibake — fixed by detecting the true encoding, which
matters because the downstream schema requires verbatim quotes.

### 2. Diff engine (`diff.py`) — deterministic, no LLM
Needleman-Wunsch paragraph alignment + word-level diff between adjacent statements,
rendered as a wdiff-style red-line. FOMC statements are structurally parallel (same ~8
paragraphs), so alignment is clean. This is the skeleton of the "AI red-line" — the LLM
later only labels each change's *direction*, it never transcribes the text (saves tokens
and removes a transcription-error surface).

### 3. Extraction (`extraction/`) — Claude API, structured output
Each statement/minutes is scored against a calibrated rubric into a Pydantic schema:
`overall_score ∈ [-5,+5]`, four dimensions (inflation / labor / balance-sheet-QT /
forward-guidance) each with `score + key_quote + confidence`, plus per-diff direction
labels. Design choices that matter:

- **Verbatim sourcing**: every `key_quote` is validated as a substring of the source
  text; a non-verbatim quote auto-flags `needs_human_review`. This is the provenance
  guarantee the front-end relies on.
- **Calibration anchors**: three statements with consensus stances (2022-06-15 = max
  hawkish, 2024-09-18 = dovish, 2024-01-31 = neutral) are few-shot anchors, cached at a
  prompt-cache breakpoint so regression re-runs read them at ~0.1× cost.
- **Idempotent + Batch**: backfill runs through the Batch API (50% off); a manifest keyed
  on `(content_hash, prompt_hash)` means an unchanged prompt re-scores nothing.

**Provider strategy** (measured, not assumed): I ran the full 87-doc set through both
`claude-opus-4-8` and `deepseek-v4-pro` with identical prompts. Overall-score correlation
was r≈0.9 with >90% within ±1 — but DeepSeek's **verbatim-quote violation rate on minutes
was 42% vs Opus's 5%**, and the schema's hard requirement is verbatim quotes. Conclusion:
production scoring stays on Opus (the volume is low — <$1/year — so cost is a non-factor);
DeepSeek is retained as a cheap second-opinion signal for the eval queue. (The
high-frequency *news-summary* path elsewhere in FXLab *was* migrated to DeepSeek v4-flash,
where the cost math flips.)

### 4. Attribution (`attribution/`) — ground truth = market
For each statement with price coverage, the release time (`t0` = 14:00 America/New_York,
DST-aware) is aligned to minute-level XAU candles, and the 15min / 1h / 1d returns are
measured. Direction convention: hawkish → gold down. The backtest reports per-window
direction-hit-rate and Pearson(score, return).

**Honest limitation, stated everywhere it surfaces**: FXLab currently has only XAU (no
DXY/US2Y), and the XAU minute history starts 2025-10 — so only ~5 of 44 statements have
price coverage. Hit-rate is 50% at N=4: the pipeline works, the signal is not yet
significant. It accumulates one event per future FOMC. This is a methodology demo with the
small-N caveat printed in the API response, the UI, and here.

### 5. Serving
- **Backend**: a read-only FastAPI router (`routers/macro_router.py`, prefix `/api/macro`)
  mounted into the existing app, serving scores / red-line diff / attribution / adjudication
  queue from S3 with a 5-minute cache — same pattern as the other analytics routers.
- **Frontend**: a `MacroPulse` page in the existing React/Vite app — score timeline
  (diverging hawk-red / dove-green bars), latest red-line, attribution table, and the
  adjudication queue, bilingual (CN/EN).

---

## The evaluation harness (the actual point)

A three-tier eval, because "did the LLM score it right" is the whole risk:

1. **Tier-1 structural/calibration regression** — runs in CI on every push, fully offline
   (no API/S3/network). It validates a committed golden snapshot of all 87 production
   scores against schema/range invariants, and asserts the three calibration anchors stay
   in their expected bands. If a prompt change shifts the scoring scale, CI goes red. This
   is the repo's **first CI workflow** (`.github/workflows/macropulse-eval.yml`).
2. **Tier-2 drift test** — gated behind an env flag (costs API). Re-scores the anchors and
   asserts `|Δ overall| ≤ 1` with no sign flip vs golden. Run manually or on a schedule
   after editing a prompt.
3. **Human adjudication queue** — pulls every production score and surfaces the
   untrustworthy ones: model-flagged `needs_review`, low confidence, verbatim violations,
   and **price conflicts** (joined with the attribution result — e.g. a statement scored
   neutral that nonetheless moved gold −5.67% intraday). Adjudications flow back as
   calibration data. The first run surfaced 8 items, each genuinely worth a human look.

---

## Stack

Python · FastAPI · Claude API (structured output, prompt caching, Batch) · DeepSeek
(comparison + high-freq path) · Pydantic · AWS (S3 data lake, Lambda-style ingestion,
EC2) · React + Vite · pytest (78 hermetic tests) · GitHub Actions CI.

---

## Honest conditions

- Fed statements/minutes are public-domain publications; the scraper self-identifies and
  rate-limits. RBA/ECB are not yet wired (their robots.txt/terms need checking first).
- The attribution conclusion is **not** statistically significant at current N, and price
  reactions carry confounders (same-day data releases, liquidity windows). Every surface
  that shows it says so.
- This project doesn't manufacture "years of production AI experience." What it does is
  move the narrative from "designed an architecture" to "shipped a system with an eval
  loop, a CI regression gate, a measured provider trade-off, and stated limitations."
