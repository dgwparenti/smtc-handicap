#!/usr/bin/env python3
"""Incrementally ingest new practice time sheets and refit the Bayesian model."""

import argparse
import logging
import time
from pathlib import Path

from smtc_handicap.model import run_model
from smtc_handicap.model.data_prep import build_stan_data
from smtc_handicap.pipeline import ingest_new_practice

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def print_ingest_summary(stats):
    print("\n" + "=" * 50)
    print("Ingestion Summary")
    print("=" * 50)
    if stats.jsons_processed or stats.jsons_failed:
        print(f"  JSONs processed:     {stats.jsons_processed}")
        print(f"  JSONs failed:        {stats.jsons_failed}")
    print(f"  PDFs processed:      {stats.pdfs_processed}")
    print(f"  PDFs failed:         {stats.pdfs_failed}")
    print(f"  Races inserted:      {stats.races_inserted}")
    print(f"  Riders upserted:     {stats.riders_upserted}")
    print(f"  Time records:        {stats.time_records_inserted}")
    print(f"  Warnings:            {len(stats.warnings)}")

    if stats.warnings:
        print("\nWarnings:")
        for w in stats.warnings[:20]:
            print(f"  - {w}")
        if len(stats.warnings) > 20:
            print(f"  ... and {len(stats.warnings) - 20} more")


def fit_position(position, args):
    print("\n" + "=" * 60)
    print(f"CRESTA RUN HANDICAP MODEL — {position}")
    print("=" * 60)

    stan_data = build_stan_data(args.db, position)
    print(f"\nData summary:")
    print(f"  Observations (N): {stan_data['N']:,}")
    print(f"  Riders (J):       {stan_data['J']:,}")
    print(f"  Seasons (S):      {stan_data['S']}")
    print(f"  Race types (R):   {stan_data['R']}")
    season_map = stan_data["meta_season_map"]
    seasons = sorted(season_map.keys())
    print(f"  Seasons:          {seasons[0]}–{seasons[-1]}")
    print(f"\nMCMC settings:")
    print(f"  Chains:           {args.chains}")
    print(f"  Warmup:           {args.iter_warmup}")
    print(f"  Sampling:         {args.iter_sampling}")
    print()

    t0 = time.time()
    result = run_model(
        args.db,
        position,
        chains=args.chains,
        iter_warmup=args.iter_warmup,
        iter_sampling=args.iter_sampling,
        output_dir=args.output_dir,
    )
    elapsed = time.time() - t0

    diag = result["diagnostics"]
    print("\n" + "=" * 60)
    print("CONVERGENCE DIAGNOSTICS")
    print("=" * 60)
    print(f"\n{diag['summary'].to_string()}")

    print(f"\n{'Check':<25s} {'Value':>10s}   {'Status'}")
    print("-" * 50)

    rhat_status = "PASS" if diag["rhat_ok"] else "FAIL"
    print(f"{'Max R-hat < 1.01':<25s} {diag['max_rhat']:>10.4f}   {rhat_status}")

    ess_status = "PASS" if diag["ess_ok"] else "FAIL"
    print(f"{'Min ESS bulk > 400':<25s} {diag['min_ess_bulk']:>10.0f}   {ess_status}")

    div_status = "PASS" if diag["divergences"] == 0 else "FAIL"
    print(f"{'Divergences == 0':<25s} {diag['divergences']:>10d}   {div_status}")

    print("-" * 50)
    overall = "ALL PASSED" if diag["passed"] else "SOME CHECKS FAILED"
    print(f"Overall: {overall}")

    nc_path = args.output_dir / f"{position.lower()}.nc"
    print(f"\nInferenceData saved to: {nc_path}")
    print(f"Fitting time: {elapsed:.0f}s ({elapsed / 60:.1f} min)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest new practice time sheets and refit the Bayesian model"
    )
    parser.add_argument(
        "--position",
        type=str,
        choices=["TOP", "JUNCTION", "BOTH"],
        default="BOTH",
        help="Start position(s) to refit (default: BOTH)",
    )
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw_pdfs",
        help="Directory containing PDF files",
    )
    parser.add_argument(
        "--json-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "json_results",
        help="Directory containing JSON files",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=PROJECT_ROOT / "data" / "cresta.db",
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "model_fits",
        help="Directory for saving InferenceData (.nc)",
    )
    parser.add_argument("--chains", type=int, default=4, help="Number of MCMC chains")
    parser.add_argument(
        "--iter-warmup", type=int, default=1000, help="Warmup iterations per chain"
    )
    parser.add_argument(
        "--iter-sampling", type=int, default=2000, help="Sampling iterations per chain"
    )
    parser.add_argument(
        "--ingest-only",
        action="store_true",
        help="Only ingest new practice files, skip model refit",
    )
    parser.add_argument(
        "--refit-only",
        action="store_true",
        help="Skip ingestion, only refit the model",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be ingested without actually doing it",
    )
    parser.add_argument(
        "--skip-refit-if-no-new",
        action="store_true",
        help="Skip model refit if no new files were ingested",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.ingest_only and args.refit_only:
        parser.error("Cannot use --ingest-only and --refit-only together")

    # Phase 1: Ingest new practice files
    new_data_found = False
    if not args.refit_only:
        stats = ingest_new_practice(args.json_dir, args.pdf_dir, args.db, dry_run=args.dry_run)
        print_ingest_summary(stats)
        new_data_found = (stats.pdfs_processed + stats.jsons_processed) > 0

    if args.ingest_only or args.dry_run:
        return

    # Phase 2: Refit the model
    if args.skip_refit_if_no_new and not new_data_found:
        print("\nNo new data ingested — skipping model refit.")
        return

    positions = ["TOP", "JUNCTION"] if args.position == "BOTH" else [args.position]
    for position in positions:
        fit_position(position, args)


if __name__ == "__main__":
    main()
