"""
================================================================================
MedLearn AI - Corpus Ingestion: Orchestrator
================================================================================
Runs all three ingestion fetchers (MedlinePlus, PubMed, MyHealthfinder) in
sequence, with per-source error isolation - one source failing (bad
network, API change, rate limit) does NOT stop the others from running,
and the run ends with a clear summary of what actually happened, not just
whatever got logged along the way.

This exists because none of the three fetchers have been run end-to-end
against live data in the sandbox this project was built in (see each
fetcher's own module docstring for why - a fetch-tool restriction and,
for MedlinePlus, a domain not on the sandbox's network allowlist). This
script is the thing to actually run in a real environment to find out
whether they work - it does not itself change that verification status
for the individual fetchers, it just makes running all three, and seeing
clearly which ones succeeded, a one-command operation instead of three
separate manual runs.

Usage:
    python ingest_all.py                    # run all three with each one's default seed list
    python ingest_all.py --only medlineplus  # run just one source
    python ingest_all.py --only pubmed,myhealthfinder

Exit code is 0 only if every attempted source completed without raising -
a source logging zero chunks stored (e.g. all its API calls failed) still
counts as "ran without raising" here, since that's the individual
fetcher's own error handling already having done its job; this script's
job is orchestration and reporting, not re-implementing each fetcher's
retry/error logic.
"""

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field

logger = logging.getLogger("medlearn.ingest.all")
logging.basicConfig(level=logging.INFO)


@dataclass
class SourceResult:
    name: str
    succeeded: bool
    duration_seconds: float
    error: str | None = None


@dataclass
class RunSummary:
    results: list[SourceResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return all(r.succeeded for r in self.results)

    def report(self) -> str:
        lines = ["", "=" * 60, "INGESTION RUN SUMMARY", "=" * 60]
        for r in self.results:
            status = "OK" if r.succeeded else "FAILED"
            lines.append(f"  [{status}] {r.name} ({r.duration_seconds:.1f}s)")
            if r.error:
                lines.append(f"           {r.error}")
        lines.append("=" * 60)
        return "\n".join(lines)


# Each entry: (name, module path, callable that returns the module's main
# function and default seed list). Imports are deferred into the runner
# function below rather than done at module load time, so that one
# source's import failing (e.g. a missing dependency specific to that
# fetcher) doesn't prevent the other two from being attempted at all.
SOURCES = ["medlineplus", "pubmed", "myhealthfinder"]


def _run_medlineplus() -> None:
    import ingest_medlineplus
    ingest_medlineplus.main(ingest_medlineplus.DEFAULT_SEED_TOPICS)


def _run_pubmed() -> None:
    import ingest_pubmed
    ingest_pubmed.main(ingest_pubmed.DEFAULT_SEED_TOPICS)


def _run_myhealthfinder() -> None:
    import ingest_myhealthfinder
    ingest_myhealthfinder.main(ingest_myhealthfinder.DEFAULT_SEED_KEYWORDS)


_RUNNERS = {
    "medlineplus": _run_medlineplus,
    "pubmed": _run_pubmed,
    "myhealthfinder": _run_myhealthfinder,
}


def run_sources(names: list[str]) -> RunSummary:
    summary = RunSummary()

    for name in names:
        if name not in _RUNNERS:
            logger.error("Unknown source '%s' - skipping. Known sources: %s", name, ", ".join(_RUNNERS))
            summary.results.append(SourceResult(name=name, succeeded=False, duration_seconds=0.0, error="unknown source name"))
            continue

        logger.info("--- Starting %s ---", name)
        start = time.time()
        try:
            _RUNNERS[name]()
            duration = time.time() - start
            summary.results.append(SourceResult(name=name, succeeded=True, duration_seconds=duration))
            logger.info("--- Finished %s (%.1fs) ---", name, duration)
        except SystemExit:
            # A fetcher's main() calls sys.exit(1) when OPENAI_API_KEY is
            # missing - that's a fatal, shared precondition for every
            # source, not a per-source failure worth continuing past.
            # Re-raise rather than swallow it as "one source failed."
            logger.error("Fatal: %s exited (likely missing OPENAI_API_KEY) - stopping the whole run.", name)
            raise
        except Exception as e:  # noqa: BLE001 - any other failure is isolated to this source
            duration = time.time() - start
            summary.results.append(SourceResult(name=name, succeeded=False, duration_seconds=duration, error=str(e)))
            logger.error("--- %s failed after %.1fs: %s ---", name, duration, e)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all MedLearn AI corpus ingestion sources.")
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help=f"Comma-separated subset of sources to run (default: all). Choices: {', '.join(_RUNNERS)}",
    )
    args = parser.parse_args()

    if args.only:
        names = [n.strip() for n in args.only.split(",") if n.strip()]
    else:
        names = list(SOURCES)

    summary = run_sources(names)
    print(summary.report())

    sys.exit(0 if summary.all_succeeded else 1)


if __name__ == "__main__":
    main()
