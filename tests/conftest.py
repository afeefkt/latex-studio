# ── Phase 4: Test conftest — shared fixtures ──

import pytest
from app.guard.factbank import FactBank
from app.guard.models import MatchedRequirement, TailorResponse

# ── Inline test facts (subset, self-contained) ──

@pytest.fixture
def sample_facts() -> FactBank:
    return FactBank(
        raw={},
        all_fact_ids={
            "koosys", "koosys_foc", "koosys_plant", "koosys_integration", "koosys_ci",
            "valentum", "valentum_testing", "valentum_static", "valentum_debug",
            "tataelxsi", "tata_eps", "tata_codegen", "tata_compliance",
            "ada", "ada_design", "ada_modeling", "ada_automation",
        },
        all_numbers={
            "8 years", "8", "6",
            "2024", "2023", "2021", "2017", "3", "10",
            "1 year", "1 year 1 month", "40", "60", "70", "90",
            "2011", "2015", "2015", "2022",
        },
        all_entities={
            "KooSys GmbH", "Valentum Engineering GmbH", "TATA Elxsi Ltd",
            "Aeronautical Development Agency", "Regensburg", "Bangalore",
            "MATLAB/Simulink", "Embedded Coder", "CANoe", "WinIDEA",
            "Helix QAC", "CppUTest", "TESSY", "DOORS", "Polarion", "XCP",
            "StateFlow", "MXAM", "Polyspace", "Davinci", "Reactis",
            "Simscape", "Catia V5", "Team Center", "MS Office",
            "AUTOSAR Classic", "Embedded C", "Python", "C/C++", "C#", "Java", "CAPL",
            "ISO", "ISO 26262", "ISO 26262 ASIL-B",
            "Mahatma Gandhi University", "B.Tech Mechanical Engineering",
            "MIL/SIL/HIL", "AUTOSAR", "Motor Control",
            "Extra Mile Award",
        },
        all_skills={
            "AUTOSAR Classic", "Embedded C", "MATLAB/Simulink", "Stateflow",
            "CANoe", "Python", "MIL/SIL/HIL", "ISO 26262 ASIL-B",
            "CppUTest", "Helix QAC", "TESSY", "DOORS", "Polarion",
            "XCP", "Simscape", "Catia V5", "C#", "Java", "CAPL",
        },
        banned_claims=[
            "istqb", "do-178c certified", "do-254", "security clearance",
            "sicherheitsüberprüfung", "phd", "master's degree",
            "team lead", "managed a team", "yocto", "embedded linux", "itar",
        ],
        certifications_held=[],
        certifications_in_progress=[
            {"name": "DO-178C", "status": "self-study",
             "claimable_as": "familiar with the objectives of DO-178C"},
        ],
    )


@pytest.fixture
def sample_job_ad() -> str:
    return """
        Senior Embedded Software Engineer — Motor Control

        We are looking for an experienced Embedded Software Engineer to join our
        electric motor control team in Munich. You will develop AUTOSAR-compliant
        software for next-generation electric drive systems.

        Requirements:
        - 5+ years of experience in embedded C development
        - Strong knowledge of AUTOSAR Classic and ISO 26262 functional safety
        - Experience with model-based development using MATLAB/Simulink
        - Familiarity with CAN bus and CANoe for testing and validation
        - Experience with MIL/SIL/HIL testing methodologies
        - Knowledge of ASPICE development processes
        - German language skills are a plus

        Nice to have:
        - Motor control algorithm development (FOC, Field Weakening)
        - Experience with Helix QAC or other static analysis tools
        - Python scripting for test automation
    """


# ── Valid response ──

@pytest.fixture
def valid_response() -> TailorResponse:
    return TailorResponse(
        matched_requirements=[
            MatchedRequirement(
                jd_phrase="model-based development using MATLAB/Simulink",
                fact_ids=["koosys_foc", "koosys_plant", "tata_eps"],
                confidence=0.95,
            ),
            MatchedRequirement(
                jd_phrase="AUTOSAR Classic and ISO 26262",
                fact_ids=["koosys_foc", "tata_eps", "tata_compliance"],
                confidence=0.90,
            ),
            MatchedRequirement(
                jd_phrase="MIL/SIL/HIL testing",
                fact_ids=["koosys_plant", "tata_codegen"],
                confidence=0.85,
            ),
        ],
        selected_bullet_ids=["koosys_foc", "koosys_plant", "koosys_ci", "tata_eps"],
        focus_phrase="model-based development using MATLAB/Simulink",
        hook_key="exact_match",
        unmatched_requirements=["Motor control algorithm (FOC)"],
        notes_for_human="Strong match on MBD and AUTOSAR. FOC is mentioned in JD but only in nice-to-have.",
    )


# ── Valid assembled letter text (for Pass 2 rules) ──

@pytest.fixture
def valid_letter_text() -> str:
    return (
        "With over 8 years of experience in embedded software engineering, "
        "I bring expertise in AUTOSAR Classic and model-based development with "
        "MATLAB/Simulink. At KooSys GmbH, I developed MBD-based FOC algorithms "
        "for 6-phase IPMSM and generated AUTOSAR ASIL-B compliant code via "
        "Embedded Coder. I built a 6-phase IPMSM Plant Model and MIL environment "
        "for performance validation. I currently work with ISO 26262 ASIL-B "
        "safety standards and am familiar with the objectives of DO-178C. "
        "My experience spans the full V-cycle from requirements in DOORS/Polarion "
        "through to system validation testing with CANoe and WinIDEA."
        * 3  # repeat to reach ~250 words
    )
