# Toy Finder

A Streamlit app that recommends toys based on a child's age, attention span,
goals, interests, budget, and other preferences, using live product data from
Google Shopping (via SerpAPI).

Live demo: https://toyrecommender.streamlit.app/

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Add your SerpAPI key (get one at https://serpapi.com/) to
`.streamlit/secrets.toml`:

```toml
SERPAPI_KEY = "your-key-here"
```

This file is gitignored and must never be committed. On Streamlit Community
Cloud, set `SERPAPI_KEY` in the app's **Settings → Secrets** instead.

## Run

```bash
streamlit run toys.py
```
