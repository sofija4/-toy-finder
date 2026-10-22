"""Screening and ranking logic for the Inclusive Toy Finder.

Plain Python with no Streamlit or network code, so every rule can be unit tested.

1. screen()        Hard rules. A toy that conflicts with the child's age, budget,
                   or any checked need is removed, never just ranked lower.
2. score()         Ranks what's left by matched interests, goals, and
                   need-specific fit, writing a plain-language reason for each.
3. recommend()     Runs both over the catalog and keeps the picks varied.
4. pick_listing()  Rechecks live shopping listings against the same rules
                   (price, age labels, light-up or electronic features).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from catalog import (ATTENTION, BUDGETS, CATALOG, FOCUS_ORDER, GOAL_PHRASES, GOALS,
                     INTEREST_PHRASES, INTERESTS, NEEDS, PLAY_SETTINGS, ToyType)


@dataclass(frozen=True)
class Profile:
    """What the parent told us about the child."""
    age: int                      # whole years; 0 means under 1
    budget: int                   # most they want to spend, in USD
    interests: tuple = ()
    goals: tuple = ()
    attention: str = "medium"     # key of ATTENTION
    play_setting: str = "either"  # key of PLAY_SETTINGS
    needs: tuple = ()             # keys of NEEDS

    def has(self, need: str) -> bool:
        return need in self.needs


@dataclass(frozen=True)
class Recommendation:
    toy: ToyType
    score: float
    reasons: tuple
    matched_interests: tuple
    matched_goals: tuple


@dataclass(frozen=True)
class Results:
    picks: tuple
    eligible: int     # toy types that passed every rule
    screened: int     # toy types checked
    excluded: Counter  # reason -> how many toy types it removed
    unmatched_interests: tuple = ()  # picked interests that no eligible toy fits
    unmatched_goals: tuple = ()


EXCLUSION_LABELS = {
    "age": "Not made for this age",
    "only_if": "Made for needs you didn't check",
    "small_parts": "Small parts, not safe under 3",
    "mouthing": "Small parts or materials that aren't safe to mouth",
    "lights": "Flashing lights",
    "noise": "Loud or electronic sounds",
    "mobility": "Needs standing, walking, or climbing",
    "grip": "Needs precise finger control",
    "vision": "Depends on seeing small details",
    "hearing": "Depends on hearing",
    "budget": "Usually costs more than your budget",
    "focus": "Needs longer focus than your child usually has",
    "players": "Needs a second player",
    "no_match": "Doesn't match any interest or goal you picked",
}

# Reasons a parent can do something about, with what to try. {n} is a count.
ADJUSTMENT_TIPS = {
    "no_match": "{n} more toy types fit the other filters but don't match the interests or "
                "goals you picked. Picking more of either will show more ideas.",
    "budget": "{n} toy types were left out because they usually cost more than your budget. "
              "Raising it will show more ideas.",
    "focus": "{n} toy types were left out because they need longer focus than you selected.",
    "players": "{n} toy types were left out because they need a second player. Choosing "
               "\"Either\" for how they play will include them.",
}


# ---------------------------------------------------------------------------
# 1. Hard rules
# ---------------------------------------------------------------------------

def screen(toy: ToyType, profile: Profile) -> Optional[str]:
    """Return the reason a toy is ruled out for this child, or None if it passes."""
    if not toy.min_age <= profile.age <= toy.max_age:
        return "age"
    if toy.only_if and not any(profile.has(need) for need in toy.only_if):
        return "only_if"
    if toy.has("small_parts") and profile.age < 3:
        return "small_parts"
    if profile.has("mouths_objects") and (toy.has("small_parts") or toy.has("mouth_hazard")):
        return "mouthing"
    if profile.has("light_sensitive") and toy.has("flashing_lights"):
        return "lights"
    if profile.has("sound_sensitive") and toy.noise == "loud":
        return "noise"
    if profile.has("limited_mobility") and toy.has("needs_mobility"):
        return "mobility"
    if profile.has("limited_grip") and toy.hands == "high":
        return "grip"
    if profile.has("low_vision") and toy.has("needs_vision"):
        return "vision"
    if profile.has("deaf_hoh") and toy.has("needs_hearing"):
        return "hearing"
    if toy.price_low > profile.budget:
        return "budget"
    if FOCUS_ORDER[toy.min_focus] > FOCUS_ORDER[profile.attention]:
        return "focus"
    if profile.play_setting == "solo" and toy.players == "2+":
        return "players"
    return None


# ---------------------------------------------------------------------------
# 2. Ranking
# ---------------------------------------------------------------------------

INTEREST_POINTS = 4.0  # what the child enjoys counts a bit more than what we hope it builds
GOAL_POINTS = 3.0
BOTH_BONUS = 2.0        # matches an interest *and* a goal
MAX_INTERESTS_COUNTED = 2
MAX_GOALS_COUNTED = 3
MAX_REASONS = 6
AGE_EDGE_PENALTY = 2.0  # the child is the oldest age a wide-range toy is made for


def join_words(items) -> str:
    items = list(items)
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def score(toy: ToyType, profile: Profile) -> Recommendation:
    interests = tuple(i for i in profile.interests if i in toy.interests)
    goals = tuple(g for g in profile.goals if g in toy.goals)

    points = INTEREST_POINTS * min(len(interests), MAX_INTERESTS_COUNTED)
    points += GOAL_POINTS * min(len(goals), MAX_GOALS_COUNTED)
    if interests and goals:
        points += BOTH_BONUS
    if not profile.interests and not profile.goals:
        points += 0.5 * len(toy.goals)  # nothing picked yet: favor versatile toys
    if profile.age == toy.max_age and toy.max_age - toy.min_age >= 4:
        points -= AGE_EDGE_PENALTY  # mostly aimed at younger kids, so it may feel young

    reasons = []
    if interests:
        reasons.append("Fits their interest in " + join_words(INTEREST_PHRASES[i] for i in interests))
    if goals:
        reasons.append("Supports " + join_words(GOAL_PHRASES[g] for g in goals))
    elif not profile.goals:
        reasons.append("Builds " + join_words(GOAL_PHRASES[g] for g in toy.goals[:2]))

    # Only details that differ from toy to toy go on the card. Rules that every
    # pick meets are stated once, above the results (see guarantees()).
    if profile.has("sound_sensitive"):
        if toy.noise == "quiet":
            points += 0.5
        else:
            reasons.append("Only makes gentle sounds your child creates")
    if profile.has("sensory_seeking") and toy.has("sensory_rich"):
        reasons.append("Lots of sensory input from texture, pressure, or movement")
        points += 3
    if profile.has("mouths_objects") and toy.has("for_mouthers"):
        reasons.append("Made to be mouthed safely")
        points += 3
    if profile.has("limited_grip") and toy.hands == "low":
        reasons.append("Large, easy-to-grip pieces")
        points += 2
    if profile.has("low_vision") and toy.has("touch_friendly"):
        reasons.append("Easy to explore by touch")
        points += 2

    if toy.min_focus == profile.attention:
        points += 1
        if profile.attention != "short":
            reasons.append("Holds interest for 5 to 15 minutes" if profile.attention == "medium"
                           else "Rewards longer focus")

    if profile.play_setting == "together" and toy.players == "2+":
        reasons.append("Made for playing together")
        points += 2

    return Recommendation(toy=toy, score=points, reasons=tuple(reasons[:MAX_REASONS]),
                          matched_interests=interests, matched_goals=goals)


SAME_CATEGORY_PENALTY = 1.0  # small nudge toward variety; never outweighs a real match


def guarantees(profile: Profile) -> list:
    """Plain-language promises that every pick for this profile keeps."""
    promises = []
    if profile.has("mouths_objects"):
        promises.append("has no small parts or materials that aren't safe to mouth")
    elif profile.age < 3:
        promises.append("has no small parts")
    if profile.has("sound_sensitive"):
        promises.append("has no loud or electronic sounds")
    if profile.has("light_sensitive"):
        promises.append("has no flashing lights")
    if profile.has("limited_mobility"):
        promises.append("can be played seated")
    if profile.has("limited_grip"):
        promises.append("needs no fine pinching")
    if profile.has("low_vision"):
        promises.append("doesn't depend on sight")
    if profile.has("deaf_hoh"):
        promises.append("doesn't depend on sound")
    if profile.attention == "short":
        promises.append("works in short bursts of play")
    return promises


def _select(ranked: list, profile: Profile, limit: int) -> list:
    """Choose the final picks from the ranked list.

    1. Every interest and goal the parent picked gets at least one toy, if any fits.
    2. The rest are filled one at a time with the best remaining toy, minus a small
       penalty for each pick already in the same category, so results stay varied
       without letting a weak match beat a strong one.
    """
    picked, chosen, counts = [], set(), Counter()

    def take(rec):
        picked.append(rec)
        chosen.add(id(rec))
        counts[rec.toy.category] += 1

    wanted = [("interest", i) for i in profile.interests] + [("goal", g) for g in profile.goals]
    for kind, key in wanted:
        if len(picked) == limit:
            break
        field = "matched_interests" if kind == "interest" else "matched_goals"
        if any(key in getattr(rec, field) for rec in picked):
            continue
        match = next((rec for rec in ranked
                      if id(rec) not in chosen and key in getattr(rec, field)), None)
        if match:
            take(match)

    rank = {id(rec): i for i, rec in enumerate(ranked)}
    remaining = [rec for rec in ranked if id(rec) not in chosen]
    while remaining and len(picked) < limit:
        best = max(remaining, key=lambda rec: (
            rec.score - SAME_CATEGORY_PENALTY * counts[rec.toy.category], -rank[id(rec)]))
        take(best)
        remaining.remove(best)
    return sorted(picked, key=lambda rec: rank[id(rec)])


def recommend(profile: Profile, catalog=CATALOG, limit: int = 6) -> Results:
    excluded = Counter()
    eligible = []
    picked_anything = bool(profile.interests or profile.goals)
    for toy in catalog:
        reason = screen(toy, profile)
        if reason:
            excluded[reason] += 1
            continue
        rec = score(toy, profile)
        if picked_anything and not (rec.matched_interests or rec.matched_goals):
            excluded["no_match"] += 1
            continue
        eligible.append(rec)
    eligible.sort(key=lambda rec: (-rec.score, rec.toy.price_low, rec.toy.name))
    picks = _select(eligible, profile, limit)
    unmatched_interests = tuple(i for i in profile.interests
                                if not any(i in rec.matched_interests for rec in eligible))
    unmatched_goals = tuple(g for g in profile.goals
                            if not any(g in rec.matched_goals for rec in eligible))
    return Results(picks=tuple(picks), eligible=len(eligible), screened=len(catalog),
                   excluded=excluded, unmatched_interests=unmatched_interests,
                   unmatched_goals=unmatched_goals)


# ---------------------------------------------------------------------------
# 3. Checking live listings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Listing:
    title: str
    price: Optional[float]
    store: str
    link: str
    image: str = ""
    rating: Optional[float] = None
    reviews: Optional[int] = None


def _words(*terms: str):
    return re.compile(r"\b(?:" + "|".join(terms) + r")\b", re.IGNORECASE)


ALWAYS_UNSAFE = _words(r"water ?beads?", r"gel beads?", r"orbeez", r"magnet(?:ic)? balls?",
                       r"buckyballs?", r"neodymium")
NOT_THE_TOY = _words(r"replacement", r"refills?", r"spare parts?", r"parts only",
                     r"accessor(?:y|ies)", r"carrying case", r"storage (?:bag|box|bin|case)",
                     r"for adults?", r"adult (?:size|sized|costume)", r"wholesale", r"bulk",
                     r"party favors?", r"e-?book", r"dvd", r"decals?")
LIGHTS = _words(r"light[- ]?up", r"led", r"lights", r"night ?light", r"flashing", r"strobe",
                r"disco", r"glowing")
ELECTRONIC_SOUND = _words(r"electronic", r"talking", r"singing", r"sound effects?",
                          r"lights? (?:and|&) sounds?", r"with sounds?", r"with music",
                          r"plays? (?:music|songs|melodies)", r"beeps?", r"siren",
                          r"speakers?", r"(?:animal|realistic) sounds", r"battery[- ]operated")
MUSIC = _words(r"music", r"musical", r"songs?")
SMALL_HAZARDS = _words(r"marbles?", r"magnets?", r"magnetic")
BALLOONS = _words(r"balloons?")

_UNIT_YEARS = r"(?:years?|yrs?|y/?o|year[- ]olds?)"
_AGE_PATTERNS = (
    (re.compile(r"\b(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*(?:months?|mos?)\b", re.I), "months_range"),
    (re.compile(r"\b(\d{1,2})\s*(?:months?|mos?|m)\s*(?:\+|and up|& up|plus|or older)", re.I),
     "months_min"),
    (re.compile(r"\bages?\s*(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\b", re.I), "range"),
    (re.compile(r"\b(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*(?:\+\s*)?" + _UNIT_YEARS + r"\b", re.I),
     "range"),
    (re.compile(r"\bages?\s*(\d{1,2})\s*(?:\+|and up|& up|plus|or older)", re.I), "min"),
    (re.compile(r"\b(\d{1,2})\s*(?:\+|and up|& up|plus)\s*(?:years?|yrs?)\b", re.I), "min"),
    (re.compile(r"\b(\d{1,2})\s*(?:years?|yrs?)\s*(?:\+|and up|& up|plus|or older)", re.I), "min"),
    (re.compile(r"\b((?:\d{1,2}[\s,]+){1,10}\d{1,2})\s*(?:\+\s*)?(?:years?[- ]olds?|year|yrs?)\b",
                re.I), "list"),
    (re.compile(r"\b(\d{1,2})\s*years?[- ]olds?\b", re.I), "single"),
)


def parse_age_range(title: str):
    """Read an age label like 'Ages 3+', '12-18 Months', or 'for 3 4 5 Year Olds'.

    Returns (youngest, oldest) in years, where oldest may be None, or None if the
    title has no age label.
    """
    for pattern, kind in _AGE_PATTERNS:
        match = pattern.search(title)
        if not match:
            continue
        if kind == "months_range":
            low, high = int(match.group(1)), int(match.group(2))
            if low <= high <= 60:
                return low / 12, high / 12
        elif kind == "months_min":
            months = int(match.group(1))
            if months <= 60:
                return months / 12, None
        elif kind == "range":
            low, high = int(match.group(1)), int(match.group(2))
            if low <= high <= 18:
                return float(low), float(high)
        elif kind == "min":
            low = int(match.group(1))
            if low <= 18:
                return float(low), None
        elif kind == "list":
            ages = [int(n) for n in re.findall(r"\d{1,2}", match.group(1))]
            if all(a <= 18 for a in ages):
                return float(min(ages)), float(max(ages))
        elif kind == "single":
            age = int(match.group(1))
            if age <= 18:
                return float(age), float(age)
    return None


def _age_conflict(title: str, age: int) -> bool:
    parsed = parse_age_range(title)
    if not parsed:
        return False
    low, high = parsed
    if low > age + 0.5:          # labeled for older kids: possible safety issue
        return True
    if high is not None and high < age - 1:  # labeled for much younger kids
        return True
    return False


_keyword_patterns = {}


def _keyword_pattern(toy: ToyType):
    pattern = _keyword_patterns.get(toy.id)
    if pattern is None:
        options = "|".join(re.escape(k).replace(r"\ ", r"[\s-]?") for k in toy.keywords)
        pattern = re.compile(r"\b(?:" + options + r")(?:s|es)?\b", re.IGNORECASE)
        _keyword_patterns[toy.id] = pattern
    return pattern


def listing_problem(listing: Listing, toy: ToyType, profile: Profile) -> Optional[str]:
    """Return why a listing shouldn't be shown for this child, or None if it's fine."""
    title = listing.title
    if ALWAYS_UNSAFE.search(title):
        return "unsafe"
    if NOT_THE_TOY.search(title):
        return "not_the_toy"
    if not _keyword_pattern(toy).search(title):
        return "off_topic"
    if listing.price is None:
        return "no_price"
    if listing.price > profile.budget:
        return "over_budget"
    if listing.price < 0.3 * toy.price_low:
        return "likely_accessory"
    if _age_conflict(title, profile.age):
        return "age_label"
    if profile.age < 8 and BALLOONS.search(title):
        return "unsafe"
    if (profile.age < 3 or profile.has("mouths_objects")) and SMALL_HAZARDS.search(title):
        return "small_parts"
    if profile.has("light_sensitive") and LIGHTS.search(title):
        return "lights"
    if profile.has("sound_sensitive"):
        if ELECTRONIC_SOUND.search(title):
            return "sounds"
        if toy.noise == "quiet" and MUSIC.search(title):
            return "sounds"
    return None


def _listing_quality(listing: Listing):
    rating = listing.rating or 0.0
    reviews = listing.reviews or 0
    return (round(rating * math.log10(reviews + 10), 3), bool(listing.image))


def pick_listing(listings, toy: ToyType, profile: Profile):
    """Return (best listing or None, how many listings passed every check)."""
    passed = [l for l in listings or () if listing_problem(l, toy, profile) is None]
    if not passed:
        return None, 0
    return max(passed, key=_listing_quality), len(passed)


# ---------------------------------------------------------------------------
# 4. Cleaning filters suggested by the AI intake
# ---------------------------------------------------------------------------

def clean_ai_filters(raw: dict):
    """Keep only valid values from Claude's JSON. Returns (values, needs, summary)."""
    values = {}
    age = raw.get("age")
    if isinstance(age, (int, float)) and not isinstance(age, bool):
        values["age"] = int(min(max(math.floor(age), 0), 12))
    budget = raw.get("budget")
    if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0:
        values["budget"] = next((b for b in BUDGETS if b >= budget), BUDGETS[-1])
    for key, allowed in (("interests", INTERESTS), ("goals", GOALS)):
        items = raw.get(key)
        if isinstance(items, list):
            values[key] = [i for i in dict.fromkeys(x for x in items if isinstance(x, str))
                           if i in allowed]
    if raw.get("attention") in ATTENTION:
        values["attention"] = raw["attention"]
    if raw.get("play_setting") in PLAY_SETTINGS:
        values["setting"] = raw["play_setting"]
    raw_needs = raw.get("needs") if isinstance(raw.get("needs"), list) else []
    needs = [n for n in dict.fromkeys(x for x in raw_needs if isinstance(x, str)) if n in NEEDS]
    summary = raw.get("summary") if isinstance(raw.get("summary"), str) else ""
    return values, needs, summary.strip()[:300]
