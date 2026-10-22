# Inclusive Toy Finder

A Streamlit app that suggests toys based on a child's age, budget, interests,
developmental goals, and sensory and accessibility needs, then finds live
listings on Google Shopping (via SerpAPI).

Live demo: https://toyrecommender.streamlit.app/

## How it works

1. **Screening.** Each of the 85 toy types in `catalog.py` is tagged with an age
   range, typical price, noise level, flashing lights, small parts, how much hand
   control and mobility it takes, and whether it depends on sight or hearing. A toy
   that conflicts with the child's profile is removed by a hard rule, so a toy with
   flashing lights never reaches a light-sensitive child.
2. **Ranking.** Remaining toys are scored on matched interests and goals plus
   need-specific fit (easy-grip pieces, touch-friendly toys). Every interest and goal
   the parent picks is represented when a toy fits it, and each result explains why
   it was chosen.
3. **Live listings.** For the top picks, the app queries Google Shopping in parallel,
   caches results, and rechecks every listing's title and price against the same
   rules (budget, age labels, light-up or electronic features, unsafe items like
   water beads) before showing the best-rated one.
4. **Plain-language intake (optional).** With an Anthropic API key, parents can
   describe their child in a sentence. Claude converts it into the form's filters,
   which stay visible and editable. The rules above still decide what's shown.

## Project structure

The whole app lives in `toys.py`, organized in four labeled parts: the toy
catalog, the rules and ranking, the outside services (SerpAPI and Claude), and
the Streamlit interface. `requirements.txt` lists its two dependencies.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Add your keys to `.streamlit/secrets.toml` (gitignored, never commit it):

```toml
SERPAPI_KEY = "your-serpapi-key"
ANTHROPIC_API_KEY = "your-anthropic-key"   # optional: enables the describe-your-child box
```

On Streamlit Community Cloud, set these in the app's **Settings → Secrets** instead.

## Run

```bash
streamlit run toys.py
```
