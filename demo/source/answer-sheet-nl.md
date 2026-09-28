# Antwoordblad voor de demo-ronde (fictieve kandidaat: Sanne Visser)

Hiermee beantwoord je de vragen *als Sanne* tijdens de Nederlandse demo-ronde. Alles is fictief
en klopt met `cv-nl.md`. Formuleer vrij: het moet lezen alsof een echt mens het typt.

## Instellingen
- Vacature: `vacancy-nl.md` (als bestand), cv: `cv-nl.md`.
- Soort gesprek **Gemengd**, duur **15 min**, antwoorden **Typen**, moeilijkheid **Realistisch**,
  taal **Nederlands**.

## Zo wordt de terugblik interessant
- Geef **twee of drie sterke STAR-antwoorden** (verhaal 1, 2 of 3): situatie, je taak, wat *jij*
  deed en een resultaat met een getal.
- Geef **één bewust zwakker antwoord**: algemeen, geen concreet voorbeeld, geen resultaat
  (bijvoorbeeld over stakeholders: "Ik probeer altijd duidelijk te communiceren en iedereen vroeg
  te betrekken.").
- Geef **één antwoord zonder resultaat** (vertel verhaal 4, maar stop na de acties).
- Stel bij de afsluitende vraag één of twee goede vragen (zie onderaan).
- Houd antwoorden rond de 60–150 woorden.

## Verhalen

**1. RAG-assistent voor douaneregels (Havenlogistiek, 2023–nu)**
S: 40 planners verloren tijd met zoeken naar douaneregels in pdf's en mailboxen; antwoorden waren
niet consistent. T: een assistent bouwen die antwoordt met de juiste bron erbij. A: planners
geïnterviewd, een RAG-pipeline in Python met LangChain gebouwd over de regeldocumenten, een
bronvermelding in elk antwoord verplicht gemaakt, eerst een pilot met 5 planners en daarna alle 40.
R: gemiddelde zoektijd per vraag van 12 naar 3 minuten; planners vertrouwen het omdat elk
antwoord de bron laat zien.

**2. Evaluatieset en guardrails (Havenlogistiek)**
S: de eerste versie verzon soms regels. T: kwaliteit meetbaar maken en foute antwoorden
terugdringen. A: een evaluatieset van 200 vragen opgezet met antwoorden die twee senior planners
controleerden, die set bij elke wijziging in CI laten draaien, guardrails toegevoegd (weigeren als
er geen bron is, de bron tonen). R: foute antwoorden van 18% naar 6% in drie iteraties; geen
release zonder dat de set slaagt.

**3. Van batch naar streaming (DataWerk Consultancy, 2021–2023)**
S: een energieklant kreeg dagrapportages een dag te laat. T: de pipeline versnellen zonder
bestaande rapportages te breken. A: de batchjob herontworpen als streaming-opzet met
Airflow-triggers en PostgreSQL, twee weken oud en nieuw naast elkaar gedraaid en de uitkomsten
vergeleken. R: doorlooptijd van rapportages van een dag naar 15 minuten; de klant gebruikte het
voor beslissingen binnen de dag.

**4. Klantdata pseudonimiseren met een privacy officer (DataWerk)**
S: een logistieke klant wilde analyses op chauffeursdata met persoonsgegevens. T: dat AVG-proof
maken. A: samen met de privacy officer een DPIA gedaan, namen en kentekens vervangen door
pseudoniemen voordat de data in de analyseomgeving kwam, vastgelegd wie wat mag zien.
R: (laat dit weg in het antwoord "zonder resultaat") goedgekeurd door de FG van de klant; de
analyses gingen twee weken later live dan gepland, maar zonder bevindingen in de audit.

**5. Uitleggen aan niet-technische collega's**
Organiseert een maandelijkse meetup over open-source AI (ca. 30 deelnemers); gaf bij Havenlogistiek
een demo aan het managementteam en legde in gewone taal uit waarom de assistent soms "dat weet ik
niet" zegt, en waarom dat juist een goede eigenschap is.

**6. Zwakke plekken (eerlijke gaten)**
- Kubernetes: basiskennis, het platformteam beheert het cluster.
- Publieke sector: alleen een stage bij een waterschap; gemotiveerd om aan dienstverlening voor
  inwoners te werken.
- Ervaring met taalmodellen: twee jaar, niet meer.

## Motivatie (als gevraagd wordt waarom deze functie)
Wil AI bouwen die inwoners direct helpt, waar betrouwbaarheid en privacy belangrijker zijn dan
opvallende features; de nadruk van de gemeente op uitlegbaarheid past bij hoe Sanne werkte met
bronvermelding en evaluatiesets.

## Vragen voor de interviewer (afsluiting)
- Hoe bepalen jullie wanneer een AI-toepassing goed genoeg is om aan inwoners voor te leggen?
- Wie in het team is eigenaar van de evaluatie van modeluitvoer zodra iets live staat?
