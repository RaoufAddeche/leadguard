"""Demo seed.

Gives the dashboard realistic volume across all six verticals, and a review
history, while deliberately leaving the scripted demo personas OUT of the
database: they are created live from the UI during the demo, so they must not
already exist — otherwise Thomas would immediately be flagged as a duplicate
instead of scoring 94/QUALIFIED.

The duplicate scenario is therefore demonstrated with its own pair (Olivier
submitted twice), so the dashboard still shows a duplicate on a cold start.

Run with:  python -m app.db.seed
"""

import asyncio
import logging

from sqlalchemy import delete, select

from app.ai.factory import build_provider
from app.config import get_settings
from app.db.session import SessionLocal, init_db
from app.integrations.crm import build_crm_client
from app.models import Lead, LeadEvent
from app.models.enums import LeadStatus
from app.schemas.lead import HumanDecision, LeadCreate
from app.services.lead_service import apply_human_decision, process_lead

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("leadguard.seed")


# =====================================================================
#  Demo personas — NOT inserted by the seed.
#  Exported so the API can serve them to the frontend's prefill buttons,
#  and so the tests and the README all quote the same payloads.
# =====================================================================

# Heat pump, excellent → 94, QUALIFIED, PAC Lyon.
# Note what is *missing*: he never says how old the boiler is, which is the
# second half of the heat pump criterion, so that rule only earns partial
# credit. Even an excellent lead has a gap, and the score names it.
THOMAS = LeadCreate(
    firstname="Thomas",
    lastname="Martin",
    email="thomas.martin@email.fr",
    phone="0612345678",
    postal_code="69003",
    source="google_ads",
    campaign="PAC_Lyon",
    project_description=(
        "J'ai acheté une maison près de Lyon et je souhaite remplacer ma chaudière "
        "fioul par une pompe à chaleur dans ma maison de 120m2 avant l'hiver."
    ),
    owner=True,
    budget=12000,
    consent=True,
)

# Solar, incomplete → 72, REVIEW. The roof profile and the usage model are
# both clear; roof ownership — the first solar criterion — is not.
LAURA = LeadCreate(
    firstname="Laura",
    lastname="Garcia",
    email="laura.garcia@email.fr",
    phone="0745129863",
    postal_code="34000",
    source="meta_ads",
    campaign="Solaire_Printemps",
    project_description=(
        "Je m'intéresse à l'installation de panneaux solaires photovoltaïques sur une "
        "toiture en tuiles exposée plein sud à Montpellier, en autoconsommation, "
        "et je voudrais des renseignements."
    ),
    owner=None,
    budget=None,
    consent=True,
)

# No identifiable vertical → capped at 68, scores 8, REJECTED.
MARCO = LeadCreate(
    firstname="Marco",
    lastname="Rossi",
    email="marco.rossi@email.fr",
    phone="123",
    postal_code="75001",
    source="partner_form",
    campaign="Generic_FR",
    project_description="Des infos svp",
    owner=None,
    budget=None,
    consent=False,
)

# Hearing aids, excellent → 93. She declares the difficulty herself.
HELENE = LeadCreate(
    firstname="Hélène",
    lastname="Moreau",
    email="helene.moreau@email.fr",
    phone="0678451236",
    postal_code="75011",
    source="google_ads",
    campaign="Audio_IDF",
    project_description=(
        "J'ai 72 ans, j'entends mal depuis deux ans et je fais répéter mes proches. "
        "Je souhaite un appareil auditif, j'ai une bonne mutuelle avec prise en charge."
    ),
    owner=None,
    budget=None,
    consent=True,
)

# Hearing aids, enquiring for someone else → 66, REVIEW.
# The person concerned has not declared the difficulty herself, so the
# strictest rule in the vertical blocks automatic qualification.
BERNARD = LeadCreate(
    firstname="Bernard",
    lastname="Leroy",
    email="bernard.leroy@email.fr",
    phone="0623987451",
    postal_code="44000",
    source="partner_form",
    campaign="Audio_Ouest",
    project_description=(
        "Je cherche un appareil auditif pour ma mère qui entend mal, "
        "elle a 80 ans et une mutuelle."
    ),
    owner=None,
    budget=None,
    consent=True,
)

# IT B2B, excellent → 100. Decision-maker, sized company, scoped project.
SYLVIE = LeadCreate(
    firstname="Sylvie",
    lastname="Chen",
    email="s.chen@groupe-industriel.fr",
    phone="0155667788",
    postal_code="92100",
    source="partner_form",
    campaign="IT_Infogerance",
    project_description=(
        "Je suis DSI d'une industrie de 180 salariés et je décide du budget. "
        "Nous cherchons un prestataire pour l'infogérance de notre parc "
        "informatique dès que possible."
    ),
    owner=None,
    budget=None,
    consent=True,
)

# IT B2B without buying authority → 67, REVIEW.
KEVIN = LeadCreate(
    firstname="Kevin",
    lastname="Petit",
    email="k.petit@boutique-lyon.fr",
    phone="0155667799",
    postal_code="69007",
    source="partner_form",
    campaign="IT_Cyber",
    project_description=(
        "Je suis technicien et je me renseigne sur la cybersécurité pour notre commerce."
    ),
    owner=None,
    budget=None,
    consent=True,
)

DEMO_PERSONAS = {
    "thomas": THOMAS,
    "laura": LAURA,
    "marco": MARCO,
    "helene": HELENE,
    "bernard": BERNARD,
    "sylvie": SYLVIE,
    "kevin": KEVIN,
}


# =====================================================================
#  What the seed actually inserts — one or two leads per vertical, so the
#  dashboard shows all six lines of business on a cold start.
# =====================================================================

SEEDED = [
    # --- Health insurance -------------------------------------------
    LeadCreate(
        firstname="Nadia", lastname="Benkacem", email="nadia.benkacem@email.fr",
        phone="0699123456", postal_code="13008", source="google_ads", campaign="Sante_Famille",
        project_description=(
            "Je suis mariée avec 3 enfants, nous avons un contrat de mutuelle en cours "
            "mais l'échéance est en décembre. Je souhaite comparer une complémentaire "
            "santé pour 5 bénéficiaires."
        ),
        owner=None, budget=None, consent=True,
    ),
    LeadCreate(
        firstname="Olivier", lastname="Fabre", email="olivier.fabre@email.fr",
        phone="0611998877", postal_code="31000", source="meta_ads", campaign="Emprunteur",
        project_description=(
            "Je finalise un crédit immobilier et je veux changer d'assurance emprunteur, "
            "mon contrat actuel arrive à échéance le mois prochain. Je suis en couple."
        ),
        owner=None, budget=None, consent=True,
    ),
    # --- Energy renovation -------------------------------------------
    LeadCreate(
        firstname="Pierre", lastname="Dubois", email="pierre.dubois@email.fr",
        phone="0611223344", postal_code="59000", source="partner_form", campaign="Reno_Globale",
        project_description=(
            "Propriétaire de ma maison construite en 1975 de 110m2, je veux faire une "
            "rénovation globale avec isolation des combles rapidement."
        ),
        owner=True, budget=25000, consent=True,
    ),
    LeadCreate(
        firstname="Julie", lastname="Petit", email="julie.petit@email.fr",
        phone="0699123457", postal_code="44000", source="partner_form", campaign="Reno_Ouest",
        project_description=(
            "Je loue mon logement et je me demande si l'isolation des combles est "
            "possible, je cherche des informations."
        ),
        owner=False, budget=None, consent=True,
    ),
    # --- Heat pump ----------------------------------------------------
    LeadCreate(
        firstname="Sophie", lastname="Bernard", email="sophie.bernard@email.fr",
        phone="0678451237", postal_code="75011", source="google_ads", campaign="PAC_Paris",
        project_description=(
            "Propriétaire d'un appartement de 70m2 à Paris avec des convecteurs "
            "électriques de 15 ans, je veux installer une pompe à chaleur air/eau "
            "rapidement, mon budget est d'environ 16000 euros."
        ),
        owner=True, budget=16000, consent=True,
    ),
    # --- Solar --------------------------------------------------------
    LeadCreate(
        firstname="Karim", lastname="Benali", email="karim.benali@email.fr",
        phone="0623987452", postal_code="13008", source="meta_ads", campaign="Solaire_Sud",
        project_description=(
            "Je souhaite faire installer des panneaux solaires sur ma maison à Marseille, "
            "toiture en tuiles plein sud, en revente de surplus, budget 14000 euros, "
            "dès que possible."
        ),
        owner=True, budget=14000, consent=True,
    ),
    # --- Hearing aids -------------------------------------------------
    LeadCreate(
        firstname="Gérard", lastname="Lambert", email="gerard.lambert@email.fr",
        phone="0688774411", postal_code="33000", source="google_ads", campaign="Audio_Sud_Ouest",
        project_description=(
            "J'ai 68 ans et j'entends mal en réunion, je souhaite un appareillage auditif. "
            "Je n'ai pas de mutuelle actuellement."
        ),
        owner=None, budget=None, consent=True,
    ),
    # --- IT B2B -------------------------------------------------------
    LeadCreate(
        firstname="Farid", lastname="Haddad", email="f.haddad@clinique-est.fr",
        phone="0388991122", postal_code="67000", source="partner_form", campaign="IT_Cyber",
        project_description=(
            "Directeur d'une clinique de 320 salariés, je cherche un audit de "
            "cybersécurité après une alerte phishing. C'est urgent et je valide le budget."
        ),
        owner=None, budget=None, consent=True,
    ),
    # --- Spain: shows the multi-country path -------------------------
    LeadCreate(
        firstname="Elena", lastname="Ruiz", email="elena.ruiz@email.es",
        phone="612345678", postal_code="08001", country="ES",
        source="meta_ads", campaign="Solar_Barcelona",
        project_description=(
            "Je suis propriétaire à Barcelona et je souhaite installer des panneaux "
            "solaires en autoconsommation sur ma toiture en tuiles plein sud, "
            "budget 13000 euros."
        ),
        owner=True, budget=13000, consent=True,
    ),
    # --- Two leads that stay in the review queue ----------------------
    # A relative enquiring on someone else's behalf: the person concerned has
    # not declared the difficulty herself, so this cannot be auto-qualified.
    LeadCreate(
        firstname="Martine", lastname="Girard", email="martine.girard@email.fr",
        phone="0677889900", postal_code="69006", source="google_ads", campaign="Audio_Lyon",
        project_description=(
            "Je voudrais un appareil auditif pour mon mari qui entend mal, "
            "il a 78 ans et nous avons une mutuelle."
        ),
        owner=None, budget=None, consent=True,
    ),
    # A B2B contact who cannot sign: needs a decision-maker before it is sold.
    LeadCreate(
        firstname="Thibault", lastname="Roux", email="t.roux@agence-conseil.fr",
        phone="0144556677", postal_code="75008", source="partner_form", campaign="IT_Logiciel",
        project_description=(
            "Je suis chargé de mission dans un cabinet de conseil et je me renseigne "
            "sur un logiciel métier pour nos équipes."
        ),
        owner=None, budget=None, consent=True,
    ),

    # --- No consent: rejected but kept on file ------------------------
    LeadCreate(
        firstname="Paul", lastname="Durand", email="paul.durand@mailinator.com",
        phone="0102030405", postal_code="59000", source="external", campaign="Affiliate_Mix",
        project_description="Bonjour", owner=None, budget=None, consent=False,
    ),
]


async def reset(db) -> None:
    await db.execute(delete(LeadEvent))
    await db.execute(delete(Lead))
    await db.commit()


async def seed(reset_first: bool = True) -> None:
    settings = get_settings()
    await init_db()
    provider = build_provider(settings)

    # Imported here so the seed can reuse the ASGI loopback CRM client:
    # seeded qualified leads then show a real CRM_SYNC=SUCCESS rather than a
    # confusing "no CRM client configured" on their detail page.
    from app.main import app as fastapi_app

    crm_client = build_crm_client(app=fastapi_app, settings=settings)

    async with SessionLocal() as db:
        if reset_first:
            await reset(db)

        plan = [(f"{p.firstname} {p.lastname}", p, "api") for p in SEEDED]
        # Duplicate scenario: Olivier submits the same form twice through a
        # different channel. He scores 96 on his own, so the -40 penalty lands
        # him at 56 — in the review band, never auto-qualified. That is the
        # rule, visible on the dashboard from a cold start.
        plan.append(("Olivier Fabre (2nd submission)", SEEDED[1], "webhook:meta_ads"))

        for label, payload, channel in plan:
            result = await process_lead(
                db, payload, provider, crm_client=crm_client, channel=channel, settings=settings
            )
            flag = " [DUPLICATE]" if result.duplicate.duplicate else ""
            logger.info(
                "%-34s %s  %-18s score=%3d  %-9s crm=%-8s team=%s%s",
                label, result.public_id, result.vertical, result.score, result.status,
                result.crm_status, result.team or "-", flag,
            )

        # Record one human decision so the dashboard ships with a review
        # history: Julie rents her home, so a reviewer rejects her.
        julie = (
            await db.execute(
                select(Lead)
                .where(Lead.lastname == "Petit", Lead.human_status.is_(None))
                .order_by(Lead.id)
            )
        ).unique().scalars().first()
        if julie is not None:
            await apply_human_decision(
                db, julie,
                HumanDecision(
                    decision=LeadStatus.REJECTED,
                    reviewer="demo-user",
                    reason="Prospect rents the property and cannot commission the work.",
                ),
                crm_client=crm_client,
            )
            logger.info("%-34s %s  human decision recorded: REJECTED", "review history", julie.public_id)

    logger.info(
        "Seed complete. The demo personas (%s) are intentionally NOT seeded — "
        "create them live from the UI.",
        ", ".join(sorted(DEMO_PERSONAS)),
    )


if __name__ == "__main__":
    asyncio.run(seed())
