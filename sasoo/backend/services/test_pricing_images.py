import unittest

from services.pricing import IMAGE_PRICING, PricingUsageError, calc_image_cost


class ImagePricingTests(unittest.TestCase):
    def test_gpt_image_2_quality_tiers(self):
        # 1536x1024 기준 공식 단가 (2026-07-11 developers.openai.com)
        self.assertEqual(IMAGE_PRICING["gpt-image-2:low"], 0.005)
        self.assertEqual(IMAGE_PRICING["gpt-image-2:medium"], 0.041)
        self.assertEqual(IMAGE_PRICING["gpt-image-2:high"], 0.165)

    def test_nano_banana_2(self):
        self.assertEqual(IMAGE_PRICING["gemini-3.1-flash-image"], 0.067)

    def test_calc_image_cost(self):
        self.assertEqual(calc_image_cost("gpt-image-2:high"), 0.165)
        self.assertEqual(calc_image_cost("gpt-image-2:high", 2), 0.33)

    def test_flare_prices_reported_request_usage(self):
        usage = {"input_tokens": 300, "input_tokens_details": {"text_tokens": 100, "image_tokens": 200},
                 "output_tokens": 1000}
        self.assertEqual(calc_image_cost("gpt-image-2.5-flare:high", usage=usage), 0.0321)
        self.assertEqual(calc_image_cost("gpt-image-2.5-flare:high", 2, usage=usage), 0.0321)
        for invalid in (None, {}, {**usage, "input_tokens": 301}, {**usage, "output_tokens": -1},
                        {**usage, "output_tokens": True}):
            with self.subTest(usage=invalid), self.assertRaises(PricingUsageError):
                calc_image_cost("gpt-image-2.5-flare:high", usage=invalid)

    def test_nano_banana_21_prices_image_and_thought_tokens(self):
        usage = {
            "total_input_tokens": 100,
            "total_output_tokens": 1130,
            "total_thought_tokens": 20,
            "output_tokens_by_modality": [
                {"modality": "image", "tokens": 1120},
                {"modality": "text", "tokens": 10},
            ],
        }
        self.assertEqual(calc_image_cost("gemini-nano-banana-2.1", usage=usage), 0.033975)
        for invalid in (None, {**usage, "total_thought_tokens": None},
                        {**usage, "output_tokens_by_modality": []},
                        {**usage, "total_output_tokens": 1000}):
            with self.subTest(usage=invalid), self.assertRaises(PricingUsageError):
                calc_image_cost("gemini-nano-banana-2.1", usage=invalid)


if __name__ == "__main__":
    unittest.main()
