#!/usr/bin/env python3
"""
Generate beli51 images using Nano Banana Pro with Orange UI combo references.

Usage (example):
  set -a; source /Users/adil/Docs/Oracle/Content/.env; set +a
  python3 /Users/adil/Docs/Oracle/Content/scripts/generate_beli51_images.py

Notes:
- Skips any output files that already exist (safe to resume).
- Uses 2K resolution and all 4 combo reference images per prompt.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import time
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PROMPT_BASE = Path("/Users/adil/Docs/Oracle/Content/Prompt_book/beli51/distilled")
COMBO_BASE = Path("/Users/adil/Docs/Oracle/Content/Input_images/Combos/beli51")
ASSET_BASE = Path("/Users/adil/Docs/Business2/Content/Content_db_1")
OUTPUT_BASE = Path(
    "/Users/adil/Docs/Business2/Content/Content_db_1/Kevin/beli51/Result_images"
)
LOG_DIR = Path("/Users/adil/Docs/Oracle/Content/docs/generation_logs")
MODEL_NAME = "beli51"
TZ = ZoneInfo("Asia/Almaty")


CATALOGS = [
    ("v2.2", ["LS01", "LS02", "LS03", "LS04", "LS05", "ZH01", "ZH02", "TS01", "BF01", "PO01"]),
    ("v3.2", ["LS01", "LS02", "LS03", "LS04", "LS05", "LS06", "LS07", "LS08", "LS09", "ZH01", "ZH02", "ZH03", "ZH04", "BF01", "PO01"]),
    # v4.2: exclude ZH prompts per instruction
    ("v4.2", ["LS01", "LS02", "LS03", "LS04", "LS05", "LS06", "LS07", "LS08", "BF01", "PO01", "ICONS01"]),
    ("v5.6", ["LS01", "LS02", "LS03", "LS04", "LS05", "LS06", "LS07", "ZH01", "ZH02", "TS01", "PO01", "FLAT01", "FLAT02", "FLAT03", "FLAT04"]),
]


PREFIX_TO_WARDROBE = {
    "LS": "longsleeve",
    "ZH": "zip-hoodie",
    "TS": "t-shirt",
    "BF": "bottom-fit",
    "PO": "product-only",
    "FLAT": "flat-lay",
    "ICONS": "icons",
}


PREFIX_TO_COMBO_DIR = {
    "LS": COMBO_BASE / "longsleeve" / "Orange_UI_Combos",
    "ZH": COMBO_BASE / "zip-hoodie" / "Orange_UI_Combos",
    "TS": COMBO_BASE / "t-shirt" / "Orange_UI_Combos",
    "BF": COMBO_BASE / "zip-hoodie" / "Orange_UI_Combos",
    "PO": COMBO_BASE / "zip-hoodie" / "Orange_UI_Combos",
    "FLAT": COMBO_BASE / "zip-hoodie" / "Orange_UI_Combos",
    "ICONS": COMBO_BASE / "zip-hoodie" / "Orange_UI_Combos",
}


def load_env_file(path: Path) -> None:
    """Load key=value pairs from a .env file into os.environ if not already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def find_prompt_file(catalog: str, prompt_id: str) -> Path:
    catalog_dir = PROMPT_BASE / f"catalog_{catalog}"
    for p in catalog_dir.glob(f"{prompt_id}*.md"):
        return p
    raise FileNotFoundError(f"Prompt file not found for {catalog} {prompt_id}")


def read_combo_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        data[key.strip()] = val.strip().strip('"').strip("'")
    return data


def run_cmd(cmd: list[str], timeout_s: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=124, stdout="", stderr=f"TIMEOUT after {timeout_s}s"
        )


def format_ts(ts: datetime | None) -> str:
    if ts is None:
        return "-"
    return ts.strftime("%Y-%m-%d %H:%M:%S%z")


def is_503_error(msg: str) -> bool:
    if not msg:
        return False
    return (
        "503" in msg
        or "UNAVAILABLE" in msg
        or "Deadline expired" in msg
        or "overloaded" in msg.lower()
    )


def write_progress_log(
    progress_path: Path,
    tasks: list[tuple[str, str, str, str, Path, Path, str, str, list[Path]]],
    run_start: datetime,
    pass_num: int,
    max_passes: int,
    end_time: datetime | None = None,
) -> None:
    total = len(tasks)
    ok_total = sum(1 for t in tasks if t[5].exists())
    pct_total = (ok_total / total * 100.0) if total else 0.0
    now = datetime.now(TZ)
    elapsed_min = (now - run_start).total_seconds() / 60.0

    def green(text: str) -> str:
        return f"\x1b[32m{text}\x1b[0m"

    totals: dict[tuple[str, str, str], int] = defaultdict(int)
    oks: dict[tuple[str, str, str], int] = defaultdict(int)
    for catalog, prompt_id, combo_id, prompt_text, combo_file, out_file, wardrobe, combo_specs, input_paths in tasks:
        key = (MODEL_NAME, wardrobe, catalog)
        totals[key] += 1
        if out_file.exists():
            oks[key] += 1

    header = (
        f"Progress: {ok_total}/{total} ({pct_total:.2f}%) | "
        f"start: {format_ts(run_start)} | "
        f"elapsed_min: {elapsed_min:.2f} | "
        f"pass: {pass_num}/{max_passes} | "
        f"end: {format_ts(end_time)}\n"
    )
    table_header = (
        "model  | wardrobe   | catalog | ok/total     | pct_group | pct_total\n"
    )
    separator = "-------|------------|---------|--------------|-----------|----------\n"

    rows = []
    for key in sorted(totals.keys(), key=lambda k: (k[1], k[2])):
        model, wardrobe, catalog = key
        ok = oks.get(key, 0)
        total_k = totals[key]
        pct_group = (ok / total_k * 100.0) if total_k else 0.0
        pct_of_total = (ok / total * 100.0) if total else 0.0
        ok_total_str = f"{green(str(ok))}/{total_k}"
        rows.append(
            f"{model:6} | {wardrobe:10} | {catalog:7} | {ok_total_str:12} | {pct_group:9.2f} | {pct_of_total:8.2f}\n"
        )

    with progress_path.open("w") as prog:
        prog.write(header)
        prog.write(table_header)
        prog.write(separator)
        for row in rows:
            prog.write(row)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate beli51 images using Nano Banana Pro with Orange UI combos."
    )
    parser.add_argument(
        "--catalog",
        action="append",
        help="Optional catalog(s) to run, e.g. --catalog v2.2 (can repeat).",
    )
    parser.add_argument(
        "--env-file",
        default="/Users/adil/Docs/Oracle/Content/.env",
        help="Path to .env file with GEMINI_API_KEY.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Max attempts per image before marking ERROR.",
    )
    parser.add_argument(
        "--retry-delay",
        type=int,
        default=10,
        help="Seconds to wait between retries.",
    )
    parser.add_argument(
        "--max-retry-delay",
        type=int,
        default=120,
        help="Max backoff delay in seconds between retries.",
    )
    parser.add_argument(
        "--retry-delay-503",
        type=int,
        default=60,
        help="Base delay in seconds when API returns 503/UNAVAILABLE.",
    )
    parser.add_argument(
        "--max-503-attempts",
        type=int,
        default=1,
        help="Max attempts per image when 503/UNAVAILABLE is detected (defer after).",
    )
    parser.add_argument(
        "--cooldown-after-503s",
        type=int,
        default=5,
        help="Consecutive 503s before a cooldown sleep.",
    )
    parser.add_argument(
        "--cooldown-on-503",
        type=int,
        default=300,
        help="Cooldown seconds after many consecutive 503s.",
    )
    parser.add_argument(
        "--per-image-timeout",
        type=int,
        default=900,
        help="Timeout in seconds for a single image generation call.",
    )
    parser.add_argument(
        "--inter-image-delay",
        type=int,
        default=3,
        help="Seconds to wait between images to reduce rate spikes.",
    )
    parser.add_argument(
        "--max-passes",
        type=int,
        default=50,
        help="Max passes to re-queue missing outputs for guaranteed quantity.",
    )
    args = parser.parse_args()

    load_env_file(Path(args.env_file))
    if "GEMINI_API_KEY" not in os.environ:
        raise RuntimeError("GEMINI_API_KEY is not set. Source your .env first.")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now_local = datetime.now(TZ)
    log_path = LOG_DIR / f"full_run_{now_local.strftime('%Y-%m-%d_%H-%M-%S%z')}_almaty.log"
    md_log_path = log_path.with_suffix(".md")
    progress_log_path = LOG_DIR / f"progress_{now_local.strftime('%Y-%m-%d_%H-%M-%S%z')}_almaty.log"

    selected_catalogs = CATALOGS
    if args.catalog:
        selected = set(args.catalog)
        selected_catalogs = [c for c in CATALOGS if c[0] in selected]
        if not selected_catalogs:
            raise ValueError(f"No matching catalogs found for {args.catalog}")

    header = (
        "  # | start_ts           | end_ts             | duration_min | status   | model  | wardrobe   | catalog | prompt | combo   | combo_specs           | relative_path\n"
    )
    separator = (
        "----|--------------------|--------------------|--------------|----------|--------|------------|---------|--------|---------|-----------------------|------------------------------\n"
    )

    with log_path.open("w") as log:
        log.write(f"Run started (Asia/Almaty): {now_local.strftime('%Y-%m-%d %H:%M:%S%z')}\n")
        log.write(header)
        log.write(separator)

    with md_log_path.open("w") as mdlog:
        mdlog.write(f"Run started (Asia/Almaty): {now_local.strftime('%Y-%m-%d %H:%M:%S%z')}\n")
        mdlog.write("```text\n")
        mdlog.write(header)
        mdlog.write(separator)

    print(f"Logging to: {log_path}")

    tasks: list[tuple[str, str, str, str, Path, Path, str, str, list[Path]]] = []
    for catalog, prompts in selected_catalogs:
        for prompt_id in prompts:
            prefix_match = re.match(r"^[A-Z]+", prompt_id)
            if not prefix_match:
                raise ValueError(f"Bad prompt id: {prompt_id}")
            prefix = prefix_match.group(0)
            wardrobe = PREFIX_TO_WARDROBE[prefix]
            combo_dir = PREFIX_TO_COMBO_DIR[prefix]
            prompt_file = find_prompt_file(catalog, prompt_id)
            prompt_text = prompt_file.read_text()
            combo_files = sorted(combo_dir.glob("C-U-*.env"))
            if not combo_files:
                raise FileNotFoundError(f"No combo env files in {combo_dir}")
            for combo_file in combo_files:
                combo_id = combo_file.stem
                out_dir = OUTPUT_BASE / wardrobe / catalog / prompt_id / combo_id
                out_file = out_dir / f"{catalog}_{prompt_id}_{combo_id}.png"
                env = read_combo_env(combo_file)
                key_order = ["WARDROBE", "BOTTOM", "POSE", "UI"]
                present_keys = [k for k in key_order if k in env]
                if not present_keys:
                    raise KeyError(f"No reference keys found in {combo_file}")
                input_paths = [ASSET_BASE / env[k] for k in present_keys]
                for p in input_paths:
                    if not p.exists():
                        raise FileNotFoundError(f"Missing input image: {p}")
                combo_specs = ",".join(present_keys)
                tasks.append(
                    (
                        catalog,
                        prompt_id,
                        combo_id,
                        prompt_text,
                        combo_file,
                        out_file,
                        wardrobe,
                        combo_specs,
                        input_paths,
                    )
                )

    print(f"Total images queued: {len(tasks)}")
    run_start = now_local
    write_progress_log(
        progress_log_path,
        tasks,
        run_start,
        pass_num=0,
        max_passes=max(1, args.max_passes),
        end_time=None,
    )

    errors = 0
    deferred = 0
    generation_counter = 1
    pass_num = 1
    max_passes = max(1, args.max_passes)
    completed = False
    consecutive_503 = 0
    while pass_num <= max_passes:
        progress_made = 0
        for catalog, prompt_id, combo_id, prompt_text, combo_file, out_file, wardrobe, combo_specs, input_paths in tasks:
            out_dir = out_file.parent
            out_dir.mkdir(parents=True, exist_ok=True)

            if out_file.exists():
                now_ts = datetime.now(TZ)
                duration_min = 0.0
                rel_path = str(out_file.relative_to(OUTPUT_BASE))
                status = f"SKIP-P{pass_num}"
                row = (
                    f"{generation_counter:4d} | "
                    f"{now_ts.strftime('%Y-%m-%d %H:%M:%S%z')} | "
                    f"{now_ts.strftime('%Y-%m-%d %H:%M:%S%z')} | "
                    f"{duration_min:12.2f} | "
                    f"{status:8} | "
                    f"{MODEL_NAME:6} | "
                    f"{wardrobe:10} | "
                    f"{catalog:7} | "
                    f"{prompt_id:6} | "
                    f"{combo_id:7} | "
                    f"{combo_specs:21} | "
                    f"{rel_path}\n"
                )
                print(f"[{generation_counter}] SKIP exists {out_file}")
                with log_path.open("a") as log:
                    log.write(row)
                with md_log_path.open("a") as mdlog:
                    mdlog.write(row)
                generation_counter += 1
                write_progress_log(progress_log_path, tasks, run_start, pass_num, max_passes)
                continue

            msg = f"[{generation_counter}] {catalog} {prompt_id} {combo_id} -> {out_file}"
            print(msg)
            start_ts = datetime.now(TZ)

            cmd = [
                "uv",
                "run",
                str(Path.home() / ".codex/skills/nano-banana-pro/scripts/generate_image.py"),
                "--prompt",
                prompt_text,
                "--filename",
                str(out_file),
                "--resolution",
                "2K",
            ]
            for p in input_paths:
                cmd.extend(["--input-image", str(p)])

            attempt = 1
            success = False
            last_err = ""
            while attempt <= args.max_attempts:
                result = run_cmd(cmd, args.per_image_timeout)
                if result.returncode == 0 and out_file.exists():
                    success = True
                    consecutive_503 = 0
                    break
                err = (result.stderr or result.stdout or "").strip()
                if result.returncode == 0 and not out_file.exists():
                    err = "Completed with success code but output file missing."
                last_err = err if err else f"exit status {result.returncode}"
                with log_path.open("a") as log:
                    log.write(f"ERROR detail (attempt {attempt}/{args.max_attempts}): {last_err}\n")

                if is_503_error(last_err):
                    consecutive_503 += 1
                    if consecutive_503 >= args.cooldown_after_503s:
                        time.sleep(args.cooldown_on_503)
                        consecutive_503 = 0
                    # defer quickly on 503 to keep progress moving
                    if attempt >= args.max_503_attempts:
                        break

                if attempt < args.max_attempts:
                    delay = min(args.retry_delay * (2 ** (attempt - 1)), args.max_retry_delay)
                    if is_503_error(last_err):
                        delay = max(delay, args.retry_delay_503)
                    # small jitter to avoid thundering herd
                    delay = min(delay + random.uniform(0, 3), args.max_retry_delay)
                    time.sleep(delay)
                attempt += 1

            end_ts = datetime.now(TZ)
            duration_min = (end_ts - start_ts).total_seconds() / 60.0
            rel_path = str(out_file.relative_to(OUTPUT_BASE))
            if success:
                status = f"OK-P{pass_num}"
                progress_made += 1
            else:
                if is_503_error(last_err):
                    status = f"DEFER-P{pass_num}"
                    deferred += 1
                else:
                    status = f"ERROR-P{pass_num}"
                    errors += 1

            row = (
                f"{generation_counter:4d} | "
                f"{start_ts.strftime('%Y-%m-%d %H:%M:%S%z')} | "
                f"{end_ts.strftime('%Y-%m-%d %H:%M:%S%z')} | "
                f"{duration_min:12.2f} | "
                f"{status:8} | "
                f"{MODEL_NAME:6} | "
                f"{wardrobe:10} | "
                f"{catalog:7} | "
                f"{prompt_id:6} | "
                f"{combo_id:7} | "
                f"{combo_specs:21} | "
                f"{rel_path}\n"
            )
            with log_path.open("a") as log:
                log.write(row)
                if not success and last_err:
                    log.write(f"ERROR detail (final): {last_err}\n")
            with md_log_path.open("a") as mdlog:
                mdlog.write(row)
            generation_counter += 1
            if args.inter_image_delay > 0:
                time.sleep(args.inter_image_delay)
            write_progress_log(progress_log_path, tasks, run_start, pass_num, max_passes)

        missing = [t[5] for t in tasks if not t[5].exists()]
        if not missing:
            completed = True
            break
        pass_num += 1
        if progress_made == 0:
            time.sleep(30)

    end_time = datetime.now(TZ)
    missing = [t[5] for t in tasks if not t[5].exists()]
    with log_path.open("a") as log:
        if completed:
            log.write(f"Run completed (Asia/Almaty): {end_time.strftime('%Y-%m-%d %H:%M:%S%z')}\n")
        else:
            log.write(
                f"Run ended incomplete (Asia/Almaty): {end_time.strftime('%Y-%m-%d %H:%M:%S%z')} | "
                f"missing: {len(missing)} | passes: {pass_num - 1}\n"
            )
        if errors:
            log.write(f"Errors: {errors}\n")
        if deferred:
            log.write(f"Deferred (503/UNAVAILABLE): {deferred}\n")
    with md_log_path.open("a") as mdlog:
        mdlog.write("```\n")
        if completed:
            mdlog.write(f"Run completed (Asia/Almaty): {end_time.strftime('%Y-%m-%d %H:%M:%S%z')}\n")
        else:
            mdlog.write(
                f"Run ended incomplete (Asia/Almaty): {end_time.strftime('%Y-%m-%d %H:%M:%S%z')} | "
                f"missing: {len(missing)} | passes: {pass_num - 1}\n"
            )
        if errors:
            mdlog.write(f"Errors: {errors}\n")
        if deferred:
            mdlog.write(f"Deferred (503/UNAVAILABLE): {deferred}\n")

    write_progress_log(progress_log_path, tasks, run_start, pass_num, max_passes, end_time=end_time)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
