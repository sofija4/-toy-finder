"""Inclusive Toy Finder: the Streamlit app.

This file is only the interface. The rules live in recommender.py, the toy
data in catalog.py, and the calls to SerpAPI and Claude in services.py.

Run with:  streamlit run toys.py
"""
from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

import streamlit as st

import services
from catalog import (ATTENTION, BUDGETS, CATALOG, EXAMPLES, GOALS, INTERESTS, NEEDS,
                     PLAY_SETTINGS)
from recommender import (ADJUSTMENT_TIPS, EXCLUSION_LABELS, Profile, clean_ai_filters,
                         pick_listing, recommend)

st.set_page_config(page_title="Inclusive Toy Finder", page_icon="🧸", layout="centered")
log = logging.getLogger("toy_finder")

RESULTS_TO_SHOW = 6
LISTING_CACHE_SECONDS = 12 * 60 * 60  # reuse shopping results for 12 hours to save API quota


def get_secret(name: str):
    try:
        value = st.secrets.get(name)
    except Exception:  # no secrets.toml, e.g. a fresh clone
        value = None
    return value or os.environ.get(name) or None


SERPAPI_KEY = get_secret("SERPAPI_KEY")
ANTHROPIC_KEY = get_secret("ANTHROPIC_API_KEY")
CLAUDE_MODEL = get_secret("CLAUDE_MODEL") or services.DEFAULT_CLAUDE_MODEL

# ---------------------------------------------------------------------------
# Form state
# ---------------------------------------------------------------------------

DEFAULT_VALUES = {"age": 4, "budget": 40, "interests": [], "goals": [],
                  "attention": "medium", "setting": "either"}


def init_state() -> None:
    for key, value in DEFAULT_VALUES.items():
        st.session_state.setdefault(key, value)
    for need in NEEDS:
        st.session_state.setdefault(f"need_{need}", False)


def apply_values(values: dict, needs) -> None:
    for key, value in values.items():
        st.session_state[key] = value
    for need in NEEDS:
        st.session_state[f"need_{need}"] = need in needs


def profile_from_state() -> Profile:
    state = st.session_state
    return Profile(
        age=state["age"], budget=state["budget"],
        interests=tuple(state["interests"]), goals=tuple(state["goals"]),
        attention=state["attention"], play_setting=state["setting"],
        needs=tuple(need for need in NEEDS if state[f"need_{need}"]),
    )


def load_example(index: int) -> None:
    example = EXAMPLES[index]
    apply_values({**DEFAULT_VALUES, **example["values"]}, example["needs"])
    st.session_state["profile"] = profile_from_state()


# ---------------------------------------------------------------------------
# Live listings
# ---------------------------------------------------------------------------

@st.cache_resource
def _listing_cache() -> dict:
    """Shared across sessions: query -> (time fetched, listings)."""
    return {}


def fetch_listings(queries):
    """Return ({query: listings or None}, problem message or None)."""
    if not SERPAPI_KEY:
        return {}, ("Live prices are off because no SerpAPI key is set, so each card "
                    "links to a Google Shopping search instead.")
    cache, now = _listing_cache(), time.time()
    found, missing = {}, []
    for query in queries:
        entry = cache.get(query)
        if entry and now - entry[0] < LISTING_CACHE_SECONDS:
            found[query] = entry[1]
        else:
            missing.append(query)

    failed = False
    if missing:
        with st.spinner("Checking live prices..."):
            with ThreadPoolExecutor(max_workers=len(missing)) as pool:
                futures = {q: pool.submit(services.search_shopping, q, SERPAPI_KEY)
                           for q in missing}
            for query, future in futures.items():
                try:
                    listings = future.result()
                except Exception as exc:  # ServiceError or anything unexpected
                    log.warning("Shopping search failed for %r: %s", query, exc)
                    failed = True
                    found[query] = None
                    continue
                cache[query] = (now, listings)
                found[query] = listings
    problem = ("Live prices aren't available right now, so some cards link to a Google "
               "Shopping search instead.") if failed else None
    return found, problem


# ---------------------------------------------------------------------------
# Formatting helpers. Streamlit renders Markdown, so "$" and symbols need escaping.
# ---------------------------------------------------------------------------

_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|$<>~])")


def md(text: str) -> str:
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def money(amount: float) -> str:
    text = f"{amount:,.0f}" if float(amount).is_integer() else f"{amount:,.2f}"
    return "\\$" + text


def age_label(age: int) -> str:
    return "Under 1" if age == 0 else f"{age} year{'s' if age > 1 else ''}"


def age_phrase(age: int) -> str:
    return "a baby under 1" if age == 0 else f"a {age}-year-old"


def age_range(toy) -> str:
    if toy.min_age == 0:
        return f"babies up to age {toy.max_age}"
    return f"ages {toy.min_age} to {toy.max_age}"


def shopping_search_url(query: str) -> str:
    return f"https://www.google.com/search?tbm=shop&q={quote_plus(query)}"


def shorten(text: str, limit: int = 90) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Page sections
# ---------------------------------------------------------------------------

def render_intro() -> None:
    st.title("Inclusive Toy Finder", anchor=False)
    st.write("Toy ideas matched to a child's age, interests, and sensory and "
             "accessibility needs, with live prices from online stores.")
    st.caption("New here? Try an example:")
    columns = st.columns(2)
    for index, example in enumerate(EXAMPLES):
        columns[index % 2].button(example["label"], key=f"example_{index}",
                                  on_click=load_example, args=(index,))


def render_describe() -> None:
    """Optional: describe the child in plain words and let Claude fill in the form."""
    if not ANTHROPIC_KEY:
        return
    with st.form("describe"):
        st.markdown("**Or describe your child in your own words**")
        st.text_area(
            "Description", key="description", max_chars=600, label_visibility="collapsed",
            placeholder="For example: My son is 4. He loves trains, covers his ears at loud "
                        "noises, and usually plays on his own for a few minutes at a time.",
        )
        st.caption("Claude turns this into the filters below and runs the search. Check "
                   "what it picked and change anything that's off. This app doesn't save "
                   "what you type.")
        submitted = st.form_submit_button("Fill in the filters")
    if not submitted:
        return
    text = (st.session_state.get("description") or "").strip()
    if len(text) < 10:
        st.warning("Add a sentence or two about the child first.")
        return
    with st.spinner("Reading your description..."):
        try:
            raw = services.describe_to_filters(text, ANTHROPIC_KEY, CLAUDE_MODEL)
        except services.ServiceError as exc:
            log.warning("Claude intake failed: %s", exc)
            st.error("Couldn't read that description right now. Use the filters below instead.")
            return
    values, needs, summary = clean_ai_filters(raw)
    apply_values({**DEFAULT_VALUES, **values}, needs)
    st.session_state["profile"] = profile_from_state()
    st.success((md(summary) + " " if summary else "") +
               "The filters below are filled in. Adjust anything and select Find toys again.")


def render_filters() -> None:
    with st.form("filters"):
        left, right = st.columns(2)
        left.select_slider("Child's age", options=list(range(13)), key="age",
                           format_func=age_label)
        right.select_slider("Budget", options=list(BUDGETS), key="budget",
                            format_func=lambda amount: f"Up to ${amount}")
        st.multiselect("Interests", options=list(INTERESTS), key="interests",
                       format_func=INTERESTS.get, placeholder="Pick any that fit")
        st.multiselect("Goals to support", options=list(GOALS), key="goals",
                       format_func=GOALS.get, placeholder="Pick any that fit")
        left, right = st.columns(2)
        left.radio("How long do they usually stay with one activity?",
                   options=list(ATTENTION), key="attention", format_func=ATTENTION.get)
        right.radio("How do they usually play?", options=list(PLAY_SETTINGS), key="setting",
                    format_func=PLAY_SETTINGS.get)
        st.markdown("**Sensory and accessibility needs**")
        st.caption("Check any that apply. Toys that conflict with a checked need are "
                   "removed, not just ranked lower.")
        left, right = st.columns(2)
        for index, (need, label) in enumerate(NEEDS.items()):
            (left if index % 2 == 0 else right).checkbox(label, key=f"need_{need}")
        submitted = st.form_submit_button("Find toys", type="primary")
    if submitted:
        st.session_state["profile"] = profile_from_state()


def render_results(profile: Profile) -> None:
    results = recommend(profile, limit=RESULTS_TO_SHOW)
    st.header(f"Top picks for {age_phrase(profile.age)}", anchor=False)

    if not results.picks:
        st.warning("No toy types passed all of these filters.")
        render_adjustment_tip(results)
        render_exclusions(results)
        return

    count = len(results.picks)
    st.write(f"{results.eligible} of {results.screened} toy types passed every filter. "
             + ("Here's the best match." if count == 1 else f"Here are the {count} best matches."))
    if results.eligible < 3:
        render_adjustment_tip(results)
    render_exclusions(results)

    listings, problem = fetch_listings([rec.toy.query for rec in results.picks])
    if problem:
        st.info(problem)
    for rec in results.picks:
        fetched = listings.get(rec.toy.query)
        best, passed = pick_listing(fetched, rec.toy, profile)
        render_card(rec, best, passed, fetched is not None)


def render_adjustment_tip(results) -> None:
    adjustable = [(reason, n) for reason, n in results.excluded.most_common()
                  if reason in ADJUSTMENT_TIPS]
    if adjustable:
        reason, count = adjustable[0]
        st.info(ADJUSTMENT_TIPS[reason].format(n=count))


def render_exclusions(results) -> None:
    if not results.excluded:
        return
    with st.expander("Why the other toys were left out"):
        lines = [f"- {EXCLUSION_LABELS[reason]}: {count}"
                 for reason, count in results.excluded.most_common()]
        st.markdown("\n".join(lines))


def render_card(rec, listing, passed: int, fetched: bool) -> None:
    toy = rec.toy
    with st.container(border=True):
        if listing and listing.image:
            image_column, text_column = st.columns([1, 2.6], gap="medium")
            image_column.image(listing.image)
        else:
            text_column = st.container()

        with text_column:
            st.subheader(md(toy.name), anchor=False)
            st.write(md(toy.blurb))
            st.caption(f"Made for {age_range(toy)}. Usually "
                       f"{money(toy.price_low)} to {money(toy.price_high)}.")
            st.markdown("**Why it fits**\n\n" + "\n".join(f"- {md(r)}" for r in rec.reasons))
            if toy.caution:
                st.caption(f"Good to know: {md(toy.caution)}")

            search_url = shopping_search_url(toy.query)
            if listing:
                store = f" at {md(listing.store)}" if listing.store else ""
                st.markdown(f"**{money(listing.price)}**{store}")
                details = [md(shorten(listing.title))]
                if listing.rating:
                    stars = f"Rated {listing.rating:.1f} out of 5"
                    if listing.reviews:
                        stars += f" from {listing.reviews:,} reviews"
                    details.append(stars)
                details.append("The only listing that passed the price, age, and safety checks"
                               if passed == 1 else
                               f"Top-rated of {passed} listings that passed the price, age, "
                               "and safety checks")
                st.caption("  \n".join(details))
                left, right = st.columns(2)
                left.link_button("View this product", listing.link)
                right.link_button("Compare options", search_url)
            else:
                if fetched:
                    st.caption("No listing passed the price, age, and safety checks right now.")
                st.link_button("Search Google Shopping", search_url)


def render_footer() -> None:
    st.divider()
    with st.expander("How this works"):
        st.markdown(
            f"1. **Screening.** Each of the {len(CATALOG)} toy types in the catalog is tagged "
            "with an age range, typical price, noise level, flashing lights, small parts, how "
            "much hand control and mobility it takes, and whether it depends on sight or "
            "hearing. Any toy that conflicts with your answers is removed by a hard rule, so "
            "a toy with flashing lights never reaches a child who's sensitive to them.\n"
            "2. **Ranking.** The remaining toys are scored on the interests and goals they "
            "match, plus need-specific fit, like easy-grip pieces or toys you can explore by "
            "touch. Every interest and goal you pick is represented when a toy fits it, and "
            "each card lists the reasons it was chosen.\n"
            "3. **Live listings.** For the top picks, the app searches Google Shopping through "
            "SerpAPI, then rechecks each listing's title and price against your filters "
            "(budget, age labels, light-up or electronic features, and unsafe items like "
            "water beads) before showing the best-rated one.\n"
            "4. **Plain-language search (optional).** You can describe your child in a sentence "
            "and Claude fills in the filters. The rules above still decide what's shown."
        )
    st.caption("These are general play ideas, not medical or therapy advice. Always check "
               "the age label and safety warnings on the product you buy.")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

init_state()
render_intro()
render_describe()
render_filters()

current = st.session_state.get("profile")
if current:
    render_results(current)
else:
    st.caption("Choose filters and select Find toys, or try an example above.")
render_footer()
