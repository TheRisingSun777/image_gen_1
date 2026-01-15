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
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path


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


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True)


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
        "--max-passes",
        type=int,
        default=5,
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

    tasks: list[tuple[str, str, str, str, Path, Path, str]] = []
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
                tasks.append((catalog, prompt_id, combo_id, prompt_text, combo_file, out_file, wardrobe))

    print(f"Total images queued: {len(tasks)}")

    errors = 0
    generation_counter = 1
    pass_num = 1
    max_passes = max(1, args.max_passes)
    while pass_num <= max_passes:
        for catalog, prompt_id, combo_id, prompt_text, combo_file, out_file, wardrobe in tasks:
            out_dir = out_file.parent
            out_dir.mkdir(parents=True, exist_ok=True)

            env = read_combo_env(combo_file)
            key_order = ["WARDROBE", "BOTTOM", "POSE", "UI"]
            present_keys = [k for k in key_order if k in env]
            if not present_keys:
                raise KeyError(f"No reference keys found in {combo_file}")

            if out_file.exists():
                now_ts = datetime.now(TZ)
                duration_min = 0.0
                rel_path = str(out_file.relative_to(OUTPUT_BASE))
                combo_specs = ",".join(present_keys)
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
                continue

            input_paths = [ASSET_BASE / env[k] for k in present_keys]
            for p in input_paths:
                if not p.exists():
                    raise FileNotFoundError(f"Missing input image: {p}")

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
                result = run_cmd(cmd)
                if result.returncode == 0:
                    success = True
                    break
                err = (result.stderr or result.stdout or "").strip()
                last_err = err if err else f"exit status {result.returncode}"
                with log_path.open("a") as log:
                    log.write(f"ERROR detail (attempt {attempt}/{args.max_attempts}): {last_err}\n")
                if attempt < args.max_attempts:
                    time.sleep(args.retry_delay)
                attempt += 1

            end_ts = datetime.now(TZ)
            duration_min = (end_ts - start_ts).total_seconds() / 60.0
            combo_specs = ",".join(present_keys)
            rel_path = str(out_file.relative_to(OUTPUT_BASE))
            status = f"{'OK' if success else 'ERROR'}-P{pass_num}"
            if not success:
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

        missing = [out for *_, out, _ in tasks if not out.exists()]
        if not missing:
            break
        pass_num += 1

    with log_path.open("a") as log:
        log.write(f"Run completed (Asia/Almaty): {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S%z')}\n")
        if errors:
            log.write(f"Errors: {errors}\n")
    with md_log_path.open("a") as mdlog:
        mdlog.write("```\n")
        mdlog.write(f"Run completed (Asia/Almaty): {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S%z')}\n")
        if errors:
            mdlog.write(f"Errors: {errors}\n")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
