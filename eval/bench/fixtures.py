"""Synthetic benchmark material. Fictional: no real person, CV or vacancy text."""

VACANCY_NL = """\
Functie: AI Developer (32-36 uur), Nederlandse overheidsorganisatie, Den Haag.
Wat ga je doen: je bouwt en beheert AI-toepassingen voor analisten, van prototype tot productie.
Eisen:
- Afgeronde hbo- of wo-opleiding in informatica, data science of vergelijkbaar.
- Minimaal 2 jaar ervaring met Python in productie.
- Ervaring met het bouwen van toepassingen op basis van taalmodellen (LLM's).
- Kennis van DevOps: CI/CD, containers en monitoring.
Wensen:
- Ervaring met open-source modellen en lokale inferentie.
- Kennis van privacy by design en de AVG.
Je werkt in een multidisciplinair team en rapporteert aan de teamleider data & AI.
"""

CV_SNIPPET = """\
[PERSON_1] - Data Engineer bij ACME Logistics (2022-2026)
- Bouwde een Python-pipeline die dagelijks 40 miljoen sensormetingen verwerkt.
- Zette CI/CD op met GitHub Actions en Docker voor 6 services.
- Ontwikkelde een prototype chatbot op basis van een open-source taalmodel voor de servicedesk.
Opleiding: MSc Civil Engineering, TU Delft (2021).
"""

PERSONA = (
    "You are {persona}, interviewing a candidate for the vacancy below. Ask exactly one "
    "question of at most two sentences, in {language}. Never ask about age, religion, health, "
    "pregnancy, origin or other protected characteristics. Output only the question."
)

# (persona, language, conversation so far, next move decided by Jev)
INTERVIEWER_CASES = [
    ("a friendly account manager", "Dutch", [], "opening question about motivation"),
    (
        "a technical lead",
        "Dutch",
        [
            ("assistant", "Kun je vertellen over je ervaring met Python in productie?"),
            ("user", "Ik heb bij ACME een pipeline gebouwd die veel data verwerkt."),
        ],
        "probe_deeper: the answer is vague and misses the result",
    ),
    (
        "a critical hiring manager",
        "Dutch",
        [
            ("assistant", "Wat heb je met taalmodellen gebouwd?"),
            ("user", "Ik heb een chatbot gemaakt die de hele servicedesk heeft vervangen."),
        ],
        "challenge: the answer may overclaim compared with the CV",
    ),
    ("a friendly account manager", "English", [], "opening question about motivation"),
    (
        "a technical lead",
        "English",
        [
            ("assistant", "How did you set up CI/CD for those services?"),
            ("user", "We used GitHub Actions and Docker."),
        ],
        "probe_deeper: ask how exactly, and what the candidate did personally",
    ),
    (
        "a critical hiring manager",
        "English",
        [
            ("assistant", "Why do you want to move from logistics to government?"),
            ("user", "I want more impact and I like public-sector work."),
        ],
        "next_topic: move on to privacy by design and the GDPR",
    ),
]
