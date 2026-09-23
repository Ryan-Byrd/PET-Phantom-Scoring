# Native GDCM Converter

This directory contains a native C implementation of the DICOM converter that succeeds the Python-based `universal_dicom_converter.py`.

## Overview

- **gdcm_converter.c**: C implementation using GDCM library
  - Detects DICOM files by content (not extension)
  - Converts to Explicit VR Little Endian
  - Preserves UIDs and pixel data
  - Operates on flat directories (no recursion)

- **gdcm_converter_wrapper.py**: Python wrapper with automatic fallback
  - Loads native DLL if available
  - Falls back to `gdcmconv.exe` if native library not built
  - Maintains same interface as original converter

- **CMakeLists.txt**: Build configuration
- **build_gdcm_converter.bat**: Windows build script

## Building on Windows

### Prerequisites

1. **Visual Studio 2022** or later (with C++ development tools)
2. **CMake** 3.10+
3. **GDCM** installed and accessible:
   ```powershell
   python -m pip install gdcm
   ```

### Build Steps

```powershell
cd pet_tools\helper
.\build_gdcm_converter.bat
```

The script will:
1. Create a `build/` directory
2. Run CMake to configure the project
3. Compile the C extension
4. Copy `gdcm_converter.dll` to `bin/`

The DLL will be available at: `pet_tools/helper/bin/gdcm_converter.dll`

## Usage in Python

### Automatic (with fallback)

```python
from pet_tools.helper.gdcm_converter_wrapper import convert_directory_native

stats = convert_directory_native(
    input_dir="/path/to/input",
    output_dir="/path/to/output",
    verbose=True
)

print(stats)
# {
#     'total_files': 100,
#     'dicom_files': 95,
#     'converted_files': 95,
#     'failed_files': 0,
#     'skipped_files': 5,
#     'return_code': 0
# }
```

### Direct (C extension)

If you want to call the C extension directly:

```python
import ctypes
import os

lib_path = "pet_tools/helper/bin/gdcm_converter.dll"
lib = ctypes.CDLL(lib_path)

lib.convert_dicom_directory.argtypes = [
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_int
]
lib.convert_dicom_directory.restype = ctypes.c_int

result = lib.convert_dicom_directory(
    b"/path/to/input",
    b"/path/to/output",
    1  # verbose
)
```

## Command Line

```bash
python -m pet_tools.helper.gdcm_converter_wrapper --input /path/to/input --output /path/to/output --verbose
```

## Fallback Behavior

If the native DLL is not available, the wrapper automatically falls back to using `gdcmconv.exe` (the existing system). This ensures:

- **Compatibility**: Works with or without native build
- **Graceful degradation**: Converter functionality never breaks
- **Performance**: Faster when native DLL is available

## Performance Benefits

- **Direct C/C++ calls**: No subprocess overhead
- **In-process execution**: No inter-process communication delays
- **Batch operations**: Process entire directories without shell escaping

## Troubleshooting

### Build fails with "GDCM not found"

Ensure GDCM headers and libraries are in CMake search path:

```powershell
python -c "import gdcm; print(gdcm.__file__)"
```

If GDCM is installed via pip, CMake may need explicit paths. Update `CMakeLists.txt`:

```cmake
set(GDCM_DIR "C:/path/to/python/site-packages/_gdcm")
find_package(GDCM REQUIRED)
```

### DLL fails to load

Ensure dependencies are in PATH:
```powershell
set PATH=%PATH%;C:\path\to\gdcm\bin
```

### Native DLL not found, using fallback

This is expected if you haven't built the native extension. The converter will use `gdcmconv.exe` instead. To build the native version, run `build_gdcm_converter.bat`.

## Packaging

When creating the PyInstaller distribution, include both:

1. `pet_tools/helper/bin/gdcm_converter.dll` (if built)
2. `pet_tools/helper/bin/gdcmconv.exe` (fallback)

Update `PET_QA_Toolkit.spec` to ensure the `bin/` directory is included in `datas`.

## Architecture

```
Input Directory (flat)
        ↓
   [C Converter]
        ↓
 [GDCM Library]
        ↓
   [Validation]
   (Check PixelData)
        ↓
   [Conversion]
   (Explicit VR LE)
        ↓
Output Directory
```

Each file is:
1. Read and validated for DICOM content
2. Converted to Explicit VR Little Endian
3. Written to output with `.dcm` extension if needed
4. Failures are logged but don't stop processing

## Future Improvements

- [ ] Multi-threaded directory scanning
- [ ] Streaming for large pixel data
- [ ] Custom transfer syntax selection
- [ ] Python 3.12+ stable ABI build
