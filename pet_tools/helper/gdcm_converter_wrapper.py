#!/usr/bin/env python3
"""
Wrapper for native GDCM converter (C extension).

Falls back to gdcmconv.exe if the C extension is not available.
"""

import os
import ctypes
import sys
from pathlib import Path


class GDCMConverterWrapper:
    """Manages the GDCM C extension with graceful fallback."""
    
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.native_lib = None
        self._load_native()
    
    def _load_native(self):
        """Attempt to load the native C extension."""
        try:
            lib_dir = os.path.dirname(os.path.abspath(__file__))
            
            # Try different possible library names/paths
            possible_paths = [
                os.path.join(lib_dir, "bin", "gdcm_converter.dll"),
                os.path.join(lib_dir, "build", "lib", "gdcm_converter.dll"),
                os.path.join(lib_dir, "build", "Release", "gdcm_converter.dll"),
                os.path.join(lib_dir, "gdcm_converter.dll"),
            ]
            
            for lib_path in possible_paths:
                if os.path.exists(lib_path):
                    self.native_lib = ctypes.CDLL(lib_path)
                    
                    # Define function signatures
                    self.native_lib.convert_dicom_directory.argtypes = [
                        ctypes.c_char_p,
                        ctypes.c_char_p,
                        ctypes.c_int
                    ]
                    self.native_lib.convert_dicom_directory.restype = ctypes.c_int
                    
                    self.native_lib.get_conversion_stats.argtypes = [
                        ctypes.POINTER(ctypes.c_int),
                        ctypes.POINTER(ctypes.c_int),
                        ctypes.POINTER(ctypes.c_int),
                        ctypes.POINTER(ctypes.c_int),
                        ctypes.POINTER(ctypes.c_int),
                    ]
                    self.native_lib.get_conversion_stats.restype = None
                    
                    if self.verbose:
                        print(f"✓ Loaded native GDCM converter from: {lib_path}")
                    return
            
            if self.verbose:
                print("⚠ Native GDCM converter not found. Will use fallback (gdcmconv.exe)")
        
        except Exception as e:
            if self.verbose:
                print(f"⚠ Failed to load native converter: {e}")
    
    def convert_directory(self, input_dir, output_dir):
        """
        Convert DICOM files in input directory to output directory.
        
        Uses native C extension if available, otherwise falls back to gdcmconv.exe.
        
        Returns:
            dict: Statistics of the conversion
        """
        input_dir = os.path.abspath(input_dir)
        output_dir = os.path.abspath(output_dir)
        
        if not os.path.exists(input_dir):
            raise FileNotFoundError(f"Input directory not found: {input_dir}")
        
        os.makedirs(output_dir, exist_ok=True)
        
        if self.native_lib:
            return self._convert_native(input_dir, output_dir)
        else:
            return self._convert_fallback(input_dir, output_dir)
    
    def _convert_native(self, input_dir, output_dir):
        """Convert using native C extension."""
        if self.verbose:
            print(f"Converting using native GDCM extension...")
        
        # Call C function
        result = self.native_lib.convert_dicom_directory(
            input_dir.encode('utf-8'),
            output_dir.encode('utf-8'),
            1 if self.verbose else 0
        )
        
        # Get stats
        total = ctypes.c_int()
        dicom = ctypes.c_int()
        converted = ctypes.c_int()
        failed = ctypes.c_int()
        skipped = ctypes.c_int()
        
        self.native_lib.get_conversion_stats(
            ctypes.byref(total),
            ctypes.byref(dicom),
            ctypes.byref(converted),
            ctypes.byref(failed),
            ctypes.byref(skipped),
        )
        
        return {
            "total_files": total.value,
            "dicom_files": dicom.value,
            "converted_files": converted.value,
            "failed_files": failed.value,
            "skipped_files": skipped.value,
            "return_code": result,
        }
    
    def _convert_fallback(self, input_dir, output_dir):
        """Fallback: use gdcmconv.exe directly (existing implementation)."""
        if self.verbose:
            print(f"Converting using fallback (gdcmconv.exe)...")
        
        from universal_dicom_converter import convert_directory as fallback_convert
        return fallback_convert(input_dir, output_dir, self.verbose)


# Convenience function for use in existing code
def convert_directory_native(input_dir, output_dir, verbose=False):
    """Convenience wrapper to convert a directory using native extension if available."""
    wrapper = GDCMConverterWrapper(verbose=verbose)
    return wrapper.convert_directory(input_dir, output_dir)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Native GDCM DICOM converter")
    parser.add_argument("--input", "-i", required=True, help="Input directory")
    parser.add_argument("--output", "-o", required=True, help="Output directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    wrapper = GDCMConverterWrapper(verbose=args.verbose)
    stats = wrapper.convert_directory(args.input, args.output)
    
    print("\n=== Conversion Results ===")
    for key, value in stats.items():
        print(f"{key}: {value}")
    
    sys.exit(stats.get("return_code", 0))
