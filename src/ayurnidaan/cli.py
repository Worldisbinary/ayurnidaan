"""Command-line entry point: ``ayur fetch | audit | run | serve | dashboard``."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer

from . import ingest, logging_utils, quality
from .config import get_settings, load_registry

app = typer.Typer(add_completion=False, help="Ayurnidaan analytics platform")


@app.callback()
def _main(log_level: str = typer.Option("INFO", help="DEBUG | INFO | WARNING")) -> None:
    logging_utils.configure(log_level)


@app.command()
def fetch(force: bool = typer.Option(False, help="Re-download even if cached")) -> None:
    """Download all registered Kaggle sources and verify their checksums."""
    s = get_settings()
    reg = load_registry(s.sources_file)
    ingest.fetch_all(reg, s.data_dir, force=force)
    for src in reg.sources.values():
        ingest.verify(src, s.data_dir)
    typer.echo(f"{len(reg.sources)} sources present and verified")


@app.command()
def audit() -> None:
    """Run the data-quality gate over every source and print the verdicts."""
    s = get_settings()
    reg = load_registry(s.sources_file)
    for src in reg.sources.values():
        rep = quality.audit(ingest.read_raw(ingest.verify(src, s.data_dir)), src, reg.quality_gate)
        failed = [c.check for c in rep.checks if c.blocking and not c.passed]
        verdict = "PASS" if rep.passed else f"FAIL ({', '.join(failed)})"
        typer.echo(f"{src.name:28} {src.role:15} {verdict}")


@app.command()
def run(fast: bool = typer.Option(False, help="Fewer bootstrap/CV repeats (smoke test)")) -> None:
    """Run the full pipeline and publish warehouse + artifacts."""
    from .pipeline import run as run_pipeline

    summary = run_pipeline(get_settings(), fast=fast)
    typer.echo(json.dumps(summary, indent=2))


@app.command()
def benchmark(n: int = typer.Option(500, help="Simulated patients per configuration")) -> None:
    """Simulated-patient benchmark with ablations; results are written into the pack manifest."""
    from .clinical import evaluation
    from .clinical.differential import DifferentialModel
    from .clinical.knowledge import KnowledgePack

    s = get_settings()
    pack = KnowledgePack.load(s.knowledge_dir)
    results = evaluation.run_ablations(DifferentialModel(pack), n=n, seed=0)
    manifest_path = s.knowledge_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["benchmark"] = {
        "n_per_config": n,
        "seed": 0,
        "note": "Simulated textbook presentations (2 volunteered symptoms + 30% noise, then 5 "
        "adaptive questions); measures internal consistency, not real-world accuracy.",
        "results": {
            k: {"volunteered_only": v["volunteered_only"], "after_interview": v["after_interview"]}
            for k, v in results.items()
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    for k, v in results.items():
        b, a = v["volunteered_only"], v["after_interview"]
        typer.echo(
            f"{k:16} top1 {b['top1']:.3f} -> {a['top1']:.3f} | top5 {b['top5']:.3f} -> {a['top5']:.3f}"
        )


@app.command("build-evidence")
def build_evidence(delay: float = typer.Option(0.25, help="Seconds between requests")) -> None:
    """Crawl Europe PMC for every condition (resumable); then re-run `ayur run`."""
    from . import evidence
    from .clinical.knowledge import KnowledgePack

    s = get_settings()
    pack = KnowledgePack.load(s.knowledge_dir)
    names = [evidence.query_name(c) for c in pack.conditions]
    cache = evidence.crawl(names, s.knowledge_dir / "evidence_cache.json", delay=delay)
    typer.echo(f"{len(cache)} diseases cached")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the REST API."""
    import uvicorn

    uvicorn.run("ayurnidaan.api:app", host=host, port=port)


@app.command("serve-app")
def serve_app(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Start the clinical API (patients / practitioners / admin)."""
    import uvicorn

    uvicorn.run("ayurnidaan.app.main:app", host=host, port=port, reload=reload)


@app.command()
def dashboard(
    port: int = 8501, open_browser: bool = typer.Option(True, help="Open a browser tab")
) -> None:
    """Start the clinician dashboard."""
    import time
    import webbrowser

    from .http import open_url

    script = Path(__file__).parent / "dashboard" / "app.py"
    # Headless skips Streamlit's first-run "Email:" prompt, which otherwise blocks
    # startup (or crashes it when stdin is not a terminal). We open the browser ourselves
    # once the server reports healthy.
    # Fixed argv, no shell, nothing user-controlled.
    proc = subprocess.Popen(  # nosec B603
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(script),
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ]
    )
    url = f"http://localhost:{port}"
    for _ in range(60):
        if proc.poll() is not None:
            raise typer.Exit(proc.returncode or 1)
        try:
            open_url(f"{url}/_stcore/health", timeout=1).close()
            break
        except OSError:
            time.sleep(0.5)
    typer.echo(f"Dashboard running at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()


if __name__ == "__main__":
    app()
