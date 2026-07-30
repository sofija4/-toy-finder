import base64
import os
import pathlib
import re

import requests
import streamlit as st

PLACEHOLDER_IMAGE = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(
        b"<svg xmlns='http://www.w3.org/2000/svg' width='400' height='400'>"
        b"<rect width='100%' height='100%' fill='#F1F0ED'/>"
        b"<text x='50%' y='50%' font-family='sans-serif' font-size='18' "
        b"fill='#9A9A9A' text-anchor='middle' dy='.3em'>No image</text></svg>"
    ).decode()
)

# Raw UI labels aren't useful shopping-search keywords on their own (e.g. "5-10 minutes"
# matches nothing in a product title), so translate them into terms that actually
# describe the kind of toy being searched for.
ATTENTION_SEARCH_TERMS = {
    "Under 5 minutes": "quick play",
    "5–10 minutes": "short session play",
    "10–20 minutes": "engaging play",
    "20+ minutes": "long immersive play",
}
DISABILITY_SEARCH_TERMS = {
    "Colorblindness": "high contrast",
    "Hearing accessibility": "visual light-up",
    "Mobility friendly": "easy grip adaptive",
}
PLAY_STYLE_SEARCH_TERMS = {
    "Independently": "solo play",
    "Socially with friends": "group play",
}

QUESTIONS = [
    {"label": "How old is the child?", "type": "slider", "key": "age",
     "args": {"min_value": 0, "max_value": 18, "value": 5}},
    {"label": "Attention span?", "type": "selectbox", "key": "attention",
     "options": ["Under 5 minutes", "5–10 minutes", "10–20 minutes", "20+ minutes"]},
    {"label": "Special disabilities (if any):", "type": "multiselect", "key": "disabilities",
     "options": ["Colorblindness", "Hearing accessibility", "Mobility friendly", "Other"]},
    {"label": "Goals for child:", "type": "selectbox", "key": "goal",
     "options": ["STEM", "Sensory and multisensory development", "Imaginative and creative thinking",
                 "Motor skills and physical coordination", "Tech and electrical exploration",
                 "Educational and cognitive growth"]},
    {"label": "Child's interests (pick one or more):", "type": "multiselect", "key": "interests",
     "options": ["Animals", "Vehicles", "Fantasy", "Science", "Art & Crafts"]},
    {"label": "Parent's budget (USD):", "type": "number_input", "key": "budget",
     "args": {"min_value": 0.0, "value": 50.0, "step": 1.0}},
    {"label": "Play style?", "type": "radio", "key": "play_style",
     "options": ["Independently", "Socially with friends"]},
    {"label": "Additional preferences:", "type": "multiselect", "key": "preferences",
     "options": ["Travel safe", "Compact storage", "Low mess level", "Washable",
                 "Indestructible", "No assembly required", "Culturally inclusive"]},
]


def load_local_css():
    css_path = pathlib.Path(__file__).parent / "cs" / "style.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def get_serpapi_key():
    key = st.secrets.get("SERPAPI_KEY") if hasattr(st, "secrets") else None
    return key or os.environ.get("SERPAPI_KEY")


def build_search_query(answers):
    parts = [
        f"{answers['age']}-year-old toy",
        ATTENTION_SEARCH_TERMS.get(answers["attention"]),
        answers["goal"],
        ", ".join(answers["interests"]) if answers["interests"] else None,
        ", ".join(DISABILITY_SEARCH_TERMS[d] for d in answers["disabilities"] if d in DISABILITY_SEARCH_TERMS) or None,
        PLAY_STYLE_SEARCH_TERMS.get(answers["play_style"]),
        ", ".join(answers["preferences"]) if answers["preferences"] else None,
        f"under ${int(answers['budget'])}",
    ]
    return " ".join(p for p in parts if p).strip()


def fetch_shopping_results(query, api_key):
    params = {"engine": "google", "q": query, "tbm": "shop", "api_key": api_key}
    response = requests.get("https://serpapi.com/search", params=params, timeout=15)
    response.raise_for_status()
    return response.json().get("shopping_results", [])


def within_budget(item, budget):
    price = item.get("extracted_price")
    if price is None:
        return True  # unknown price is shown, not assumed over budget
    return price <= budget


# A toy's title is the only free-text field SerpAPI reliably fills in (snippet/tag/
# extensions are mostly promo noise like "25% OFF"), so every match reason below is
# a real substring/regex check against the title — never a guess about the product.
AGE_RANGE_PREFIXED_RE = re.compile(r"ages?\s*(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})", re.I)
AGE_RANGE_UNIT_RE = re.compile(r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*(?:years?|yrs?)\b", re.I)
AGE_PLUS_RE = re.compile(r"ages?\s*(\d{1,2})\s*\+", re.I)


def _age_fits_title(title, age):
    for pattern in (AGE_RANGE_PREFIXED_RE, AGE_RANGE_UNIT_RE):
        match = pattern.search(title)
        if match:
            lo, hi = int(match.group(1)), int(match.group(2))
            return lo <= age <= hi
    match = AGE_PLUS_RE.search(title)
    if match:
        return age >= int(match.group(1))
    return False  # no age info in the title at all — can't claim a fit either way


def match_reasons(item, answers):
    """Every reason here is a verified fact about this specific item, grouped into
    the 3-color tag palette: coral = matches what the child likes/needs to learn,
    teal = practical fit (budget/age/accessibility), yellow = stated preferences.
    """
    title = item.get("title", "").lower()
    reasons = []

    if item.get("extracted_price") is not None:
        reasons.append({"label": "In budget", "group": "teal"})

    if _age_fits_title(title, answers["age"]):
        reasons.append({"label": "Age-appropriate", "group": "teal"})

    if any(DISABILITY_SEARCH_TERMS[d].lower() in title for d in answers["disabilities"] if d in DISABILITY_SEARCH_TERMS):
        reasons.append({"label": "Accessibility-aware", "group": "teal"})

    if answers["goal"] and answers["goal"].lower() in title:
        reasons.append({"label": f"{answers['goal']} goal", "group": "coral"})

    for interest in answers["interests"]:
        if interest.lower() in title:
            reasons.append({"label": f'Matches "{interest}"', "group": "coral"})

    attention_term = ATTENTION_SEARCH_TERMS.get(answers["attention"])
    if attention_term and attention_term.lower() in title:
        reasons.append({"label": "Attention-span fit", "group": "yellow"})

    play_style_term = PLAY_STYLE_SEARCH_TERMS.get(answers["play_style"])
    if play_style_term and play_style_term.lower() in title:
        reasons.append({"label": "Play-style fit", "group": "yellow"})

    for preference in answers["preferences"]:
        if preference.lower() in title:
            reasons.append({"label": preference, "group": "yellow"})

    return reasons


def rank_results(results, answers):
    in_budget = [item for item in results if within_budget(item, answers["budget"])]
    scored = [(item, match_reasons(item, answers)) for item in in_budget]
    scored.sort(
        key=lambda pair: (
            -len(pair[1]),
            pair[0].get("extracted_price") if pair[0].get("extracted_price") is not None else float("inf"),
        )
    )
    return scored


def render_toy_card(column, toy, reasons):
    column.markdown("<div class='toy-card'>", unsafe_allow_html=True)
    column.image(toy.get("thumbnail") or PLACEHOLDER_IMAGE, use_container_width=True)
    title = toy.get("title", "Untitled toy")
    column.markdown(f"<p class='toy-card__title'>{title}</p>", unsafe_allow_html=True)
    price_text = toy.get("price") or "Price unavailable"
    column.markdown(f"<p class='toy-card__price'>{price_text}</p>", unsafe_allow_html=True)
    if reasons:
        tags_html = "".join(f"<span class='tag tag--{r['group']}'>{r['label']}</span>" for r in reasons)
        column.markdown(f"<div class='toy-card__tags'>{tags_html}</div>", unsafe_allow_html=True)
    link = toy.get("product_link")
    if link:
        column.markdown(
            f"<div class='toy-card__link'><a href='{link}' target='_blank' rel='noopener'>View toy</a></div>",
            unsafe_allow_html=True,
        )
    column.markdown("</div>", unsafe_allow_html=True)


def render_results(results, answers):
    ranked = rank_results(results, answers)
    if not ranked:
        st.info("No toys matched your filters. Try raising your budget or loosening your interests.")
        return

    st.markdown("### Your toy matches")
    grid = st.columns(4)
    for i, (toy, reasons) in enumerate(ranked):
        render_toy_card(grid[i % 4], toy, reasons)


def main():
    st.set_page_config(page_title="Toy Finder", layout="wide")
    load_local_css()

    st.markdown(
        "<div class='hero'>"
        "<h1>Toy Finder</h1>"
        "<p class='hero__subtitle'>Answer a few questions and we'll match your child with toys they'll love.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    api_key = get_serpapi_key()
    if not api_key:
        st.error(
            "No SerpAPI key configured. Add SERPAPI_KEY to .streamlit/secrets.toml "
            "(local) or your deployment's secrets/environment variables."
        )
        st.stop()

    with st.form("preferences_form"):
        answers = {}
        cols = st.columns(2)
        for idx, q in enumerate(QUESTIONS):
            col = cols[idx % 2]
            if q["type"] == "slider":
                answers[q["key"]] = col.slider(q["label"], **q["args"])
            elif q["type"] == "selectbox":
                answers[q["key"]] = col.selectbox(q["label"], q["options"], key=q["key"])
            elif q["type"] == "multiselect":
                answers[q["key"]] = col.multiselect(q["label"], q["options"], key=q["key"])
            elif q["type"] == "number_input":
                answers[q["key"]] = col.number_input(q["label"], **q["args"])
            elif q["type"] == "radio":
                answers[q["key"]] = col.radio(q["label"], q["options"], key=q["key"])
        submitted = st.form_submit_button("Find my toys")

    if submitted:
        query = build_search_query(answers)
        with st.spinner("Finding great matches..."):
            try:
                results = fetch_shopping_results(query, api_key)
            except requests.RequestException:
                st.error("Couldn't reach the toy search service. Please try again in a moment.")
                return
        render_results(results, answers)

    st.markdown("---")
    st.markdown("<p class='app-footer'>© 2026 Toy Finder</p>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
