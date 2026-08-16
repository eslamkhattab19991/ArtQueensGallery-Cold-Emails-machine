"""Run the artist prospecting pipeline end to end.

One command instead of eleven scripts in a remembered order. The scripts under
``spikes/roster_probe/`` are the working system — they produced every lead the
gallery has — but running them by hand means knowing the sequence, and a wrong
order wastes money rather than merely failing.

    python run_pipeline.py --budget 300

What it does, in order. Steps marked (£) call Firecrawl and cost credits;
everything else reads files already on disk and is free.

    1. ingest            read the workbook into seeds.json
    2. map        (£)    list every page of each organization's website
    3. probe sample      pick 3 artists per organization to test
    4. probe      (£)    test them — do these artists publish their own address?
    5. evaluate          decide which organizations are worth pursuing
    6. expand            widen the rosters of those organizations
    ---- STOP: a human confirms which artists are women ----
    7. chain sample      queue the confirmed-female artists, within budget
    8. chain      (£)    trace each one to a personal email address
    9. sanitize          strip gallery, vendor and shared addresses
   10. export            write the two deliverable sheets
   11. audit             report per-gallery coverage honestly

Nothing is re-paid. Every artist and every site map is cached, so re-running
resumes rather than restarting, and a step whose work is already done says so
and moves on.

The stop before step 7 is deliberate, not an unfinished feature. See
``spikes/roster_probe/list_unclassified.py``.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
SPIKE = ROOT / "spikes" / "roster_probe"
OUT = SPIKE / "out"
DELIVERABLES = ROOT / "output"
WORKBOOK = ROOT / "Galleries sheet.xlsx"

#: npm ships a .cmd shim on Windows; CreateProcess will not find the bare name.
FIRECRAWL = "firecrawl.cmd" if sys.platform == "win32" else "firecrawl"

#: Measured across 962 traced artists: most cost one page read, and only those
#: with a site of their own go on to cost the map-and-scrape pair.
CREDITS_PER_ARTIST = 1.8


@dataclass(frozen=True)
class Step:
    """One stage of the pipeline."""

    name: str
    script: str
    args: tuple[str, ...] = ()
    costs_credits: bool = False


#: The CLI colours its output, so "Credits:" is followed by a reset sequence
#: rather than by a space. Matching the raw text silently found no balance and
#: reported a working CLI as missing, which sent the operator to reinstall Node.
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def credits_remaining() -> int | None:
    """Ask Firecrawl for the balance. None when the CLI cannot be reached."""
    try:
        result = subprocess.run(
            [FIRECRAWL, "--status"],
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"Credits:\s*([\d,]+)", ANSI.sub("", result.stdout or ""))
    return int(match.group(1).replace(",", "")) if match else None


def preflight(budget: int) -> None:
    """Stop before spending anything if the run cannot possibly succeed."""
    problems: list[str] = []

    if not WORKBOOK.is_file() and not (OUT / "seeds.json").is_file():
        problems.append(
            f"The workbook is missing. Put your spreadsheet here:\n"
            f"     {WORKBOOK}\n"
            f"     It needs a sheet named 'Collected Accounts' with the organisation\n"
            f"     name, website and Instagram columns."
        )

    balance = credits_remaining()
    if balance is None:
        problems.append(
            f"The Firecrawl CLI ({FIRECRAWL}) is not installed, not on PATH, or not\n"
            f"     signed in. It needs Node.js:\n"
            f"       npm install -g firecrawl\n"
            f"       firecrawl config"
        )
    elif budget > balance:
        problems.append(
            f"Budget is {budget} credits but only {balance} remain.\n"
            f"     Lower --budget, or top up the Firecrawl account."
        )

    if problems:
        lines = "\n\n".join(f"  {index}. {p}" for index, p in enumerate(problems, 1))
        raise SystemExit(f"\nCannot start:\n\n{lines}\n")

    print(f"Firecrawl: signed in, {balance:,} credits available.")
    print(f"Budget for this run: {budget} credits (~{int(budget / CREDITS_PER_ARTIST)} artists).\n")


def run(step: Step) -> None:
    """Run one step, stopping the pipeline if it fails."""
    print(f"\n{'=' * 72}\n  {step.name}\n{'=' * 72}", flush=True)
    result = subprocess.run(
        [sys.executable, str(SPIKE / step.script), *step.args], cwd=SPIKE, check=False
    )
    if result.returncode != 0:
        raise SystemExit(
            f"\n!! Step '{step.name}' failed (exit {result.returncode}).\n"
            f"   Nothing is lost — every completed artist is cached in\n"
            f"   {OUT / 'chain'}, so re-running resumes and costs no credits for work\n"
            f"   already done."
        )


def gender_gate() -> None:
    """Halt until a human has confirmed which discovered artists are women.

    The pipeline could technically continue without this, and that is exactly
    the failure worth preventing: the export would either refuse to run or, in an
    earlier version, ship male artists to the operator. Stopping here with a
    readable instruction is the honest behaviour.
    """
    gate = OUT / "female_artists.json"
    print(f"\n{'=' * 72}\n  Confirm which artists are women\n{'=' * 72}")
    subprocess.run([sys.executable, str(SPIKE / "list_unclassified.py")], cwd=SPIKE, check=False)

    pending = _count_pending()
    if pending == 0:
        print("\nEvery discovered artist is already classified. Continuing.")
        return

    raise SystemExit(
        f"\n{'-' * 72}\n"
        f"STOPPED — {pending} artists need a female / not-female decision.\n\n"
        f"  This is a human judgement the machine deliberately does not make.\n"
        f"  Add the names you can confirm are women to:\n"
        f"    {gate}\n\n"
        f'  Working in Claude Code? Just say: "classify the pending artist names".\n\n'
        f"  Then run this command again — it will resume from here and re-pay for\n"
        f"  nothing.\n{'-' * 72}"
    )


def _count_pending() -> int:
    """How many discovered artists still lack a gender decision."""
    result = subprocess.run(
        [sys.executable, str(SPIKE / "list_unclassified.py")],
        cwd=SPIKE,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    match = re.search(r"awaiting a decision\s*:\s*(\d+)", result.stdout or "")
    return int(match.group(1)) if match else 0


def publish() -> None:
    """Copy the two deliverables where the operator can find them."""
    DELIVERABLES.mkdir(exist_ok=True)
    for name in ("completed_leads.csv", "enrichment_not_a_must.csv", "coverage_report.csv"):
        source = OUT / name
        if source.is_file():
            shutil.copyfile(source, DELIVERABLES / name)
            print(f"  {DELIVERABLES / name}")


def summarise() -> None:
    """Report the one number the project is judged on."""
    leads = OUT / "completed_leads.csv"
    if not leads.is_file():
        return
    rows = leads.read_text(encoding="utf-8-sig").splitlines()
    print(f"\n  COMPLETED LEADS: {max(len(rows) - 1, 0)}")


def main() -> None:
    """Run every step in order, resuming wherever previous work left off."""
    parser = argparse.ArgumentParser(
        description="Find female artists with contactable email addresses.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:  python run_pipeline.py --budget 300",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=200,
        help="maximum Firecrawl credits to spend on tracing artists (default: 200)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show the plan and spend nothing",
    )
    args = parser.parse_args()

    print("Art Queens Gallery — artist prospecting\n")

    before = [
        Step("1/11  Read the workbook", "ingest.py"),
        Step("2/11  Map every organization's website", "map_sites.py", costs_credits=True),
        Step("3/11  Choose artists to test", "build_probe_sample.py"),
        Step("4/11  Test them", "chain.py", costs_credits=True),
        Step("5/11  Decide which organizations are worth pursuing", "evaluate_probe.py"),
        Step("6/11  Widen the rosters of those organizations", "expand_rosters.py"),
    ]
    after = [
        Step(
            "7/11  Queue confirmed-female artists",
            "build_chain_sample.py",
            ("--budget", str(args.budget)),
        ),
        Step("8/11  Trace each one to a personal email", "chain.py", costs_credits=True),
        Step("9/11  Strip gallery, vendor and shared addresses", "sanitize.py"),
        Step("10/11 Write the deliverable sheets", "build_final_export.py"),
        Step("11/11 Audit per-gallery coverage", "coverage_audit.py"),
    ]

    if args.dry_run:
        print("Planned steps (£ = spends credits):\n")
        for step in [*before, Step("---   STOP: confirm which artists are women", ""), *after]:
            marker = " £" if step.costs_credits else "  "
            print(f"  {marker} {step.name}")
        print(f"\nBudget would be {args.budget} credits. Nothing was run.")
        return

    preflight(args.budget)
    for step in before:
        run(step)
    gender_gate()
    for step in after:
        run(step)

    print(f"\n{'=' * 72}\n  Done\n{'=' * 72}")
    summarise()
    print("\n  Files written:")
    publish()
    remaining = credits_remaining()
    if remaining is not None:
        print(f"\n  Credits remaining: {remaining:,}")


if __name__ == "__main__":
    main()
