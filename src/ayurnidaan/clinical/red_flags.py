"""Emergency red flags - checked before, and independently of, any Ayurvedic reasoning.

Every intake starts with this checklist. If any item is positive the app stops the
differential and tells the person to seek emergency care (India: 112 / 108). Rules are
adapted from standard telephone-triage danger signs (stroke FAST, acute coronary
syndrome, sepsis/meningitis, obstetric, paediatric and mental-health emergencies).

These are deliberately simple and over-inclusive: a false alarm costs a hospital visit,
a missed flag can cost a life. Nothing downstream can override a red flag.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RedFlag:
    code: str
    question: str
    advice: str
    level: str = "emergency"  # emergency | urgent


CHECKLIST: tuple[RedFlag, ...] = (
    RedFlag(
        "chest_pain",
        "Chest pain, pressure or tightness - especially spreading to the arm, jaw "
        "or back, or with sweating or breathlessness?",
        "Possible heart attack. Call 112/108 now. Chew an aspirin only if a doctor has advised it.",
    ),
    RedFlag(
        "stroke",
        "Sudden face drooping, weakness of one arm or leg, or slurred / difficult speech?",
        "Possible stroke - every minute matters. Call 112/108 now and note the time it started.",
    ),
    RedFlag(
        "breathing",
        "Severe difficulty breathing, unable to speak in full sentences, or blue lips?",
        "Breathing emergency. Call 112/108 now.",
    ),
    RedFlag(
        "unconscious",
        "Fainted, had a seizure, or is very drowsy / confused and hard to wake?",
        "Seek emergency care now.",
    ),
    RedFlag(
        "bleeding",
        "Vomiting blood, coughing blood, black tarry stools or heavy bleeding that will not stop?",
        "Possible internal bleeding. Go to an emergency department now.",
    ),
    RedFlag(
        "meningitis",
        "High fever with stiff neck, a rash that does not fade when pressed, or severe confusion?",
        "Possible meningitis or sepsis. Go to an emergency department now.",
    ),
    RedFlag(
        "headache",
        "Sudden, severe 'worst ever' headache, or sudden loss of vision?",
        "Seek emergency care now.",
    ),
    RedFlag(
        "abdomen",
        "Severe abdominal pain with a hard / rigid belly, or persistent vomiting?",
        "Seek emergency care now.",
    ),
    RedFlag(
        "pregnancy",
        "Pregnant and having bleeding, severe abdominal pain, fits or severe headache?",
        "Obstetric emergency. Go to the nearest hospital with maternity services now.",
    ),
    RedFlag(
        "infant",
        "Baby under 3 months with fever, or a child who is floppy, not feeding or not passing urine?",
        "Seek emergency paediatric care now.",
    ),
    RedFlag(
        "allergy",
        "Swelling of the face, lips or throat with difficulty breathing or swallowing?",
        "Possible anaphylaxis. Call 112/108 now.",
    ),
    RedFlag(
        "self_harm",
        "Thoughts of ending your life or harming yourself?",
        "You are not alone. Call Tele-MANAS 14416 (24x7, free) or 112 now.",
        "emergency",
    ),
)

FLAGS = {f.code: f for f in CHECKLIST}

# Symptoms from the free-text / adaptive part of the intake that re-trigger triage even
# if the checklist was answered 'no' (people under-report on checklists).
SYMPTOM_TRIGGERS = {
    "chest pain": "chest_pain",
    "facial deviation": "stroke",
    "paralysis": "stroke",
    "difficulty speaking": "stroke",
    "loss of consciousness": "unconscious",
    "unconsciousness": "unconscious",
    "seizures": "unconscious",
    "fainting": "unconscious",
    "hemoptysis": "bleeding",
    "blood in stool": "bleeding",
    "vision loss": "headache",
}


@dataclass(frozen=True)
class TriageResult:
    level: str  # emergency | urgent | routine
    flags: list[dict]

    @property
    def stop(self) -> bool:
        return self.level == "emergency"


def triage(checklist: dict[str, bool], symptoms: dict[str, bool] | None = None) -> TriageResult:
    hits = [FLAGS[c] for c, yes in checklist.items() if yes and c in FLAGS]
    for sym, present in (symptoms or {}).items():
        code = SYMPTOM_TRIGGERS.get(sym)
        if present and code and FLAGS[code] not in hits:
            # Reported during the symptom interview rather than the checklist: urgent
            # review rather than an outright stop, since onset/severity are unknown.
            hits.append(RedFlag(code, FLAGS[code].question, FLAGS[code].advice, "urgent"))
    level = (
        "emergency"
        if any(h.level == "emergency" for h in hits)
        else "urgent"
        if hits
        else "routine"
    )
    return TriageResult(
        level, [{"code": h.code, "level": h.level, "advice": h.advice} for h in hits]
    )
