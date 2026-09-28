"""Build a static local dashboard from selected, sanitized result summaries."""

import html
import json
import re
from pathlib import Path

SOURCE_RUN = re.compile(r"https://github\.com/[^/]+/[^/]+/actions/runs/[0-9]+\Z")


def selected_records(directory: Path) -> list[dict]:
    files = sorted(directory.glob("*.json"))
    if len(files) > 100:
        raise ValueError("Too many selected result files")
    records = []
    for path in files:
        if path.stat().st_size > 1_000_000:
            raise ValueError("Selected result file is too large")
        record = json.loads(path.read_text(encoding="utf-8"))
        if type(record) is not dict or type(record.get("execution_mode")) is not str:
            raise ValueError("Selected result lacks an execution mode")
        if type(record.get("benchmark_eligible")) is not bool:
            raise ValueError("Selected result lacks a benchmark eligibility flag")
        records.append({"file": path.name, "data": record})
    return records


def _ratio(stage: dict) -> str:
    if type(stage) is not dict:
        return "—"
    successes, requests = stage.get("successes"), stage.get("requests")
    if type(successes) is not int or type(requests) is not int:
        return "—"
    return f"{successes}/{requests}"


def _row(entry: dict) -> str:
    record = entry["data"]
    mode = record["execution_mode"]
    if mode == "fixture":
        healthy = _ratio(record.get("healthy"))
        fault = _ratio(record.get("fault"))
        recovered = _ratio(record.get("recovered"))
        outcome = "Scripted fixture recovery"
    elif mode == "github_actions_kind":
        healthy = _ratio(record.get("healthy_setup"))
        fault = _ratio(record.get("injected_fault"))
        recovered = _ratio(record.get("recovery_smoke"))
        outcome = record.get("runbook", {}).get("decision", "Unreported")
    elif mode == "github_actions_kind_evaluator":
        cases = record.get("cases", [])
        healthy_case = next((case for case in cases if case.get("scenario") == "healthy"), {})
        failed_case = next((case for case in cases if case.get("passed") is False), {})
        healthy = _ratio(healthy_case.get("independent_check", {}))
        fault = _ratio(failed_case.get("independent_check", {}))
        recovered = "—"
        outcome = f"{record.get('passed_attempts', 0)}/{record.get('attempts', 0)} attempts passed"
    else:
        healthy = fault = recovered = "—"
        outcome = "See selected record"
    source = record.get("source_run", "")
    if type(source) is str and SOURCE_RUN.fullmatch(source):
        source_cell = f'<a href="{html.escape(source, quote=True)}">CI run</a>'
    else:
        source_cell = "Local selected record"
    values = (
        entry["file"],
        mode,
        record.get("scenario", "—"),
        healthy,
        fault,
        recovered,
        outcome,
        "Yes" if record["benchmark_eligible"] else "No",
    )
    cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in values)
    return f"<tr>{cells}<td>{source_cell}</td></tr>"


def render(records: list[dict]) -> str:
    live = sum(
        entry["data"]["execution_mode"].startswith("github_actions_kind") for entry in records
    )
    fixture = sum(entry["data"]["execution_mode"] == "fixture" for entry in records)
    eligible = sum(entry["data"]["benchmark_eligible"] for entry in records)
    rows = "\n".join(_row(entry) for entry in records)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RackOps selected results</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, sans-serif; }}
    body {{ max-width: 1100px; margin: 0 auto; padding: 2rem;
      background: #f5f7f8; color: #17202a; }}
    h1 {{ margin-bottom: .3rem; }}
    .notice {{ padding: 1rem; background: #fff4d6; border-left: 5px solid #a36b00; }}
    .cards {{ display: flex; flex-wrap: wrap; gap: 1rem; margin: 1.5rem 0; }}
    .card {{ background: white; padding: 1rem; min-width: 140px; border: 1px solid #dce3e8; }}
    .card strong {{ display: block; font-size: 2rem; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ border-collapse: collapse; width: 100%; background: white; }}
    th, td {{ padding: .65rem; text-align: left; border-bottom: 1px solid #dce3e8; }}
    th {{ background: #e7eef2; }}
    tr:hover {{ background: #f2f8fb; }}
    a {{ color: #005a9c; }}
  </style>
</head>
<body>
  <h1>RackOps selected results</h1>
  <p class="notice">Development evidence only. This page replays selected records;
    opening it does not run a lab or an agent. Fixture data and live kind checks
    are labeled separately. No LLM comparison or held-out benchmark is reported.</p>
  <div class="cards">
    <div class="card"><strong>{len(records)}</strong>selected records</div>
    <div class="card"><strong>{live}</strong>live kind records</div>
    <div class="card"><strong>{fixture}</strong>fixture records</div>
    <div class="card"><strong>{eligible}</strong>benchmark-eligible records</div>
  </div>
  <div class="table-wrap"><table>
    <thead><tr><th>Record</th><th>Mode</th><th>Scenario</th><th>Healthy</th>
    <th>Fault</th><th>Recovery</th><th>Outcome</th><th>Benchmark eligible</th>
    <th>Source</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <p>Counts are request checks from selected summaries. A single smoke run is
    not a recovery-rate estimate.</p>
</body>
</html>
"""


def generate(directory: Path, output: Path) -> dict:
    records = selected_records(directory)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(records), encoding="utf-8")
    return {"output": str(output), "selected_records": len(records), "execution_mode": "replay"}
