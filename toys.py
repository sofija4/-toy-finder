import streamlit as st
import pathlib 
from pathlib import Path
import requests

import urllib.parse


def extract_real_url(google_link):
    """
    Extract the actual product URL from a Google redirect link.
    If it’s already a direct link, it returns it as-is.
    """
    parsed = urllib.parse.urlparse(google_link)
    query = urllib.parse.parse_qs(parsed.query)
    return query.get("q", [google_link])[0]  # get 'q' parameter if exists, else original link






def load_local_css():
    # Build absolute path to cs/style.css
    css_path = pathlib.Path(__file__).parent / "cs" / "style.css"
    if css_path.exists():
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    else:
        st.warning("style.css not found in /cs folder.")
        st.stop()

# Load the CSS before anything else
load_local_css()

# --- Your Streamlit content below ---
# Page config
st.set_page_config(page_title="Family Fun Hub", page_icon="🎠", layout="wide")


st.title("🎉 Discover the Perfect Toy!")





# 🔑 SerpAPI key
serpapi_key = "ad2a069e7be9fa060929eab75e34d86161876dc30a71e26f50e3558f13a2d626"


# --- Questions ---
questions = [
    {"label": "1. How old is the child?", "type": "slider", "key": "age", "args": {"min_value": 0, "max_value": 18, "value": 5}},
    {"label": "2. Attention span?", "type": "selectbox", "key": "attention", "options": ["Under 5 minutes", "5–10 minutes", "10–20 minutes", "20+ minutes"]},
    {"label": "3. Special disabilities (if any):", "type": "multiselect", "key": "disabilities", "options": ["Colorblindness", "Hearing accessibility", "Mobility friendly", "Other"]},
    {"label": "4. Goals for child:", "type": "selectbox", "key": "goal", "options": ["STEM", "Sensory and multisensory development", "Imaginative and creative thinking", "Motor skills and physical coordination", "Tech and electrical exploration", "Educational and cognitive growth"]},
    {"label": "5. Child's interests (pick one or more):", "type": "multiselect", "key": "interests", "options": ["Animals", "Vehicles", "Fantasy", "Science", "Art & Crafts"]},
    {"label": "6. Parent's budget (USD):", "type": "number_input", "key": "budget", "args": {"min_value": 0.0, "value": 50.0, "step": 1.0}},
    {"label": "7. Play style?", "type": "radio", "key": "play_style", "options": ["Independently", "Socially with friends"]},
    {"label": "8. Additional preferences:", "type": "multiselect", "key": "preferences", "options": ["Travel safe", "Compact storage", "Low mess level", "Washable", "Indestructible", "No assembly required", "Culturally inclusive"]}
]

# --- Collect Answers ---
answers = {}
cols = st.columns(2)
for idx, q in enumerate(questions):
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

# --- Search Button ---










if st.button("🚀 Find My Toys!"):
    parts = [
        f"{answers['age']}-year-old toy",
        answers['attention'],
        ", ".join(answers['disabilities']) if answers['disabilities'] else None,
        answers['goal'],
        ", ".join(answers['interests']) if answers['interests'] else None,
        f"under ${int(answers['budget'])}",
        answers['play_style'],
        ", ".join(answers['preferences']) if answers['preferences'] else None
    ]
    query = " ".join([p for p in parts if p]).strip()

    params = {"engine": "google", "q": query, "tbm": "shop", "api_key": serpapi_key}
    data = requests.get("https://serpapi.com/search", params=params).json()
    results = data.get("shopping_results", [])[:12]







    # Filter by budget
    filtered = []
    for item in results:
        raw = item.get("price", "").replace("$", "").replace(",", "")
        try:
            price = float(raw)
        except:
            price = None
        if price is None or price <= answers['budget']:
            filtered.append(item)

    if not filtered:
        st.warning("No toys found that match your criteria. Try adjusting your filters.")
    else:
        st.markdown("### 🎁 Your Toy Matches:")
        grid = st.columns(4)
      
        for i, toy in enumerate(filtered):
            col = grid[i % 4]  # distribute toys across the 4 columns
            col.markdown("<div class='toy-card'>", unsafe_allow_html=True)

            # Show thumbnail if available
            if toy.get("thumbnail"):
                col.image(toy["thumbnail"], use_container_width=True)

            # Get title and link
            title = toy.get("title", "Untitled Toy")
            link = toy.get("link")

            if link:
                real_link = extract_real_url(link)
                # Clickable title that opens in a new tab
                col.markdown(f"<h3><a href='{real_link}' target='_blank'>{title}</a></h3>", unsafe_allow_html=True)
            else:
                col.markdown(f"### {title}", unsafe_allow_html=True)

            # Show price if available
            if toy.get("price"):
                col.markdown(f"**{toy['price']}**")

            col.markdown("</div>", unsafe_allow_html=True)



           

# --- Footer ---
st.markdown("---")
st.markdown(
    "<p style='text-align:center; color:gray;'>© 2025 Family Fun Toy Finder</p>",
    unsafe_allow_html=True
)

