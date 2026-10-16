import unittest

import timeline_state as ts


class EnglishTimeJumpDetectionTests(unittest.TestCase):
    def targets(self, text):
        return [d.target for d in ts.detect_time_directives(text)]

    def test_explicit_english_jump_phrases(self):
        self.assertEqual(self.targets("Skip to the next morning."), ["the next morning"])
        self.assertEqual(self.targets("Fast-forward to Chapter 30"), ["Chapter 30"])
        self.assertEqual(self.targets("Let's jump ahead to three days later"), ["three days later"])

    def test_bare_english_time_targets(self):
        self.assertEqual(self.targets("Chapter 30"), ["Chapter 30"])
        self.assertEqual(self.targets("the year 1968"), ["the year 1968"])

    def test_ordinary_movement_and_narration_are_not_jumps(self):
        self.assertEqual(self.targets("I go to the tavern"), [])
        self.assertEqual(self.targets("In 1968, William attended the opening party"), [])
        self.assertEqual(self.targets("I cut to the chase and ask her directly"), [])

    def test_chinese_forms_still_work(self):
        self.assertEqual(self.targets("第30章"), ["第30章"])
        self.assertTrue(ts.has_jump_verb("快进到第二天"))


if __name__ == "__main__":
    unittest.main()
