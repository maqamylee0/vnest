"""Shared vocabulary and English helpers for the VNeST dataset scripts."""
import re

# Concrete, picturable transitive verbs, the kind VNeST trains. Violent verbs (hit, shoot) left out on purpose.
VERBS = set("""bake boil build buy carry catch chop clean climb close cook count cut deliver dig draw drink drive
eat feed fill fix fold fry grow hammer hang heat iron kick knit lift load mix mop open pack paint park peel pick
plant play pour print pull push read repair ride roll sell send serve sew shave sing slice smell sort spread sweep
throw tie trim type wash water wear weigh wipe wrap write fly milk shear brush comb plow harvest ring check examine
treat bandage measure stir grill toast squeeze sharpen polish scrub dust vacuum fish teach paint knead decorate
deliver drive hug kick""".split())

# Held out of training entirely, so the test measures verbs the model has never seen. Five of the app's verbs
# (the ones compared on the phone); the app's other verbs stay in training so the model learns them.
TEST_VERBS = {"cook", "wash", "drive", "paint", "plant"}

# Content not suitable for a therapy app. Checked on whole words of the object and answers.
UNSUITABLE = {"gun", "guns", "grave", "graves", "battlefield", "army", "war", "trench", "trenches", "soldier",
              "beer", "wine", "whiskey", "vodka", "alcohol", "liquor", "cigarette", "cigarettes", "cigar", "tobacco",
              "prank", "pranks", "drug", "drugs", "dead", "weapon", "weapons", "bullet", "bullets", "sword", "bomb",
              "kill", "blood", "tank", "thief", "thieves"}
# Phrases that contain one of those words but are fine.
SUITABLE_EXCEPTIONS = {"blood pressure", "fish tank", "in the tank"}

PEOPLE = set("""chef cook mother father doctor nurse teacher farmer driver student mechanic child baby artist carpenter
gardener painter waiter waitress baker pilot fisherman dentist plumber electrician tailor barber hairdresser cashier
singer musician soldier policeman firefighter postman mailman librarian scientist builder janitor cleaner housekeeper
butcher shopkeeper grandmother grandfather boy girl man woman kid parent athlete player golfer swimmer hunter writer
author poet secretary vet veterinarian pharmacist surgeon photographer shepherd milkman maid nanny lifeguard coach
referee judge lawyer banker clerk husband wife friend neighbor cowboy pitcher homeowner worker chemist farmer
fireman sailor captain gardener cleaner miner engineer architect dancer actor actress priest teenager brother sister
son daughter aunt uncle customer shopper tourist camper baker florist grocer jockey rancher potter weaver knitter
sculptor drummer pianist guitarist violinist typist cook mom dad grandma grandpa toddler waiter bartender""".split())

PLURALS = {"children": "child", "men": "man", "women": "woman", "people": None, "kids": "kid", "mothers": "mother",
           "fathers": "father", "pilots": "pilot", "parents": "parent", "farmers": "farmer", "teachers": "teacher",
           "students": "student", "doctors": "doctor", "nurses": "nurse", "chefs": "chef", "cooks": "cook",
           "gardeners": "gardener", "workers": "worker", "boys": "boy", "girls": "girl", "babies": "baby"}

ARTICLES = ("a ", "an ", "the ", "some ", "your ", "his ", "her ", "their ", "my ", "our ", "its ", "thier ", "this ", "that ")

def strip_det(s: str) -> str:
    s = s.strip().lower()
    changed = True
    while changed:
        changed = False
        for a in ARTICLES:
            if s.startswith(a):
                s, changed = s[len(a):], True
    return s

def third_person(v: str) -> str:  # same rules as Scenario.thirdPerson in the app
    irregular = {"have": "has", "be": "is", "go": "goes", "do": "does"}
    if v in irregular:
        return irregular[v]
    if re.search(r"(s|x|z|ch|sh|o)$", v):
        return v + "es"
    if re.search(r"[^aeiou]y$", v):
        return v[:-1] + "ies"
    return v + "s"

def load_dictionary(path="/usr/share/dict/american-english") -> set:
    words = set()
    for w in open(path, encoding="utf-8", errors="ignore"):
        w = w.strip()
        if w and w.islower() and w.isalpha():
            words.add(w)
    return words
