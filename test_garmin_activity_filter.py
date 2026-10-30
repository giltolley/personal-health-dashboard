"""Prevent synthetic MyFitnessPal activities reappearing after Garmin sync."""
import sqlite3
import unittest

from garmin_importer import import_dataset


def activity(activity_id, name, when="2026-10-28T07:30:00", activity_type="walking"):
    return {
        "activityId": activity_id,
        "activityName": name,
        "startTimeLocal": when,
        "activityType": {"typeKey": activity_type},
        "duration": 1800,
        "calories": 100,
    }


class GarminActivityFilterTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")

    def tearDown(self):
        self.db.close()

    def test_filters_myfitnesspal_substring_and_preserves_real_sessions(self):
        rows = [
            activity(11, "Walking - MyFitnessPal"),
            activity(12, "Strength training - myfitnesspal"),
            activity(13, "MYFITNESSPAL generated yoga", activity_type="yoga"),
            activity(14, "Strength", activity_type="strength_training"),
            activity(15, "Walking"),
            activity(16, "Dover Walking"),
        ]
        written = import_dataset(self.db, "activities", rows)
        self.assertEqual(written, 3)
        actual = self.db.execute(
            "SELECT activity_id, activity_name FROM garmin_activities ORDER BY activity_id"
        ).fetchall()
        self.assertEqual(actual, [
            ("14", "Strength"),
            ("15", "Walking"),
            ("16", "Dover Walking"),
        ])

    def test_reimport_cannot_restore_filtered_sessions(self):
        import_dataset(self.db, "activities", [activity(1, "Strength")])
        import_dataset(self.db, "activities", [
            activity(2, "Walking - MyFitnessPal"),
            activity(3, "Strength training (weight lifting) - MyFitnessPal"),
            activity(1, "Strength"),
        ])
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM garmin_activities").fetchone()[0], 1
        )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM garmin_activities WHERE activity_name LIKE '%MyFitnessPal%'"
            ).fetchone()[0], 0
        )

    def test_import_logs_only_retained_activities(self):
        retained = import_dataset(
            self.db, "activities", [activity(4, "MyFitnessPal - walking"), activity(5, "Treadmill")]
        )
        self.assertEqual(retained, 1)
        count, status = self.db.execute(
            "SELECT record_count, status FROM ingestion_log ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual((count, status), (1, "ok"))


if __name__ == "__main__":
    unittest.main()
