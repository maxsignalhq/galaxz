from agents.rigel.skills.code_generation import code_generation
from agents.rigel.skills.debug_triage import debug_triage
from agents.rigel.skills.pr_review import pr_review
from agents.rigel.skills.refactor import refactor
from agents.rigel.skills.scaffold import scaffold
from agents.rigel.skills.write_tests import write_tests

SKILL_REGISTRY: dict = {
    "rigel.skill.code_generation": code_generation,
    "rigel.skill.pr_review": pr_review,
    "rigel.skill.test_writing": write_tests,
    "rigel.skill.refactor": refactor,
    "rigel.skill.scaffold": scaffold,
    "rigel.skill.debug_triage": debug_triage,
}
