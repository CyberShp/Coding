"""CLI commands for batch test orchestration."""

import click
import json

from ...core.orchestrator import BatchOrchestrator, ScenarioResult
from ...utils.logging import get_logger

logger = get_logger("cli.batch")


@click.group("batch")
def batch_group():
    """Batch test orchestration commands."""
    pass


@batch_group.command("run")
@click.argument("batch_file", type=click.Path(exists=True))
@click.option("--stop-on-failure", is_flag=True, default=False,
              help="Stop batch if any scenario fails.")
@click.option("--delay", type=float, default=2.0,
              help="Delay between scenarios (seconds).")
@click.option("--export", "-o", type=click.Path(), default=None,
              help="Export results to JSON file.")
@click.pass_context
def batch_run(ctx, batch_file, stop_on_failure, delay, export):
    """Run a batch of test scenarios from a JSON file.

    BATCH_FILE should be a JSON file containing scenario definitions.

    Example batch file format:

    \b
    {
        "scenarios": [
            {
                "name": "iSCSI Login Fuzz",
                "config_overrides": {"protocol.type": "iscsi"},
                "anomalies": [{"type": "field_tamper", "enabled": true, ...}],
                "execution": {"repeat": 100, "interval_ms": 50}
            }
        ]
    }
    """
    config_path = ctx.obj.get("config_path")

    def on_progress(current: int, total: int, result: ScenarioResult) -> None:
        status_icon = "+" if result.status.value == "completed" else "x"
        click.echo(
            f"  [{status_icon}] {current}/{total} {result.name}: "
            f"{result.status.value} ({result.packets_sent} pkts, "
            f"{result.duration:.1f}s)"
        )

    def on_start(idx: int, name: str) -> None:
        click.echo(f"\n--- Scenario {idx + 1}: {name} ---")

    try:
        orchestrator = BatchOrchestrator(
            base_config_path=config_path,
            stop_on_failure=stop_on_failure,
            inter_scenario_delay=delay,
            on_progress=on_progress,
            on_scenario_start=on_start,
        )

        scenarios = orchestrator.load_batch_file(batch_file)
        click.echo(f"Loaded {len(scenarios)} scenarios from {batch_file}")

        result = orchestrator.run_batch(scenarios)

        # Print summary
        click.echo("\n=== Batch Summary ===")
        click.echo(f"  Total scenarios: {result.total_scenarios}")
        click.echo(f"  Completed:       {result.completed_count}")
        click.echo(f"  Failed:          {result.failed_count}")
        click.echo(f"  Skipped:         {result.skipped_count}")
        click.echo(f"  Total packets:   {result.total_packets}")
        click.echo(f"  Duration:        {result.duration:.1f}s")
        click.echo(f"  All passed:      {'Yes' if result.all_passed else 'No'}")

        if export:
            result.export_json(export)
            click.echo(f"\nResults exported to: {export}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        logger.error("Batch run failed: %s", e, exc_info=True)
        raise SystemExit(1)


@batch_group.command("validate")
@click.argument("batch_file", type=click.Path(exists=True))
def batch_validate(batch_file):
    """Validate a batch file without running it.

    Checks JSON syntax and scenario structure.
    """
    try:
        with open(batch_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            scenarios = data
        elif isinstance(data, dict):
            scenarios = data.get("scenarios", [data])
        else:
            click.echo("Error: Invalid batch file format", err=True)
            raise SystemExit(1)

        click.echo(f"Batch file: {batch_file}")
        click.echo(f"Scenarios:  {len(scenarios)}")

        for i, scenario in enumerate(scenarios, 1):
            name = scenario.get("name", f"Scenario {i}")
            has_overrides = bool(scenario.get("config_overrides"))
            has_anomalies = bool(scenario.get("anomalies"))
            has_execution = bool(scenario.get("execution"))
            click.echo(
                f"  {i}. {name} "
                f"[overrides={'Y' if has_overrides else 'N'}, "
                f"anomalies={'Y' if has_anomalies else 'N'}, "
                f"execution={'Y' if has_execution else 'N'}]"
            )

        click.echo("\nValidation passed.")

    except json.JSONDecodeError as e:
        click.echo(f"JSON syntax error: {e}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Validation error: {e}", err=True)
        raise SystemExit(1)


@batch_group.command("create-template")
@click.argument("output_file", type=click.Path())
def batch_template(output_file):
    """Create a template batch file.

    Generates a sample batch JSON file that can be customized.
    """
    template = {
        "batch_name": "Example Batch Test",
        "description": "Template batch file for packet storm testing",
        "scenarios": [
            {
                "name": "iSCSI Login Opcode Fuzz",
                "description": "Fuzz login request opcode field",
                "config_overrides": {
                    "protocol.type": "iscsi",
                    "network.dst_ip": "192.168.1.200",
                },
                "anomalies": [
                    {
                        "type": "field_tamper",
                        "enabled": True,
                        "target_layer": "iscsi",
                        "target_field": "opcode",
                        "mode": "random",
                        "count": 100,
                    }
                ],
                "execution": {
                    "repeat": 1,
                    "interval_ms": 50,
                },
            },
            {
                "name": "iSCSI Truncated PDU",
                "description": "Send truncated iSCSI packets",
                "config_overrides": {
                    "protocol.type": "iscsi",
                },
                "anomalies": [
                    {
                        "type": "truncation",
                        "enabled": True,
                        "mode": "random",
                        "count": 50,
                    }
                ],
                "execution": {
                    "repeat": 1,
                    "interval_ms": 100,
                },
            },
        ],
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)

    click.echo(f"Template batch file created: {output_file}")
