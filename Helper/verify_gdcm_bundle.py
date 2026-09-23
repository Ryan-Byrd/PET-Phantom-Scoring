import os

DLLS = [
    "gdcmCommon.dll",
    "gdcmDSED.dll",
    "gdcmIOD.dll",
    "gdcmMSFF.dll",
    "gdcmjpeg8.dll",
    "gdcmjpeg12.dll",
    "gdcmjpeg16.dll",
    "gdcmcharls.dll",
    "gdcmopenjpeg.dll",
    "gdcmexpat.dll",
    "gdcmzlib.dll",
    "gdcmuuid.dll",
]

BIN_DIR = os.path.join(os.path.dirname(__file__), "bin")

missing = []
for dll in DLLS + ["gdcmconv.exe"]:
    if not os.path.exists(os.path.join(BIN_DIR, dll)):
        missing.append(dll)

if missing:
    print("❌ GDCM BUNDLE INCOMPLETE:")
    for m in missing:
        print("   -", m)
else:
    print("✅ GDCM BUNDLE OK — all required files present.")
