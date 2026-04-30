import json
import sys
from uuid import uuid4

import click

from agents.vega.pipeline import run_vega_pipeline
from core.contracts import TaskContract


@click.group()
def galaxz():
    pass


@galaxz.command()
@click.option("--input", "input_path", required=True, help="Path to requirements file")
@click.option("--results", default=None, help="Path to test results JSON file (optional)")
@click.option("--config", default="config/providers.yaml", help="Path to providers.yaml")
@click.option("--output", default=None, help="Path to save JSON output (optional)")
def vega(input_path, results, config, output):
    """Run the Vega QA pipeline."""
    try:
        with open(input_path) as f:
            raw_requirements = f.read()

        test_results = None
        if results is not None:
            with open(results) as f:
                test_results = json.load(f)

        result = run_vega_pipeline(
            raw_requirements=raw_requirements,
            test_results=test_results,
            config_path=config,
        )

        print(f"run_id: {result['run_id']}")
        print(f"Requirements found: {result['analyzer']['total_count']}")
        print(f"Test cases generated: {result['test_designer']['total_count']}")
        if result["bug_reporter"] is None:
            print("Bugs reported: Stage 3 skipped")
        else:
            print(f"Bugs reported: {result['bug_reporter']['total_bugs']}")

        if output is not None:
            with open(output, "w") as f:
                json.dump(result, f, indent=2, default=str)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


@galaxz.command()
@click.option("--skill",   required=True, help="Skill ID e.g. rigel.skill.code_generation")
@click.option("--payload", required=True, help="JSON string of task payload")
@click.option("--config",  default="config/providers.yaml")
@click.option("--output",  default=None, help="Path to save result JSON")
def route(skill, payload, config, output):
    """Route a task through Andromeda to the correct agent."""
    try:
        payload_dict = json.loads(payload)

        from boot import boot
        andromeda = boot()

        task = TaskContract(
            task_id=uuid4(),
            origin="cli",
            skill=skill,
            payload=payload_dict,
            confidence_threshold=0.65,
        )
        final_state = andromeda.route(task=task)

        print(f"task_id:        {final_state['task_id']}")
        print(f"assigned_agent: {final_state.get('assigned_agent')}")
        print(f"status:         {final_state.get('status')}")
        print(f"confidence:     {final_state.get('confidence')}")

        if output is not None:
            with open(output, "w") as f:
                json.dump(final_state, f, indent=2, default=str)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    galaxz()
