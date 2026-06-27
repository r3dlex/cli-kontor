"""Python rules for kontor-cli.
Called after YAML DSL rules with no match.
Should return a folder path or None to pass through to NL/LLM.
"""

from __future__ import annotations

import re  # noqa: F401
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kontor_cli.himalaya import Email


EXTERNAL_TO_FOLDER: dict[str, str] = {
    "viseo.com": "3_External/Viseo",
    "herodevs.com": "3_External/HeroDevs",
    "mommies-kitchen-gang.de": "3_External/Mommies-Kitchen",
    "tuxcare.com": "3_External/TuxCare",
    "adobesign.com": "3_External/AdobeSign",
    "arval.de": "3_External/Arval",
    "se.com": "3_External/Schneider",
    "tailormade.catering": "3_External/TailorMade",
    "placer.ai": "3_External/Placer",
    "eventbrite.com": "3_External/Eventbrite",
    "getcontrast.com": "3_External/Contrast",
    "goengineer.com": "3_External/GoEngineer",
    "lapid.org": "3_External/Lapid",
    "beonex.com": "3_External/Beonex",
    "t-online.de": "3_External/TOnline",
    "informa.com": "3_External/Informa",
    "wegaconsulting.de": "3_External/WeGa",
    "peugeot.com": "3_External/Peugeot",
    "stellantis.com": "3_External/Stellantis",
    "inno2fleet.com": "3_External/Inno2Fleet",
    "5d-institut.de": "3_External/5DInstitut",
    "sonarsource.com": "3_External/SonarSource",
    "google.com": "3_External/Google",
    "gmail.com": "3_External/Google",
    "contexus.com": "3_External/Contexus",
    "jobrad.de": "3_External/JobRad",
    "peakon.com": "3_External/Peakon",
    "promoteinternational.com": "3_External/PromoteIntl",
    "mentimeter.com": "3_External/Mentimeter",
}


def classify(email: Email) -> str | None:
    """Python rules evaluator.

    Called after all YAML DSL rules have been checked.
    Returns folder path or None to pass through to LLM.
    """
    from_addr = email.from_addr
    subject = email.subject.lower()

    # External sender: extract domain and map
    if "@" in from_addr:
        domain = from_addr.split("@")[-1].lower()

        # Check explicit mappings first
        for ext_domain, folder in EXTERNAL_TO_FOLDER.items():
            if domain == ext_domain or domain.endswith("." + ext_domain):
                return folder

        # For rib-software.com, try subject-based classification
        if "rib-software.com" in domain:
            # Check for specific project topics
            if "augment" in subject:
                return "2_Projects/Augment"
            if "ai" in subject or "estimate" in subject or "incubator" in subject:
                return "1_Management/AI"
            if "jira" in subject or "confluence" in subject:
                return "9_System"
            if "release" in subject or "thermometer" in subject:
                return "2_Projects/Releases"
            if any(w in subject for w in ["willemen", "hypercare", "escalat"]):
                return "2_Projects/Willemen"
            if any(w in subject for w in ["eiffage"]):
                return "2_Projects/Eiffage"
            if any(w in subject for w in ["vinci"]):
                return "2_Projects/Vinci"
            if any(w in subject for w in ["budimex", "ratisbona"]):
                return "2_Projects/Budimex"
            if any(w in subject for w in ["purchase", "approval", "pull request"]):
                return "2_Projects/Internal"
            if any(w in subject for w in ["azure", "trusted signing"]):
                return "2_Projects/AzureSigning"
            if any(w in subject for w in ["1:1", "1on1", "one-on-one"]):
                return "1_Management/1on1"
            if any(w in subject for w in ["travel", "reise", "hotel"]):
                return "4_Info"
            if any(w in subject for w in ["elternzeit", "krankmeldung", "interview"]):
                return "1_Management/HR"
            if any(w in subject for w in ["rechnung", "invoice", "budget"]):
                return "4_Info"
            # Default internal: 2_Projects/Internal
            return "2_Projects/Internal"

        # Unknown external: create folder 3_External/<Company>
        # Extract company from domain
        parts = domain.replace("www.", "").split(".")
        if len(parts) >= 2:
            company = parts[-2].title()
            return f"3_External/{company}"

    return None
