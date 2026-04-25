# S5 — Sentiment Engine

## Purpose
Score all raw text scraped by S2, compute per-ticker daily sentiment and
attention metrics, and write residualized scores for S3.

## Entry Point
```python
from s5_sentiment.main import run
run(run_id="<uuid-from-jobs-table>")
```

## File Structure
```
s5_sentiment/
  __init__.py          — package marker
  main.py              — orchestration entry point (run())
  preprocessor.py      — text cleaning, URL stripping, ticker-mention detection
  scorer.py            — FinBERT inference; model fallback chain (finbert → none)
  aggregator.py        — per-ticker: raw_sentiment, abn_attention
  residualizer.py      — OLS residualization of raw_sentiment
  utils.py             — utc_now(), utc_today(), canonical file path helpers
  requirements.txt     — module-level package requirements

tests/unit/s5/
  conftest.py          — shared fixtures
  test_preprocessor.py
  test_scorer.py
  test_aggregator.py
  test_residualizer.py
  test_main.py
```

## Config Keys Consumed
From `config/sentiment_params.yaml`:
- `model` — primary model (`finbert`)
- `finbert_model_id` — HF model ID
- `attention_lookback_days` — rolling window for abn_attention z-score (30)

From `config/system.yaml`:
- `data_dir_hdd` — root for raw JSON files written by S2
- `gpu_device` — e.g. `cuda:0` or `cpu`
- `db_url` — PostgreSQL connection string

From `config/universe.yaml`:
- `tickers` — universe; every ticker gets a row in sentiment_scores

## Failure Modes
| Condition | Behaviour |
|---|---|
| Raw file missing | Degrade to empty document list; log WARNING |
| FinBERT unavailable | model_used='none' for all items; emit SENTIMENT_ERROR WARNING |
| Empty universe | Raise SentimentError; emit SENTIMENT_ERROR WARNING |
| DB write failure | Raise SentimentError; S1 handles retry |

## Residualization Model
\[
\hat{y} = \beta_0 + \beta_1 \cdot \overline{s}_{t-5:t-1} + \beta_2 \cdot \overline{a}_{t-5:t-1}
\]
```
sentiment_res = raw_sentiment_today - ŷ
```
Fallback when history < 2 days: `sentiment_res = raw_sentiment`.
