from datetime import date
from unittest import TestCase

from .validation import (
    age_on,
    validate_age_preferences,
    validate_alias,
    validate_birth_date,
    validate_distance_preference,
    validate_target_genders,
)


class AboutYouValidationTests(TestCase):
    def test_eighteenth_birthday_is_accepted_but_not_the_day_before(self):
        born = date(2008, 11, 15)
        with self.assertRaisesRegex(ValueError, "must_be_18_or_older"):
            validate_birth_date(born, date(2026, 11, 14))
        self.assertEqual(validate_birth_date(born, date(2026, 11, 15)), born)
        self.assertEqual(age_on(born, date(2026, 11, 15)), 18)

    def test_future_birth_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must_be_18_or_older"):
            validate_birth_date(date(2027, 1, 1), date(2026, 11, 15))

    def test_age_100_is_supported_and_101_is_rejected(self):
        self.assertEqual(age_on(date(1925, 11, 16), date(2026, 11, 15)), 100)
        validate_birth_date(date(1925, 11, 16), date(2026, 11, 15))
        with self.assertRaisesRegex(ValueError, "birth_date_invalid"):
            validate_birth_date(date(1925, 11, 15), date(2026, 11, 15))

    def test_leap_day_birthday_matches_the_application_age_rule(self):
        self.assertEqual(age_on(date(2008, 2, 29), date(2026, 2, 28)), 17)
        self.assertEqual(age_on(date(2008, 2, 29), date(2026, 3, 1)), 18)

    def test_alias_keeps_user_chosen_names_and_trims_outer_whitespace(self):
        self.assertEqual(validate_alias("  My own alias  "), "My own alias")
        self.assertEqual(validate_alias("\U0001f31f Mrembo"), "\U0001f31f Mrembo")

    def test_invalid_aliases_are_rejected_before_database_writes(self):
        for alias in ["", " ", "a", "a" * 41, "Some\nName", "Some\x00Name", "Bad\ud800name"]:
            with self.subTest(alias=repr(alias)):
                with self.assertRaisesRegex(ValueError, "alias_invalid"):
                    validate_alias(alias)


class MatchingPreferencesValidationTests(TestCase):
    def test_every_gender_and_custom_combinations_are_supported(self):
        for values in [["M"], ["W"], ["NB"], ["M", "W"], ["W", "NB"], ["M", "W", "NB"], ["ALL"]]:
            with self.subTest(values=values):
                self.assertEqual(validate_target_genders(values), values)

    def test_everyone_cannot_be_combined_with_specific_genders(self):
        with self.assertRaisesRegex(ValueError, "target_genders_invalid"):
            validate_target_genders(["ALL", "M"])

    def test_empty_duplicate_unknown_and_malformed_selections_are_rejected(self):
        for values in [[], ["M", "M"], ["unknown"], ["m"], [None], [["M"]], "M", {}, None]:
            with self.subTest(values=values):
                with self.assertRaisesRegex(ValueError, "target_genders_invalid"):
                    validate_target_genders(values)

    def test_supported_adult_age_boundaries_and_single_year_ranges(self):
        for minimum, maximum in [(18, 100), (18, 18), (40, 85), (100, 100)]:
            with self.subTest(minimum=minimum, maximum=maximum):
                validate_age_preferences(minimum, maximum)

    def test_underage_reversed_and_over_limit_ranges_are_rejected(self):
        for minimum, maximum in [(17, 30), (30, 29), (18, 101), (0, 100), (101, 101)]:
            with self.subTest(minimum=minimum, maximum=maximum):
                with self.assertRaisesRegex(ValueError, "age_preference_range_invalid"):
                    validate_age_preferences(minimum, maximum)

    def test_age_range_requires_integers(self):
        for minimum, maximum in [(True, 30), (18, False), (18.5, 30), (18, "30"), (None, 30)]:
            with self.subTest(minimum=minimum, maximum=maximum):
                with self.assertRaisesRegex(ValueError, "age_preference_range_invalid"):
                    validate_age_preferences(minimum, maximum)

    def test_distance_boundaries_are_supported(self):
        for distance in [1, 15, 50]:
            validate_distance_preference(distance)

    def test_invalid_distances_are_rejected(self):
        for distance in [0, -1, 51, True, 1.5, "15", None]:
            with self.subTest(distance=distance):
                with self.assertRaisesRegex(ValueError, "distance_preference_range_invalid"):
                    validate_distance_preference(distance)
