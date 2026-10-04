"""General wellness guidance (dinacharya / ritucharya / dosha-pacifying habits).

Only non-prescriptive, low-risk lifestyle advice is shown to patients. Herbs, doses and
procedures stay in the practitioner view: herbs interact with medicines (e.g. Ashwagandha
with thyroid / sedative drugs, Guggulu with anticoagulants) and need a clinician.
"""

from __future__ import annotations

RITUCHARYA = {
    "shishira": [
        "Favour warm, freshly cooked, slightly unctuous food.",
        "Oil massage (abhyanga) before a warm bath; protect from cold wind.",
    ],
    "vasanta": [
        "Lighter, warm, easily digested meals; reduce heavy, sweet, cold and fried food.",
        "Brisk exercise; avoid daytime sleep - Kapha is aggravated in spring.",
    ],
    "grishma": [
        "Cooling, light, liquid-rich food; stay hydrated; avoid excess salt, sour and spicy.",
        "Avoid midday sun and strenuous exercise in the heat.",
    ],
    "varsha": [
        "Digestion is weakest in the monsoon: warm, light, freshly cooked food; boiled water.",
        "Keep dry; avoid daytime sleep and getting chilled - Vata is aggravated.",
    ],
    "sharad": [
        "Pitta is aggravated: cooling, mildly bitter and sweet food; avoid fried, sour, spicy.",
        "Avoid strong sun; moonlight walks are traditional for this season.",
    ],
    "hemanta": [
        "Digestion is strongest: nourishing, warm meals are well tolerated.",
        "Regular oil massage and exercise; protect from cold.",
    ],
}

DOSHA_HABITS = {
    "vata": [
        "Keep a regular routine for meals and sleep.",
        "Warm, moist, grounding food; avoid cold and dry snacks.",
        "Gentle, steady exercise; avoid over-exertion and long fasts.",
    ],
    "pitta": [
        "Avoid skipping meals; favour cooling foods and drinks.",
        "Limit chilli, sour, fermented and fried food, and alcohol.",
        "Avoid overheating; make time to cool down mentally.",
    ],
    "kapha": [
        "Light, warm, freshly cooked food; reduce heavy, sweet, oily and cold food.",
        "Daily vigorous exercise; avoid daytime naps.",
        "Eat only when genuinely hungry.",
    ],
}


def patient_guidance(ritu: str, vikriti_dominant: str | None) -> dict:
    doshas = (
        vikriti_dominant.split("-") if vikriti_dominant and vikriti_dominant != "tridosha" else []
    )
    return {
        "season": RITUCHARYA.get(ritu, []),
        "balance": [tip for d in doshas for tip in DOSHA_HABITS.get(d, [])],
        "note": "General wellness guidance only. Do not start herbs or stop medicines without "
        "consulting a qualified practitioner.",
    }
