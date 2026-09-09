"""Deterministic keyword-based provider.

Lets the entire application — and the whole test suite — run with no API key
and no network. Because it is deterministic, the persona scores in the demo are
reproducible, which is exactly what you want when demoing live.

Beyond the fields every lead has, it extracts the handful of fields that only
matter for one vertical (heating age, roof orientation, decision-making
power...) into ``AIAnalysis.details``. That mirrors what a real LLM would be
prompted to return, and it is what the per-vertical rules then score.

French only, deliberately: see the limits section of the README.
"""

import re
import unicodedata

from app.ai.base import REFERENCE_YEAR, AIProvider, age_bracket, company_size
from app.models.enums import Level, ProjectType, PropertyType, Vertical, vertical_for
from app.schemas.lead import AIAnalysis, LeadCreate

# Ordered: the first project type with a keyword hit wins. B2B and health
# come first because their vocabulary is the most distinctive.
PROJECT_KEYWORDS: list[tuple[ProjectType, tuple[str, ...]]] = [
    (ProjectType.IT_B2B, (
        "infogerance", "cybersecurite", "cyber securite", "erp", "crm ", "saas",
        "parc informatique", "systeme d'information", "si de l'entreprise",
        "migration cloud", "hebergement", "developpement logiciel", "logiciel metier",
        "rgpd de l'entreprise", "audit informatique", "prestataire informatique",
    )),
    (ProjectType.HEARING_AID, (
        "audioprothese", "aide auditive", "appareil auditif", "appareillage auditif",
        "j'entends mal", "perte d'audition", "audition", "malentendant",
        "acouphene", "audioprothesiste",
    )),
    (ProjectType.HEALTH_INSURANCE, (
        "mutuelle", "assurance sante", "complementaire sante", "prevoyance",
        "assurance emprunteur", "assurance de pret", "garantie obseque",
        "couverture sante", "tiers payant",
    )),
    (ProjectType.HEAT_PUMP, (
        "pompe a chaleur", "pac ", " pac", "heat pump", "aerothermie",
        "geothermie", "air/eau", "air eau",
    )),
    (ProjectType.SOLAR, (
        "solaire", "photovoltaique", "panneaux", "solar", "photovoltaic",
        "autoconsommation", "onduleur",
    )),
    (ProjectType.INSULATION, ("isolation", "isoler", "combles", "insulation")),
    (ProjectType.WINDOWS, ("fenetre", "double vitrage", "menuiserie", "window")),
    (ProjectType.BOILER, ("chaudiere", "boiler", "gaz condensation")),
]

URGENCY_HIGH = (
    "avant l'hiver", "avant l hiver", "urgent", "des que possible", "rapidement",
    "au plus vite", "cette semaine", "ce mois", "immediatement", "asap",
    "before winter", "echeance", "avant la fin de l'annee",
)
URGENCY_MEDIUM = (
    "prochainement", "dans les prochains mois", "cette annee", "printemps", "ete",
    "je reflechis a", "envisage", "next year", "planning", "l'annee prochaine",
)

INTENT_HIGH = (
    "je souhaite", "je veux", "je voudrais", "devis", "remplacer", "installer",
    "faire poser", "j'ai besoin", "je cherche a", "budget", "quote", "faire changer",
    "je compte", "nous souhaitons", "nous cherchons",
)
INTENT_MEDIUM = ("renseignement", "information", "combien", "savoir", "interesse", "curieux")

OWNER_HINTS = (
    "ma maison", "mon appartement", "proprietaire", "j'ai achete", "ma residence",
    "chez moi", "ma toiture", "mon logement", "mon pavillon",
)
TENANT_HINTS = ("je loue", "locataire", "mon proprietaire", "mon bailleur")

HOUSE_HINTS = ("maison", "pavillon", "villa", "house")
APARTMENT_HINTS = ("appartement", "apartment", "studio", "copropriete")

CITIES = (
    "Lyon", "Paris", "Marseille", "Bordeaux", "Lille", "Toulouse", "Nantes",
    "Nice", "Strasbourg", "Rennes", "Montpellier", "Grenoble", "Barcelona",
    "Barcelone", "Madrid", "Valence", "Milan", "Rome", "Turin", "Brussels",
    "Geneva", "Annecy", "Dijon", "Reims", "Tours",
)

MIN_MEANINGFUL_LENGTH = 25

# --- Per-vertical vocabularies -------------------------------------------

HEATING_SYSTEMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("oil_boiler", ("chaudiere fioul", "fioul", "mazout")),
    ("gas_boiler", ("chaudiere gaz", "chaudiere a gaz", "gaz de ville", "gaz condensation")),
    ("electric", ("convecteur", "radiateur electrique", "chauffage electrique", "grille-pain")),
    ("wood", ("poele a bois", "insert", "chaudiere bois", "granule", "pellet")),
    ("heat_pump", ("pompe a chaleur existante", "pac existante")),
)

ROOF_COVERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tiles", ("tuile", "tuiles")),
    ("slate", ("ardoise", "ardoises")),
    ("fibre_cement", ("fibro", "fibro-ciment", "fibrociment", "bac acier", "tole")),
    ("flat", ("toit plat", "toiture terrasse", "toit-terrasse")),
)

ORIENTATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("south", ("plein sud", "orientee sud", "oriente sud", "exposition sud", "expose sud", "exposee sud")),
    ("south_east", ("sud-est", "sud est")),
    ("south_west", ("sud-ouest", "sud ouest")),
    ("east_west", ("est-ouest", "est ouest")),
    ("north", ("plein nord", "orientee nord", "oriente nord")),
)

INSURANCE_NEEDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("borrower", ("emprunteur", "assurance de pret", "assurance pret", "credit immobilier")),
    ("provident", ("prevoyance", "obseque", "incapacite", "invalidite", "deces")),
    ("health", ("mutuelle", "complementaire sante", "assurance sante", "couverture sante", "sante")),
)

WORKS_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("insulation", ("isolation", "isoler", "combles", "murs")),
    ("windows", ("fenetre", "double vitrage", "menuiserie")),
    ("heating", ("chaudiere", "chauffage", "radiateur")),
    ("global", ("renovation globale", "renovation complete", "bouquet de travaux", "renovation energetique")),
)

IT_PROJECTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cybersecurity", ("cybersecurite", "cyber securite", "pentest", "soc ", "phishing", "ransomware")),
    ("managed_services", ("infogerance", "prestataire informatique", "parc informatique", "support informatique")),
    ("software", ("logiciel", "erp", "crm ", "saas", "developpement", "application metier")),
    ("cloud", ("migration cloud", "hebergement", "azure", "aws", "datacenter")),
)

DECISION_MAKER_TITLES = (
    "dsi", "directeur", "directrice", "gerant", "gerante", "president",
    "pdg", "ceo", "cto", "responsable informatique", "chef d'entreprise",
    "co-fondateur", "cofondateur", "associe",
)
INFLUENCER_TITLES = ("technicien", "assistant", "stagiaire", "alternant", "charge de")
DECISION_PHRASES = ("je decide", "c'est moi qui decide", "je suis le decideur", "je valide le budget")

SELF_DECLARED_HINTS = (
    "j'entends mal", "je n'entends", "j'ai du mal a entendre", "ma gene",
    "je suis malentendant", "mon audition", "je fais repeter", "j'ai des acouphenes",
    "je perds l'audition",
)
THIRD_PARTY_HINTS = (
    "pour ma mere", "pour mon pere", "pour mon mari", "pour ma femme",
    "pour mon epoux", "pour mon epouse", "pour mes parents", "pour ma grand-mere",
    "pour mon grand-pere", "mon proche", "ma mere entend", "mon pere entend",
)

COVERAGE_HINTS = ("mutuelle", "complementaire", "prise en charge", "remboursement", "securite sociale", "cmu")
NO_COVERAGE_HINTS = ("pas de mutuelle", "sans mutuelle", "aucune mutuelle", "pas de complementaire")

ACCOMPANIED_HINTS = ("ma fille m'accompagne", "accompagne par", "avec mon conjoint", "mon fils m'aide")

HOUSEHOLD_HINTS = (
    "marie", "mariee", "en couple", "pacse", "celibataire", "divorce",
    "avec mes enfants", "mes enfants", "ma famille", "mon conjoint",
)


def _normalize(text: str) -> str:
    """Lowercase and strip accents so keyword matching is accent-insensitive."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _match_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(needle in haystack for needle in needles)


def _first_label(text: str, table) -> str | None:
    """First (label, keywords) entry in ``table`` whose keywords appear."""
    for label, keywords in table:
        if _match_any(text, keywords):
            return label
    return None


class MockAIProvider(AIProvider):
    name = "mock"

    async def analyze_lead(self, lead: LeadCreate) -> AIAnalysis:
        raw = lead.project_description
        # Pad with spaces so keywords like "pac " match at either end.
        text = f" {_normalize(raw)} "

        project_type = self._project_type(text)
        vertical = vertical_for(project_type.value)
        is_vague = len(raw.strip()) < MIN_MEANINGFUL_LENGTH or project_type is ProjectType.UNKNOWN

        return AIAnalysis(
            project_type=project_type.value,
            location=self._location(raw),
            property_type=self._property_type(text).value,
            owner_intent=self._owner_intent(text),
            urgency=self._urgency(text, is_vague).value,
            purchase_intent=self._purchase_intent(text, is_vague).value,
            summary=self._summary(raw, project_type),
            provider=self.name,
            details=self._details(text, vertical),
        )

    # -- shared extractions ------------------------------------------------

    def _project_type(self, text: str) -> ProjectType:
        for project_type, keywords in PROJECT_KEYWORDS:
            if _match_any(text, keywords):
                return project_type
        return ProjectType.UNKNOWN

    def _location(self, raw: str) -> str | None:
        for city in CITIES:
            if re.search(rf"\b{re.escape(city)}\b", raw, flags=re.IGNORECASE):
                return city
        return None

    def _property_type(self, text: str) -> PropertyType:
        if _match_any(text, APARTMENT_HINTS):
            return PropertyType.APARTMENT
        if _match_any(text, HOUSE_HINTS):
            return PropertyType.HOUSE
        return PropertyType.UNKNOWN

    def _owner_intent(self, text: str) -> bool | None:
        if _match_any(text, TENANT_HINTS):
            return False
        if _match_any(text, OWNER_HINTS):
            return True
        return None

    def _urgency(self, text: str, is_vague: bool) -> Level:
        if is_vague:
            return Level.LOW
        if _match_any(text, URGENCY_HIGH):
            return Level.HIGH
        if _match_any(text, URGENCY_MEDIUM):
            return Level.MEDIUM
        return Level.LOW

    def _purchase_intent(self, text: str, is_vague: bool) -> Level:
        if is_vague:
            return Level.LOW
        if _match_any(text, INTENT_HIGH):
            return Level.HIGH
        if _match_any(text, INTENT_MEDIUM):
            return Level.MEDIUM
        return Level.LOW

    def _summary(self, raw: str, project_type: ProjectType) -> str:
        if project_type is ProjectType.UNKNOWN:
            return "Request too vague to identify a project type."
        label = project_type.value.replace("_", " ")
        excerpt = " ".join(raw.split())[:120]
        return f"Prospect interested in a {label} project: {excerpt}"

    # -- per-vertical extractions -----------------------------------------

    def _details(self, text: str, vertical: Vertical) -> dict:
        """Only extract what the lead's own vertical will actually score."""
        match vertical:
            case Vertical.HEAT_PUMP:
                return self._heat_pump_details(text)
            case Vertical.SOLAR:
                return self._solar_details(text)
            case Vertical.HEARING_AID:
                return self._hearing_details(text)
            case Vertical.HEALTH_INSURANCE:
                return self._insurance_details(text)
            case Vertical.ENERGY_RENOVATION:
                return self._renovation_details(text)
            case Vertical.IT_B2B:
                return self._it_details(text)
            case _:
                return {}

    def _surface(self, text: str) -> int | None:
        """Living area in m², written as '120m2', '120 m²' or '120 metres carres'."""
        match = re.search(r"(\d{2,4})\s?(?:m2|m²|metres? carres?)\b", text)
        return int(match.group(1)) if match else None

    def _years_old(self, text: str) -> int | None:
        """Age in years: 'de 20 ans', 'a 25 ans', '15 ans d'anciennete'."""
        match = re.search(r"\b(?:de|a|d'|environ)?\s?(\d{1,2})\s?ans?\b", text)
        return int(match.group(1)) if match else None

    def _build_year(self, text: str) -> int | None:
        """Construction year: 'construite en 1978', 'de 1975'."""
        match = re.search(r"\b(19\d{2}|20[0-2]\d)\b", text)
        return int(match.group(1)) if match else None

    # Heat pump criteria: ownership · current heating and its age
    # · surface and property type.
    def _heat_pump_details(self, text: str) -> dict:
        return {
            "heating_system": _first_label(text, HEATING_SYSTEMS),
            "heating_age_years": self._years_old(text),
            "surface_m2": self._surface(text),
        }

    # Solar: roof ownership · roof cover and dominant orientation
    # · self-consumption or selling the surplus.
    def _solar_details(self, text: str) -> dict:
        usage = None
        if "autoconsommation" in text:
            usage = "self_consumption"
        elif _match_any(text, ("revente", "revendre", "surplus", "vente du surplus")):
            usage = "surplus_resale"
        return {
            "roof_cover": _first_label(text, ROOF_COVERS),
            "roof_orientation": _first_label(text, ORIENTATIONS),
            "usage_model": usage,
            "surface_m2": self._surface(text),
        }

    # Hearing aids: the difficulty must be declared by the person themselves
    # · age bracket and whether they are accompanied · insurance coverage.
    def _hearing_details(self, text: str) -> dict:
        self_declared = None
        if _match_any(text, THIRD_PARTY_HINTS):
            self_declared = False
        elif _match_any(text, SELF_DECLARED_HINTS):
            self_declared = True

        coverage = None
        if _match_any(text, NO_COVERAGE_HINTS):
            coverage = False
        elif _match_any(text, COVERAGE_HINTS):
            coverage = True

        age = self._years_old(text)
        return {
            "self_declared": self_declared,
            "age_years": age,
            "age_bracket": age_bracket(age),
            "accompanied": True if _match_any(text, ACCOMPANIED_HINTS) else None,
            "has_coverage": coverage,
        }

    # Health insurance: nature of the need · household and beneficiaries
    # · current contract and its renewal date.
    def _insurance_details(self, text: str) -> dict:
        beneficiaries = None
        match = re.search(r"(\d{1,2})\s?(?:beneficiaires?|personnes?|enfants?)", text)
        if match:
            beneficiaries = int(match.group(1))

        has_contract = None
        if _match_any(text, ("pas de contrat", "aucun contrat", "sans mutuelle", "pas de mutuelle")):
            has_contract = False
        elif _match_any(text, ("je suis chez", "je suis assure", "nous sommes assures")):
            has_contract = True
        # "un contrat de mutuelle en cours" must match as well as "mon contrat
        # actuel", so allow words between the noun and the qualifier.
        elif re.search(r"contrat[^.!?]{0,40}(?:en cours|actuel)", text):
            has_contract = True
        elif re.search(r"(?:mon|notre|un)\s+contrat\b", text):
            has_contract = True

        return {
            "need_type": _first_label(text, INSURANCE_NEEDS),
            "household": _match_any(text, HOUSEHOLD_HINTS) or None,
            "beneficiaries": beneficiaries,
            "has_current_contract": has_contract,
            "contract_end_known": bool(
                _match_any(text, ("echeance", "renouvellement", "fin de contrat", "resiliation"))
            )
            or None,
        }

    # Energy renovation: owner-occupier or landlord · property age and type
    # · nature of the planned works.
    def _renovation_details(self, text: str) -> dict:
        owner_type = None
        if _match_any(text, ("bailleur", "je loue a", "locatif", "mon locataire")):
            owner_type = "landlord"
        elif _match_any(text, TENANT_HINTS):
            owner_type = "tenant"
        elif _match_any(text, OWNER_HINTS):
            owner_type = "owner_occupier"

        year = self._build_year(text)
        return {
            "owner_type": owner_type,
            "build_year": year,
            "property_age_years": (REFERENCE_YEAR - year) if year else self._years_old(text),
            "works_type": _first_label(text, WORKS_TYPES),
            "surface_m2": self._surface(text),
        }

    # IT B2B: the contact's role and decision-making power · company size and
    # sector · nature of the project.
    def _it_details(self, text: str) -> dict:
        role = None
        if _match_any(text, DECISION_MAKER_TITLES) or _match_any(text, DECISION_PHRASES):
            role = "decision_maker"
        elif _match_any(text, INFLUENCER_TITLES):
            role = "influencer"

        headcount = None
        match = re.search(r"(\d{1,5})\s?(?:salaries?|employes?|collaborateurs?|personnes?|postes?)", text)
        if match:
            headcount = int(match.group(1))

        return {
            "contact_role": role,
            "headcount": headcount,
            "company_size": company_size(headcount),
            "sector": self._sector(text),
            "it_project": _first_label(text, IT_PROJECTS),
        }

    def _sector(self, text: str) -> str | None:
        sectors = (
            ("industry", ("industrie", "usine", "production", "manufacture")),
            ("retail", ("commerce", "retail", "magasin", "e-commerce")),
            ("healthcare", ("clinique", "hopital", "cabinet medical", "pharmacie")),
            ("services", ("cabinet", "conseil", "agence", "expertise comptable")),
            ("construction", ("btp", "batiment", "construction", "travaux publics")),
            ("public", ("mairie", "collectivite", "administration", "ministere")),
        )
        return _first_label(text, sectors)
