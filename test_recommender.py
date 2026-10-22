"""Tests for the Inclusive Toy Finder. Run with:  python -m unittest -v"""
import itertools
import unittest

from catalog import (ATTENTION, BUDGETS, CATALOG, EXAMPLES, FLAGS, GOALS, HAND_LEVELS,
                     INTERESTS, NEEDS, NOISE_LEVELS, PLAY_SETTINGS)
from recommender import (AGE_EDGE_PENALTY, Listing, Profile, clean_ai_filters, guarantees,
                         listing_problem, parse_age_range, pick_listing, recommend, score)
from services import extract_json_object

FOCUS = {"short": 0, "medium": 1, "long": 2}
TOYS = {toy.id: toy for toy in CATALOG}


def make_profile(**changes):
    values = dict(age=4, budget=40, interests=(), goals=(), attention="medium",
                  play_setting="either", needs=())
    values.update(changes)
    return Profile(**values)


def broken_rules(toy, profile):
    """An independent restatement of every hard rule, used to audit recommend()."""
    problems = []
    if not toy.min_age <= profile.age <= toy.max_age:
        problems.append("age")
    if toy.price_low > profile.budget:
        problems.append("budget")
    if toy.has("small_parts") and profile.age < 3:
        problems.append("small parts under 3")
    if "mouths_objects" in profile.needs and (toy.has("small_parts") or toy.has("mouth_hazard")):
        problems.append("mouthing")
    if "sound_sensitive" in profile.needs and toy.noise == "loud":
        problems.append("noise")
    if "light_sensitive" in profile.needs and toy.has("flashing_lights"):
        problems.append("lights")
    if "limited_grip" in profile.needs and toy.hands == "high":
        problems.append("grip")
    if "limited_mobility" in profile.needs and toy.has("needs_mobility"):
        problems.append("mobility")
    if "low_vision" in profile.needs and toy.has("needs_vision"):
        problems.append("vision")
    if "deaf_hoh" in profile.needs and toy.has("needs_hearing"):
        problems.append("hearing")
    if FOCUS[toy.min_focus] > FOCUS[profile.attention]:
        problems.append("focus")
    if profile.play_setting == "solo" and toy.players == "2+":
        problems.append("players")
    if toy.only_if and not set(toy.only_if) & set(profile.needs):
        problems.append("only_if")
    return problems


class CatalogTests(unittest.TestCase):
    def test_ids_are_unique(self):
        self.assertEqual(len(TOYS), len(CATALOG))

    def test_every_field_is_valid(self):
        for toy in CATALOG:
            with self.subTest(toy=toy.id):
                self.assertTrue(0 <= toy.min_age <= toy.max_age <= 12)
                self.assertTrue(0 < toy.price_low <= toy.price_high)
                self.assertTrue(toy.interests and set(toy.interests) <= set(INTERESTS))
                self.assertTrue(toy.goals and set(toy.goals) <= set(GOALS))
                self.assertIn(toy.min_focus, ATTENTION)
                self.assertIn(toy.noise, NOISE_LEVELS)
                self.assertIn(toy.hands, HAND_LEVELS)
                self.assertIn(toy.players, ("any", "2+"))
                self.assertTrue(toy.flags <= FLAGS, toy.flags - FLAGS)
                self.assertTrue(set(toy.only_if) <= set(NEEDS))
                self.assertTrue(toy.query and toy.keywords and all(toy.keywords))
                self.assertTrue(toy.blurb.endswith("."))

    def test_small_parts_are_never_for_under_3s(self):
        for toy in CATALOG:
            if toy.has("small_parts"):
                self.assertGreaterEqual(toy.min_age, 3, toy.id)

    def test_toys_made_for_mouthing_have_no_mouthing_hazards(self):
        for toy in CATALOG:
            if toy.has("for_mouthers"):
                self.assertFalse(toy.has("small_parts") or toy.has("mouth_hazard"), toy.id)

    def test_every_age_has_plenty_of_options(self):
        for age in range(13):
            results = recommend(make_profile(age=age, budget=150, attention="long"))
            self.assertGreaterEqual(results.eligible, 8, f"age {age}")

    def test_examples_are_valid_and_return_full_results(self):
        for example in EXAMPLES:
            values = example["values"]
            with self.subTest(example=example["label"]):
                self.assertIn(values["budget"], BUDGETS)
                self.assertTrue(set(values["interests"]) <= set(INTERESTS))
                self.assertTrue(set(values["goals"]) <= set(GOALS))
                self.assertTrue(set(example["needs"]) <= set(NEEDS))
                profile = make_profile(age=values["age"], budget=values["budget"],
                                       interests=tuple(values["interests"]),
                                       goals=tuple(values["goals"]),
                                       attention=values["attention"],
                                       play_setting=values["setting"],
                                       needs=tuple(example["needs"]))
                self.assertEqual(len(recommend(profile).picks), 6)


class RecommendationTests(unittest.TestCase):
    def test_no_pick_ever_breaks_a_hard_rule(self):
        """Every age, budget, focus, play setting, and pair of needs."""
        need_sets = [()] + [(n,) for n in NEEDS] + list(itertools.combinations(NEEDS, 2))
        checked = 0
        for age, budget, attention, setting, needs in itertools.product(
                range(13), (15, 40, 150), ATTENTION, PLAY_SETTINGS, need_sets):
            profile = make_profile(age=age, budget=budget, attention=attention,
                                   play_setting=setting, needs=needs)
            for rec in recommend(profile).picks:
                problems = broken_rules(rec.toy, profile)
                self.assertFalse(problems, f"{rec.toy.id} for {profile}: {problems}")
                checked += 1
        self.assertGreater(checked, 50_000)

    def test_every_pick_matches_something_the_parent_picked(self):
        for interest, goal in itertools.product(INTERESTS, GOALS):
            profile = make_profile(age=6, budget=150, attention="long",
                                   interests=(interest,), goals=(goal,))
            for rec in recommend(profile).picks:
                self.assertTrue(interest in rec.toy.interests or goal in rec.toy.goals,
                                f"{rec.toy.id} for {interest}/{goal}")

    def test_every_interest_and_goal_is_represented_when_possible(self):
        for age in (1, 4, 7, 10):
            for interests in itertools.combinations(INTERESTS, 2):
                for goal in GOALS:
                    profile = make_profile(age=age, budget=60, attention="long",
                                           interests=interests, goals=(goal,))
                    picks = recommend(profile).picks
                    eligible = recommend(profile, limit=100).picks
                    for interest in interests:
                        if any(interest in r.matched_interests for r in eligible):
                            self.assertTrue(any(interest in r.matched_interests for r in picks),
                                            f"{interest} missing for {profile}")
                    if any(goal in r.matched_goals for r in eligible):
                        self.assertTrue(any(goal in r.matched_goals for r in picks))

    def test_stronger_matches_rank_first(self):
        profile = make_profile(age=5, interests=("vehicles",), goals=("fine_motor",),
                               attention="long")
        top = recommend(profile).picks[0].toy
        self.assertIn("vehicles", top.interests)
        self.assertIn("fine_motor", top.goals)

    def test_specialized_toys_only_appear_when_relevant(self):
        def ids(profile):
            return {rec.toy.id for rec in recommend(profile, limit=100).picks}
        self.assertNotIn("braille_blocks", ids(make_profile(age=4, interests=("words",))))
        self.assertIn("braille_blocks", ids(make_profile(age=4, interests=("words",),
                                                         needs=("low_vision",))))

    def test_picks_are_varied(self):
        results = recommend(make_profile(age=6, budget=150, attention="long"))
        categories = {rec.toy.category for rec in results.picks}
        self.assertGreaterEqual(len(categories), 4, categories)

    def test_variety_never_beats_relevance(self):
        """A weak match should never take a slot from a much stronger one."""
        for interest, goal in itertools.product(INTERESTS, GOALS):
            for age in (2, 5, 9):
                profile = make_profile(age=age, budget=150, attention="long",
                                       interests=(interest,), goals=(goal,))
                picks = recommend(profile).picks
                everything = recommend(profile, limit=100).picks
                if len(everything) <= len(picks):
                    continue
                left_out = max(r.score for r in everything if r not in picks)
                self.assertGreaterEqual(min(r.score for r in picks), left_out - 3,
                                        f"{interest}/{goal} age {age}")

    def test_every_pick_explains_itself(self):
        profile = make_profile(age=3, interests=("music",), needs=("sound_sensitive",))
        for rec in recommend(profile).picks:
            self.assertTrue(rec.reasons, rec.toy.id)
        self.assertIn("has no loud or electronic sounds", guarantees(profile))

    def test_reports_choices_nothing_fits(self):
        results = recommend(make_profile(age=0, interests=("science", "sensory")))
        self.assertEqual(results.unmatched_interests, ("science",))
        self.assertTrue(results.picks)

    def test_toys_aimed_at_younger_kids_rank_lower(self):
        puppets = TOYS["hand_puppets"]  # ages 2 to 9
        at_edge = score(puppets, make_profile(age=9, interests=("pretend",)))
        inside = score(puppets, make_profile(age=8, interests=("pretend",)))
        self.assertEqual(inside.score - at_edge.score, AGE_EDGE_PENALTY)

    def test_exclusions_are_counted(self):
        results = recommend(make_profile(age=2, needs=("mouths_objects",)))
        total = results.eligible + sum(results.excluded.values())
        self.assertEqual(total, results.screened)


class ListingTests(unittest.TestCase):
    def listing(self, title, price=20.0, rating=4.5, reviews=100):
        return Listing(title=title, price=price, store="Shop", link="https://example.com",
                       rating=rating, reviews=reviews)

    def test_parse_age_range(self):
        cases = {
            "Magnetic Tiles for Kids Ages 3+": (3, None),
            "Baby Rattle 0-6 Months": (0, 0.5),
            "Toddler Puzzle 18M+": (1.5, None),
            "STEM Kit for Kids Ages 8-12": (8, 12),
            "Toys for 3 4 5 6 Year Old Boys": (3, 6),
            "Gift for 5 Year Old Girls": (5, 5),
            "Robot Kit 8 Years and Up": (8, None),
            "3-5 Year Olds Learning Toy": (3, 5),
            "Wooden Blocks 100 Pieces 2-in-1": None,
            "Classic Xylophone": None,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(parse_age_range(title), expected)

    def test_rejects_listings_that_break_the_filters(self):
        tiles = TOYS["magnetic_tiles"]
        child = make_profile(age=4, budget=40)
        self.assertIsNone(listing_problem(self.listing("Magnetic Tiles 60 pcs Ages 3+"), tiles, child))
        self.assertEqual(listing_problem(self.listing("Magnetic Tiles 100 pcs", price=55),
                                         tiles, child), "over_budget")
        self.assertEqual(listing_problem(self.listing("Magnetic Tiles STEM Set Ages 8+"),
                                         tiles, child), "age_label")
        self.assertEqual(listing_problem(self.listing("Replacement Magnetic Tiles 4 pack",
                                                      price=12), tiles, child), "not_the_toy")
        self.assertEqual(listing_problem(self.listing("Kids Art Easel"), tiles, child), "off_topic")
        light_sensitive = make_profile(age=4, budget=40, needs=("light_sensitive",))
        self.assertEqual(listing_problem(self.listing("Light Up Magnetic Tiles with LED"),
                                         tiles, light_sensitive), "lights")

    def test_always_rejects_water_beads(self):
        sensory_bin = TOYS["sensory_bin"]
        listing = self.listing("Sensory Bin Kit with Water Beads")
        self.assertEqual(listing_problem(listing, sensory_bin, make_profile(age=6)), "unsafe")

    def test_sound_rules_respect_gentle_instruments(self):
        sensitive = make_profile(age=3, needs=("sound_sensitive",))
        xylophone = TOYS["xylophone"]
        train = TOYS["train_set"]  # a quiet toy type
        self.assertIsNone(listing_problem(self.listing("Wooden Musical Xylophone for Toddlers"),
                                          xylophone, sensitive))
        self.assertEqual(listing_problem(self.listing("Electronic Xylophone with Lights and Sounds"),
                                         xylophone, sensitive), "sounds")
        self.assertEqual(listing_problem(self.listing("Musical Wooden Train Set", price=35),
                                         train, sensitive), "sounds")

    def test_picks_the_best_reviewed_valid_listing(self):
        toy = TOYS["wooden_blocks"]
        listings = [
            self.listing("Wooden Blocks Set", rating=4.9, reviews=12),
            self.listing("Wooden Building Blocks 100 pcs", rating=4.7, reviews=5400),
            self.listing("Giant Wooden Blocks Deluxe", price=89, rating=5.0, reviews=9000),
        ]
        best, passed = pick_listing(listings, toy, make_profile(age=4, budget=40))
        self.assertEqual(best.title, "Wooden Building Blocks 100 pcs")
        self.assertEqual(passed, 2)


class AiIntakeTests(unittest.TestCase):
    def test_clean_ai_filters_keeps_only_valid_values(self):
        values, needs, summary = clean_ai_filters({
            "age": 4.7, "budget": 35, "interests": ["vehicles", "dinosaurs", "vehicles", 3],
            "goals": ["calming"], "attention": "short", "play_setting": "alone",
            "needs": ["sound_sensitive", "autism"], "summary": "A 4-year-old who loves trains.",
        })
        self.assertEqual(values, {"age": 4, "budget": 40, "interests": ["vehicles"],
                                  "goals": ["calming"], "attention": "short"})
        self.assertEqual(needs, ["sound_sensitive"])
        self.assertEqual(summary, "A 4-year-old who loves trains.")

    def test_clean_ai_filters_handles_junk(self):
        values, needs, summary = clean_ai_filters({"age": "four", "budget": True, "needs": "none"})
        self.assertEqual((values, needs, summary), ({}, [], ""))

    def test_extract_json_object(self):
        self.assertEqual(extract_json_object('```json\n{"age": 3}\n```'), {"age": 3})
        self.assertEqual(extract_json_object('Here you go: {"age": 3}'), {"age": 3})


if __name__ == "__main__":
    unittest.main()
