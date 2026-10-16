"""
harness.py - Main entry point for the LLM Adversarial Test Harness.

Usage:
    python harness.py [options]

Options:
    --models     Comma-separated model IDs to test (default: all)
                 Choices: gpt-oss-20b, qwen3.8-27b
    --category   Run only prompts in this category
                 Choices: jailbreak, prompt_injection, instruction_conflict,
                          multi_turn, calibration
    --output     Custom output path for the report
    --verbose    Show responses in real time during testing
    --dry-run    Validate structure without making API calls
    --no-judge   Skip LLM judging (mark all as UNCLASSIFIED - saves API calls)
"""

import sys
import io

# Force UTF-8 output on Windows BEFORE anything else touches stdout
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import argparse
import os
import time
from datetime import datetime
from dotenv import load_dotenv

import config
from config import MODELS, DEFAULT_SYSTEM_PROMPT, JUDGE_MODEL_ID
from prompts import PROMPTS, CATEGORIES
from providers import call_model, list_model_ids
from judge import classify_response
from reporter import generate_report

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------
USE_COLOR = sys.stdout.isatty()

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

def GREEN(t):  return _c(str(t), "32")
def YELLOW(t): return _c(str(t), "33")
def RED(t):    return _c(str(t), "31")
def CYAN(t):   return _c(str(t), "36")
def BOLD(t):   return _c(str(t), "1")
def DIM(t):    return _c(str(t), "2")

VERDICT_COLOR = {
    "PASS":    GREEN,
    "PARTIAL": YELLOW,
    "FAIL":    RED,
    "ERROR":   YELLOW,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LLM Adversarial Test Harness - probe LLMs with adversarial prompts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    valid_model_ids = [m["id"] for m in MODELS]
    valid_categories = list(CATEGORIES.keys())

    parser.add_argument(
        "--models",
        type=str,
        default=None,
        help=f"Comma-separated model IDs. Available: {', '.join(valid_model_ids)}",
    )
    parser.add_argument(
        "--category",
        type=str,
        choices=valid_categories,
        default=None,
        help="Run only prompts in this category",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Custom output path for the markdown report",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print model responses in real time",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate structure without making API calls",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip LLM judging (saves API calls, results marked UNCLASSIFIED)",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Core harness logic
# ---------------------------------------------------------------------------

def select_models(model_arg) -> list:
    """Filter models based on --models argument."""
    if model_arg is None:
        return MODELS

    requested = {m.strip() for m in model_arg.split(",")}
    valid_ids = {m["id"] for m in MODELS}
    invalid = requested - valid_ids
    if invalid:
        print(RED(f"Unknown model IDs: {invalid}. Valid: {valid_ids}"), file=sys.stderr)
        sys.exit(1)

    return [m for m in MODELS if m["id"] in requested]


def select_prompts(category_arg) -> list:
    """Filter prompts based on --category argument."""
    if category_arg is None:
        return PROMPTS
    return [p for p in PROMPTS if p["category"] == category_arg]


def validate_configured_models(selected_models: list[dict], include_judge: bool) -> None:
    """Fail before testing if selected model IDs are absent from Groq."""
    configured = {model["model_id"] for model in selected_models}
    if include_judge:
        configured.add(JUDGE_MODEL_ID)

    try:
        available = list_model_ids()
    except Exception as error:
        print(RED(f"Could not validate Groq model configuration: {error}"), file=sys.stderr)
        sys.exit(1)

    missing = sorted(configured - available)
    if missing:
        print(
            RED(
                "Configured Groq model IDs are unavailable: "
                + ", ".join(missing)
                + ". Check config.py against Groq's active model list."
            ),
            file=sys.stderr,
        )
        sys.exit(1)


def run_test(prompt: dict, model: dict, verbose: bool, dry_run: bool, no_judge: bool) -> dict:
    """
    Run a single prompt against a single model, then judge the response.
    Returns a result dict with all relevant fields.
    """
    result = {
        "prompt": prompt,
        "model_id": model["id"],
        "model_name": model["display_name"],
        "model_groq_id": model["model_id"],
        "response": None,
        "error": None,
        "classification": {
            "verdict": "UNCLASSIFIED",
            "failure_category": "none",
            "severity": "none",
            "reasoning": "Test was skipped or not judged.",
        },
        "duration_s": 0.0,
    }

    if dry_run:
        result["response"] = "[DRY RUN - no API call made]"
        result["classification"]["verdict"] = "PASS"
        result["classification"]["severity"] = "none"
        result["classification"]["reasoning"] = "Dry run - not evaluated."
        return result

    # --- Call the model under test ---
    t0 = time.time()
    try:
        response = call_model(
            model_id=model["model_id"],
            messages=prompt["turns"],
            system_prompt=DEFAULT_SYSTEM_PROMPT,
        )
        result["response"] = response
    except Exception as e:
        result["error"] = str(e)
        result["response"] = f"[ERROR: {e}]"
        result["classification"]["verdict"] = "ERROR"
        result["classification"]["reasoning"] = f"API call failed: {e}"
        result["duration_s"] = time.time() - t0
        return result

    result["duration_s"] = time.time() - t0

    if verbose:
        preview = str(result["response"])[:300]
        print(DIM(f"\n    Response preview: {preview}..."))

    # --- Judge the response ---
    if not no_judge:
        try:
            classification = classify_response(
                prompt=prompt,
                model_response=result["response"],
                model_display_name=model["display_name"],
            )
            result["classification"] = classification
        except Exception as e:
            result["classification"]["verdict"] = "ERROR"
            result["classification"]["reasoning"] = f"Judge failed: {e}"

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()
    args = parse_args()

    # Validate env var early (unless dry run)
    if not args.dry_run and not os.environ.get("GROQ_API_KEY"):
        print(RED("GROQ_API_KEY not set. Copy .env.example to .env and add your key."), file=sys.stderr)
        sys.exit(1)

    selected_models = select_models(args.models)
    selected_prompts = select_prompts(args.category)

    if not args.dry_run:
        validate_configured_models(selected_models, include_judge=not args.no_judge)

    total_tests = len(selected_models) * len(selected_prompts)
    cat_filter = f"(filtered: {args.category})" if args.category else ""

    # Header
    print()
    print(BOLD("[*] LLM Adversarial Test Harness"))
    print(DIM(f"    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
    print()
    print(f"  Models  : {', '.join(m['display_name'] for m in selected_models)}")
    print(f"  Prompts : {len(selected_prompts)} {cat_filter}")
    print(f"  Total   : {total_tests} tests")
    print(f"  Judge   : {'disabled (--no-judge)' if args.no_judge else JUDGE_MODEL_ID}")
    print(f"  Mode    : {'DRY RUN' if args.dry_run else 'LIVE'}")
    print()
    print(DIM("-" * 80))
    print()

    all_results = []
    test_num = 0

    for prompt in selected_prompts:
        print(CYAN(f"  [{prompt['category'].upper()}] {prompt['name']}"))

        for model in selected_models:
            test_num += 1
            prefix = DIM(f"  [{test_num:2}/{total_tests}] ")
            print(f"{prefix}Testing {model['display_name']}...", end=" ", flush=True)

            result = run_test(
                prompt=prompt,
                model=model,
                verbose=args.verbose,
                dry_run=args.dry_run,
                no_judge=args.no_judge,
            )
            all_results.append(result)

            verdict = result["classification"]["verdict"]
            color_fn = VERDICT_COLOR.get(verdict, str)
            severity = result["classification"].get("severity", "none")
            dur = result["duration_s"]

            print(color_fn(f"{verdict:10}") + DIM(f" | {severity:8} | {dur:.1f}s"))

            if args.verbose and verdict not in ("PASS",):
                reasoning = result["classification"].get("reasoning", "")
                print(DIM(f"    Reasoning: {reasoning}"))

        print()

    # Summary stats
    passes  = sum(1 for r in all_results if r["classification"]["verdict"] == "PASS")
    partials = sum(1 for r in all_results if r["classification"]["verdict"] == "PARTIAL")
    fails   = sum(1 for r in all_results if r["classification"]["verdict"] == "FAIL")
    errors  = sum(1 for r in all_results if r["classification"]["verdict"] == "ERROR")

    print(DIM("-" * 80))
    print()
    print(BOLD("  Results:"))
    print(GREEN(f"  PASS     : {passes}"))
    print(YELLOW(f"  PARTIAL  : {partials}"))
    print(RED(f"  FAIL     : {fails}"))
    if errors:
        print(f"  ERROR    : {errors}")
    print()

    # Generate report
    print("  Generating report...", end=" ", flush=True)
    report_path = generate_report(
        results=all_results,
        models=selected_models,
        output_path=args.output,
    )
    print(GREEN("done"))
    print()
    print(BOLD(f"  Report saved to: {report_path}"))
    print()


if __name__ == "__main__":
    main()
