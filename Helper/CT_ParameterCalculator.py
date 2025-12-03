# Helper/CT_ParameterCalculator.py
# --------------------------------
# Centralized computation and DICOM tag mapping for CT scan parameters.

import pydicom
from pydicom.tag import Tag


class CTParameterCalculator:
    """Comprehensive class to extract or compute all CT scan parameters."""

    # ---------- Utility Functions ----------
    @staticmethod
    def _get_val(ds, tag):
        """Safely return tag value (handles missing, lists, etc.)."""
        if tag not in ds:
            return None
        val = ds[tag].value
        if isinstance(val, (list, tuple)):
            val = val[0]
        return val

    @staticmethod
    def _to_float(v):
        try:
            return float(str(v).split("\\")[0])
        except Exception:
            return None

    # ---------- Core DICOM Parameters ----------
    @classmethod
    def get_kvp(cls, ds):
        """Tube potential (kVp) — (0018,0060)"""
        v = cls._get_val(ds, (0x0018, 0x0060))
        return cls._to_float(v)

    @classmethod
    def get_ma(cls, ds):
        """Tube current (mA) — (0018,1151)"""
        v = cls._get_val(ds, (0x0018, 0x1151))
        return cls._to_float(v)

    @classmethod
    def get_rotation_time(cls, ds):
        """Time per rotation (s) — (0018,9305)"""
        v = cls._get_val(ds, (0x0018, 0x9305))
        if v is None:
            v = cls._get_val(ds, (0x0018, 0x0031))  # fallback legacy
        return cls._to_float(v)

    @classmethod
    def get_scan_fov(cls, ds):
        """Data Collection Diameter (0018,0090) in cm"""
        v = cls._get_val(ds, (0x0018, 0x0090))
        f = cls._to_float(v)
        return round(f / 10, 1) if f else None

    @classmethod
    def get_display_fov(cls, ds):
        """Reconstruction Diameter (0018,1100) in cm"""
        v = cls._get_val(ds, (0x0018, 0x1100))
        f = cls._to_float(v)
        return round(f / 10, 1) if f else None

    @classmethod
    def get_slice_thickness(cls, ds):
        """Slice Thickness (0018,0050)"""
        v = cls._get_val(ds, (0x0018, 0x0050))
        return cls._to_float(v)

    @classmethod
    def get_spacing(cls, ds):
        """Spacing Between Slices (0018,0088)"""
        v = cls._get_val(ds, (0x0018, 0x0088))
        return cls._to_float(v)

    @classmethod
    def get_recon_alg(cls, ds):
        """Convolution Kernel (0018,1210)"""
        v = cls._get_val(ds, (0x0018, 0x1210))
        if v is None:
            return ""
        s = str(v)
        # Remove brackets or lists like ['Br40f', '3']
        s = s.replace("[", "").replace("]", "").replace("'", "")
        for sep in ["\\", ","]:
            if sep in s:
                s = s.split(sep)[0]
                break
        return s.strip()

    @classmethod
    def get_dose_reduction(cls, ds):
        """Exposure Modulation Type (0018,9323)"""
        v = cls._get_val(ds, (0x0018, 0x9323))
        return str(v) if v else ""

    # ---------- Geometry and Collimation ----------
    @classmethod
    def get_total_collimation(cls, ds):
        """Total Collimation Width (0018,9307)"""
        v = cls._get_val(ds, (0x0018, 0x9307))
        return cls._to_float(v)

    @classmethod
    def get_single_collimation(cls, ds):
        """Single Collimation Width (0018,9306)"""
        v = cls._get_val(ds, (0x0018, 0x9306))
        return cls._to_float(v)

    @classmethod
    def get_table_speed(cls, ds):
        """Table Speed (0018,9309) [mm/s]"""
        v = cls._get_val(ds, (0x0018, 0x9309))
        return cls._to_float(v)

    @classmethod
    def get_table_feed_per_rot(cls, ds):
        """Table Feed per Rotation (0018,9310) [mm/rot]"""
        v = cls._get_val(ds, (0x0018, 0x9310))
        return cls._to_float(v)

    @classmethod
    def get_pitch(cls, ds):
        """
        Spiral Pitch Factor (0018,9311),
        or compute: pitch = table_feed_per_rot / total_collimation
        """
        v = cls._get_val(ds, (0x0018, 0x9311))
        if v is not None:
            return cls._to_float(v)
        feed = cls.get_table_feed_per_rot(ds)
        coll = cls.get_total_collimation(ds)
        if feed and coll and coll != 0:
            return round(feed / coll, 3)
        return None

    @classmethod
    def get_n_channels(cls, ds):
        """Number of data channels used (approx.)"""
        total = cls.get_total_collimation(ds)
        single = cls.get_single_collimation(ds)
        if total and single and single != 0:
            return round(total / single)
        return None

    # ---------- Derived Exposure Parameters ----------
    @classmethod
    def get_mas(cls, ds):
        """mAs = mA × Rotation Time"""
        ma = cls.get_ma(ds)
        rot = cls.get_rotation_time(ds)
        if ma and rot:
            return round(ma * rot, 2)
        return None

    @classmethod
    def get_effective_mas(cls, ds):
        """Effective mAs = mAs / Pitch"""
        mas = cls.get_mas(ds)
        pitch = cls.get_pitch(ds)
        if mas and pitch and pitch != 0:
            return round(mas / pitch, 2)
        return None

    # ---------- Table Increment ----------
    @classmethod
    def get_table_increment(cls, ds):
        """Table Increment (0018,9310)"""
        v = cls._get_val(ds, (0x0018, 0x9310))
        if v is not None:
            return cls._to_float(v)
        feed = cls.get_table_feed_per_rot(ds)
        # Single-image increment fallback (rarely needed)
        if feed:
            return round(feed, 3)
        return None

    # ---------- Classification ----------
    @classmethod
    def get_scan_mode(cls, ds):
        """Axial (A) or Helical (H)"""
        pitch = cls.get_pitch(ds)
        if pitch and pitch > 0:
            return "H"
        return "A"
