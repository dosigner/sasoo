import unittest

from services.pricing import IMAGE_PRICING, calc_image_cost


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


if __name__ == "__main__":
    unittest.main()
