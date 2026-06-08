"""Run HYSPLIT dispersion for an EMR Camden fire.

Generates the CONTROL file, invokes `hycs_std` to run the dispersion model,
then invokes `con2asc` to convert the binary cdump output to a CSV-style
ASCII grid we can plot. Outputs land in tools/hysplit/output/fire_<date>/.

The fire is selected with --fire YYYY-MM-DD; ignition time comes from
data/fire_events.csv (ignition_local column) or a --start override. The
required HRRR met chunks (6-hour ARL files, ~3.4 GB each) are computed from
the simulation window and downloaded from the NOAA ARL archive if missing.

Prerequisites:
  - HYSPLIT installed (e.g., /Applications/hysplit/ with `exec/hycs_std`)

Run:
    python3 scripts/run_hysplit.py --fire 2026-03-10
    python3 scripts/run_hysplit.py --fire 2025-02-21
    python3 scripts/run_hysplit.py --fire 2026-05-29 --start 2026-05-29T04:00
    python3 scripts/run_hysplit.py --fire 2025-02-21 --skip-run   # CONTROL only
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import EMR_LAT, EMR_LON
from src.fires import (
    ARL_HRRR_BASE_URL,
    DEFAULT_RUN_HOURS,
    HYS_MET_DIR as MET_DIR,
    HYS_WORK_DIR as WORK_DIR,
    hysplit_fire_out_dir,
    ignition_utc,
    met_chunk_names,
)

EMIS_RATE_G_PER_HR = 1000.0   # Unit rate; we publish *relative* plume shape, not absolute conc
DEFAULT_EMIS_HOURS = 3.0      # Most-intense burn assumed to last ~3 hours

# Source-height sensitivity envelope, per Codex (no fake rigor — no weighting).
SOURCE_HEIGHTS_AGL = [10.0, 30.0, 100.0, 200.0]

# Output grid centered on EMR. 0.005° ≈ 500 m at this latitude.
GRID_SPACING_DEG = 0.005
GRID_SPAN_DEG = 0.30          # Half-extent each way → 33 km × 33 km covers full bbox + margin
SAMPLING_INTERVAL_MIN = 30    # Averaged (not snapshot) per Codex feedback


def write_control(path: Path, start_utc: datetime, run_hours: int,
                  emis_hours: float, met_files: list[str],
                  source_height_agl: float, out_dir: Path, cdump_name: str) -> None:
    yy, mm, dd, hh, mn = (start_utc.year % 100, start_utc.month, start_utc.day,
                          start_utc.hour, start_utc.minute)
    lines = [
        # Simulation start. HYSPLIT reads an optional 5th field (minutes); without
        # it the run silently starts on the hour, dropping up to 59 min for a
        # non-hour ignition (e.g. 1/29/21 09:30 UTC, 10/18/22 22:30 UTC).
        f"{yy:02d} {mm:02d} {dd:02d} {hh:02d} {mn:02d}",
        "1",
        f"{EMR_LAT:.6f} {EMR_LON:.6f} {source_height_agl:.1f}",
        f"{run_hours}",
        "0",                       # vertical motion: 0 = data
        "10000.0",                 # model top, m AGL
        f"{len(met_files)}",
    ]
    for mf in met_files:
        lines.append(f"{MET_DIR.as_posix()}/")
        lines.append(mf)
    # Pollutants
    lines += [
        "1",
        "PM25",
        f"{EMIS_RATE_G_PER_HR:.1f}",
        f"{emis_hours:.1f}",
        f"{yy:02d} {mm:02d} {dd:02d} {hh:02d} {mn:02d}",
    ]
    # Output grid
    lines += [
        "1",
        f"{EMR_LAT:.4f} {EMR_LON:.4f}",
        f"{GRID_SPACING_DEG} {GRID_SPACING_DEG}",
        f"{GRID_SPAN_DEG} {GRID_SPAN_DEG}",
        f"{out_dir.as_posix()}/",
        cdump_name,
        "1",                       # 1 vertical sampling layer
        "100",                     # vertical layer top: 0–100 m AGL averaged
    ]
    # Sampling start/stop and interval. Interval = "HH MM SS" — non-zero MM = averaged output.
    start_str = f"{yy:02d} {mm:02d} {dd:02d} {hh:02d} {mn:02d}"
    stop = start_utc + timedelta(hours=run_hours)
    stop_str = (f"{stop.year % 100:02d} {stop.month:02d} {stop.day:02d} "
                f"{stop.hour:02d} {stop.minute:02d}")
    lines += [start_str, stop_str]
    # CONTROL "SAMPLING INTERVAL" is actually "TYPE HOUR MINUTE":
    #   TYPE 0 = time-averaged, 1 = snapshot, 2 = maximum.
    # Per Codex feedback, use averaged output (not snapshot) for journalism integrity.
    interval_h = SAMPLING_INTERVAL_MIN // 60
    interval_m = SAMPLING_INTERVAL_MIN % 60
    lines.append(f"0 {interval_h} {interval_m}")
    # Deposition (one pollutant) — zeros = no deposition, plume stays airborne
    lines += [
        "1",
        "0.0 0.0 0.0",            # particle diameter, density, shape
        "0.0 0.0 0.0 0.0 0.0",    # dry dep velocity, mol wt, A, D, Henry's
        "0.0 0.0 0.0",            # wet dep
        "0.0",                    # radioactive decay half-life (days)
        "0.0",                    # resuspension factor
    ]
    path.write_text("\n".join(lines) + "\n")


def download_met(name: str) -> None:
    """Stream one HRRR ARL chunk (~3.4 GB) from the NOAA ARL archive."""
    import requests

    url = f"{ARL_HRRR_BASE_URL}/{name}"
    dest = MET_DIR / name
    tmp = MET_DIR / (name + ".part")
    print(f"  Downloading {url}")
    try:
        with requests.get(url, stream=True, timeout=120) as r:
            if r.status_code == 404:
                raise SystemExit(
                    f"Met chunk not in NOAA ARL archive: {url}\n"
                    "Check the date, or the archive may not retain this period."
                )
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            done = 0
            next_report = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if done >= next_report:
                        pct = f" ({100 * done / total:.0f}%)" if total else ""
                        print(f"    {done / 1e9:.2f} GB{pct}", flush=True)
                        next_report += 500_000_000
        # Guard against a truncated/early-EOF download poisoning the run: a
        # short met file fails cryptically deep inside hycs_std. Require the
        # byte count to match Content-Length before promoting the .part file.
        if total and done != total:
            raise SystemExit(
                f"Truncated download: got {done:,} of {total:,} bytes for {name}. "
                "Re-run to retry."
            )
        tmp.rename(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)   # don't leave a stale .part behind
        raise
    print(f"  -> {dest.relative_to(PROJECT_ROOT)} ({dest.stat().st_size:,} bytes)")


def find_hysplit(hint: str | None) -> Path:
    candidates = [hint] if hint else []
    candidates += [
        "/Applications/hysplit",
        os.path.expanduser("~/Applications/hysplit"),
        "/opt/hysplit",
        os.path.expanduser("~/hysplit"),
    ]
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if (p / "exec" / "hycs_std").exists():
            return p
    raise SystemExit(
        "Could not find HYSPLIT install. Looked in:\n  "
        + "\n  ".join(str(c) for c in candidates if c)
        + "\nPass --hysplit-dir /path/to/hysplit if installed elsewhere."
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fire", default="2026-03-10",
                    help="Fire date YYYY-MM-DD (must be in data/fire_events.csv)")
    ap.add_argument("--start",
                    help="Override ignition time, YYYY-MM-DDTHH:MM local ET "
                         "(for fires without ignition_local in the CSV)")
    ap.add_argument("--run-hours", type=int, default=DEFAULT_RUN_HOURS)
    ap.add_argument("--emis-hours", type=float, default=DEFAULT_EMIS_HOURS)
    ap.add_argument("--hysplit-dir")
    ap.add_argument("--no-download", action="store_true",
                    help="Fail instead of downloading missing met chunks")
    ap.add_argument("--skip-run", action="store_true",
                    help="Just write CONTROL, don't run hycs_std")
    args = ap.parse_args()

    start_utc = ignition_utc(args.fire, args.start)
    met_files = met_chunk_names(start_utc, args.run_hours)
    out_dir = hysplit_fire_out_dir(args.fire)

    print(f"Fire {args.fire}: ignition {start_utc:%Y-%m-%d %H:%M} UTC, "
          f"{args.run_hours} h run, emissions {args.emis_hours:.1f} h")
    print(f"Met chunks needed: {met_files}")

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    MET_DIR.mkdir(parents=True, exist_ok=True)

    missing = [m for m in met_files if not (MET_DIR / m).exists()]
    if missing and args.no_download:
        print(f"Missing meteorology files: {missing}")
        return 1
    for m in missing:
        download_met(m)

    if args.skip_run:
        # Write one example CONTROL for inspection
        ctl = WORK_DIR / "CONTROL"
        write_control(ctl, start_utc, args.run_hours, args.emis_hours,
                      met_files, SOURCE_HEIGHTS_AGL[0], out_dir, "cdump_example")
        print(f"Wrote {ctl.relative_to(PROJECT_ROOT)} (dry-run, only first height)")
        return 0

    hys = find_hysplit(args.hysplit_dir)
    hycs = hys / "exec" / "hycs_std"
    con2asc = hys / "exec" / "con2asc"
    par2asc = hys / "exec" / "par2asc"
    print(f"Using HYSPLIT: {hys}")

    for h in SOURCE_HEIGHTS_AGL:
        tag = f"h{int(h)}"
        cdump_name = f"cdump_{tag}"
        ctl = WORK_DIR / "CONTROL"
        write_control(ctl, start_utc, args.run_hours, args.emis_hours,
                      met_files, h, out_dir, cdump_name)
        print(f"\n=== Source height {h:.0f} m ===")

        # Run hycs_std — reads CONTROL from cwd.
        res = subprocess.run([str(hycs)], cwd=WORK_DIR)
        if res.returncode != 0:
            print(f"  hycs_std exited with {res.returncode}")
            return res.returncode

        cdump = out_dir / cdump_name
        if not cdump.exists():
            alt = WORK_DIR / cdump_name
            if alt.exists():
                alt.rename(cdump)
        if not cdump.exists():
            print(f"  No cdump produced for {tag}")
            return 1
        print(f"  -> {cdump.relative_to(PROJECT_ROOT)} ({cdump.stat().st_size:,} bytes)")

        # SETUP.CFG (NDUMP/NCYCL) makes each run drop a PARDUMP in the work dir.
        # Keep the 30 m one — it feeds the animation's particle layer.
        pardump = WORK_DIR / "PARDUMP"
        if int(h) == 30 and pardump.exists():
            shutil.copy2(pardump, out_dir / "PARDUMP_h30")
            if par2asc.exists():
                res = subprocess.run([str(par2asc), "-iPARDUMP", "-oPARDUMP.txt"],
                                     cwd=WORK_DIR)
                if res.returncode == 0 and (WORK_DIR / "PARDUMP.txt").exists():
                    shutil.copy2(WORK_DIR / "PARDUMP.txt", out_dir / "PARDUMP.txt")
                    print(f"  -> {(out_dir / 'PARDUMP.txt').relative_to(PROJECT_ROOT)}")
                else:
                    print("  par2asc failed — animation particle layer will be skipped")

        # Convert to ASCII. NO -s flag → averaged output (per Codex feedback).
        conc_out = out_dir / f"conc_{tag}"
        res = subprocess.run(
            [str(con2asc), f"-i{cdump}", f"-o{conc_out}", "-t", "-z1"],
            cwd=out_dir,
        )
        if res.returncode != 0:
            print(f"  con2asc exited with {res.returncode}")
            return res.returncode
        # con2asc writes one file per timestep at <output>_<JJJ>_<HHMM>
        produced = sorted(out_dir.glob(f"conc_{tag}*"))
        for p in produced:
            print(f"     {p.relative_to(PROJECT_ROOT)} ({p.stat().st_size:,} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
