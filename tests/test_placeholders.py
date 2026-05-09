import unittest

from beleggingsraadgever.placeholders import contains_todo, is_nonempty_string, is_placeholder


class PlaceholderTests(unittest.TestCase):
    def test_placeholder_detection_catches_empty_dates_and_todos(self) -> None:
        self.assertTrue(is_placeholder(None))
        self.assertTrue(is_placeholder(""))
        self.assertTrue(is_placeholder("YYYY-MM-DD"))
        self.assertTrue(is_placeholder("TODO: vul aan"))
        self.assertFalse(is_placeholder("2026-05-09"))

    def test_todo_and_string_helpers(self) -> None:
        self.assertTrue(contains_todo("waarde met TODO erin"))
        self.assertFalse(contains_todo("waarde"))
        self.assertTrue(is_nonempty_string("x"))
        self.assertFalse(is_nonempty_string(" "))


if __name__ == "__main__":
    unittest.main()
