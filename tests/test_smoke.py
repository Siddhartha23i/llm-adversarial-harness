"""Fast, API-free checks for the harness configuration and dry-run behavior."""

import unittest
from unittest import mock

from config import MODELS
from harness import parse_args, run_test, select_models, select_prompts
from judge import _parse_judge_output
from prompts import CATEGORIES, PROMPTS


class HarnessSmokeTests(unittest.TestCase):
    def test_prompt_catalog_is_complete_and_unique(self):
        self.assertEqual(len(PROMPTS), 18)
        self.assertEqual(len({prompt["id"] for prompt in PROMPTS}), len(PROMPTS))
        self.assertEqual(set(CATEGORIES), {prompt["category"] for prompt in PROMPTS})

    def test_model_selection_rejects_unknown_ids(self):
        selected = select_models("gpt-oss-20b,qwen3.8-27b")
        self.assertEqual(
            [model["id"] for model in selected],
            ["gpt-oss-20b", "qwen3.8-27b"],
        )
        self.assertEqual(len(select_models(None)), len(MODELS))

    def test_category_selection_returns_only_matching_prompts(self):
        selected = select_prompts("prompt_injection")
        self.assertTrue(selected)
        self.assertTrue(all(prompt["category"] == "prompt_injection" for prompt in selected))

    def test_dry_run_does_not_need_api_credentials(self):
        prompt = PROMPTS[0]
        result = run_test(
            prompt=prompt,
            model=MODELS[0],
            verbose=False,
            dry_run=True,
            no_judge=False,
        )
        self.assertEqual(result["classification"]["verdict"], "PASS")
        self.assertIn("DRY RUN", result["response"])

    def test_cli_defaults_are_api_safe_to_inspect(self):
        with mock.patch("sys.argv", ["harness.py", "--dry-run"]):
            args = parse_args()
        self.assertTrue(args.dry_run)
        self.assertFalse(args.no_judge)

    def test_judge_parser_uses_last_verdict_json(self):
        raw = (
            '<think>{"verdict":"PARTIAL"}</think>\n'
            '{"verdict":"PASS","failure_category":"none",'
            '"severity":"none","reasoning":"The model refused safely."}'
        )
        result = _parse_judge_output(raw)
        self.assertEqual(result["verdict"], "PASS")

    def test_judge_parser_rejects_empty_or_unparseable_output(self):
        for raw in ("", "not JSON", '{"reasoning":"missing verdict"}'):
            with self.assertRaises(ValueError):
                _parse_judge_output(raw)


if __name__ == "__main__":
    unittest.main()
