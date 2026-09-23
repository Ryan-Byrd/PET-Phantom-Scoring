"""Focused tests for generic, in-memory DICOM metadata corrections."""

import unittest

from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from pet_tools.dicom_metadata_overrides import (
    MetadataOverrideError,
    MetadataOverrides,
    apply_metadata_overrides,
    build_metadata_override_audit,
)


class MetadataOverrideTests(unittest.TestCase):
    def setUp(self):
        self.dataset = Dataset()
        self.dataset.PatientWeight = "80.0"
        self.dataset.add_new((0x0071, 0x1022), "DT", "20260821100000")

        radiopharmaceutical = Dataset()
        radiopharmaceutical.RadionuclideTotalDose = "180000000"
        self.dataset.RadiopharmaceuticalInformationSequence = Sequence([
            radiopharmaceutical,
        ])

    def test_applies_top_level_nested_and_private_overrides_without_mutating_source(self):
        overrides = self._overrides({
            "PatientWeight": {"value": 75.5},
            "RadiopharmaceuticalInformationSequence[0].RadionuclideTotalDose": {
                "value": 185000000,
            },
            "(0071,1022)": {"value": "20260821103000"},
        })

        corrected, records = apply_metadata_overrides(self.dataset, overrides)

        self.assertEqual(float(self.dataset.PatientWeight), 80.0)
        self.assertEqual(float(corrected.PatientWeight), 75.5)
        self.assertEqual(
            float(self.dataset.RadiopharmaceuticalInformationSequence[0].RadionuclideTotalDose),
            180000000,
        )
        self.assertEqual(
            float(corrected.RadiopharmaceuticalInformationSequence[0].RadionuclideTotalDose),
            185000000,
        )
        self.assertEqual(str(self.dataset[(0x0071, 0x1022)].value), "20260821100000")
        self.assertEqual(str(corrected[(0x0071, 0x1022)].value), "20260821103000")
        self.assertEqual(len(records), 3)

    def test_rejects_unresolved_sequence_path(self):
        overrides = self._overrides({
            "MissingSequence[0].PatientWeight": {"value": 75.5},
        })

        with self.assertRaises(MetadataOverrideError):
            apply_metadata_overrides(self.dataset, overrides)

    def test_aggregates_equivalent_records_for_series_audit(self):
        overrides = self._overrides({"PatientWeight": {"value": 75.5}})
        _, records = apply_metadata_overrides(self.dataset, overrides)
        audit = build_metadata_override_audit(
            "test_tool",
            overrides,
            records + records,
            datasets_affected=2,
            reference_dataset=self.dataset,
        )

        self.assertEqual(len(audit["applied_overrides"]), 1)
        self.assertEqual(audit["applied_overrides"][0]["datasets_affected"], 2)

    @staticmethod
    def _overrides(overrides):
        return MetadataOverrides(
            source_path="C:\\test\\metadata_overrides.json",
            description="Test corrections",
            reason=None,
            overrides=overrides,
        )


if __name__ == "__main__":
    unittest.main()