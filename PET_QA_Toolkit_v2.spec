# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for PET QA Toolkit v2.

This spec file packages PET_GUI.py into a standalone Windows executable
with all required dependencies, including asyncio support and bundled tools.

Build with: pyinstaller PET_QA_Toolkit_v2.spec
"""

from PyInstaller.utils.hooks import collect_data_files
import os

# Collect data files from packages that need them
datas = []
try:
    datas += collect_data_files('customtkinter')
except:
    pass

# Resolve paths relative to this spec file so packaging does not depend on the
# shell working directory used to invoke PyInstaller.
SPEC_DIR = os.path.abspath(globals().get('SPECPATH', os.getcwd()))
WORKSPACE_ROOT = SPEC_DIR

# Include bundled GDCM/DCMTK tools if present
dcmtk_bin = os.path.join(WORKSPACE_ROOT, 'dcmtk-3.6.9-win64-dynamic', 'bin')
if os.path.exists(dcmtk_bin):
    datas.append((dcmtk_bin, 'dcmtk-3.6.9-win64-dynamic/bin'))

# Include bundled GDCM converter
gdcm_bin = os.path.join(WORKSPACE_ROOT, 'pet_tools', 'helper', 'bin')
if os.path.exists(gdcm_bin):
    datas.append((gdcm_bin, 'pet_tools/helper/bin'))

# Include documentation PDFs
docs_dir = os.path.join(WORKSPACE_ROOT, 'docs')
if os.path.exists(docs_dir):
    datas.append((docs_dir, 'docs'))

# Include the root HTML documentation files searched by PET_GUI.py.
for html_name in ('PET_QA_Workbench.html', 'p_e_t_q_a_workbench.html', 'index.html'):
    html_path = os.path.join(WORKSPACE_ROOT, html_name)
    if os.path.exists(html_path):
        datas.append((html_path, '.'))

# Bundle CT_Analysis_Toolkit as raw source/support files.
# This package has no __init__.py (namespace package), so PyInstaller cannot
# collect it via collect_data_files. Bundle the directories that the imported
# modules may reach for at runtime.
ct_toolkit_root = os.path.join(WORKSPACE_ROOT, 'CT_Analysis_Toolkit')
for rel_dir in ('Modules', 'Config', 'Data', 'Lib'):
    src_dir = os.path.join(ct_toolkit_root, rel_dir)
    if os.path.exists(src_dir):
        datas.append((src_dir, f'CT_Analysis_Toolkit/{rel_dir}'))

# Hidden imports needed for:
# - asyncio (for async converter)
# - multiprocessing (for worker processes)
# - concurrent.futures (ProcessPoolExecutor)
# - tqdm (progress bars)
# - pydicom (DICOM handling)
# - customtkinter (GUI framework)
# - pet_tools (all helper modules)
hiddenimports = [
    'asyncio',
    'concurrent.futures',
    'multiprocessing',
    'multiprocessing.managers',
    'multiprocessing.util',
    'tqdm',
    'tqdm.std',
    'pydicom',
    'pydicom.dataelem',
    'pydicom.dataset',
    'customtkinter',
    'customtkinter.windows',
    'customtkinter.windows.widgets',
    'PIL',
    'PIL.Image',
    'zipfile',
    'json',
    'argparse',
    'shutil',
    'tempfile',
    'pathlib',
    # matplotlib backend — image_selection.py sets matplotlib.use('TkAgg') explicitly;
    # PyInstaller does not auto-collect backends referenced via use() string calls.
    'matplotlib.backends.backend_tkagg',
    # PET Tools modules
    'pet_tools',
    'pet_tools.convert_to_dicom',
    'pet_tools.extract_dicom_info',
    'pet_tools.suv_overlay_manual',
    'pet_tools.suv_overlay_auto',
    'pet_tools.suv_overlay_auto_center_single',
    'pet_tools.uniformity_scoring_manual',
    'pet_tools.uniformity_scoring_auto',
    'pet_tools.count_rate_performance',
    'pet_tools.z_axis_coregistration',
    'pet_tools.roi_axial_profile',
    'pet_tools.roi_statistics',
    'pet_tools.visualize_com_analysis',
    'pet_tools.dual_series_overlay',
    'pet_tools.z_axis_regression_analysis',
    'pet_tools.image_selection',
    'pet_tools.acr_specific_overlay',
    'pet_tools.acr_slice_selector',
    'pet_tools.ct_dicom_parameter_extractor',
    'pet_tools.pet_dicom_organizer',
    'pet_tools.run_from_manifest',
    'pet_tools.helper',
    'pet_tools.helper.flatten_input',
    'pet_tools.helper.gdcm_converter_wrapper',
    'pet_tools.helper.universal_dicom_converter',
    'pet_tools.helper.universal_dicom_organizer',
    'pet_tools.helper.manifest_builder',
    # CT Analysis Toolkit — imported transitively by suv_overlay_manual (and therefore
    # image_selection). CT_Analysis_Toolkit has no __init__.py so PyInstaller will not
    # auto-discover these modules; they must be listed explicitly.
    'CT_Analysis_Toolkit.Modules.find_phantom_center',
    'CT_Analysis_Toolkit.Modules.auto_center_and_hotcells',
    'CT_Analysis_Toolkit.Modules.HU_Module',
    'CT_Analysis_Toolkit.Modules.LowContrast_Module',
    'CT_Analysis_Toolkit.Modules.Picker_UI',
    'CT_Analysis_Toolkit.Modules.SpatialResolution_Module',
    'CT_Analysis_Toolkit.Modules.Uniformity_Module',
    'CT_Analysis_Toolkit.Modules.Utils',
]

# Explicitly bundle python313.dll — required when using Microsoft Store Python,
# which places the DLL in a protected directory that PyInstaller cannot auto-copy.
import glob as _glob
_py_dll_candidates = _glob.glob(
    r'C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13*\python313.dll'
)
binaries = [(_py_dll_candidates[0], '.')] if _py_dll_candidates else []

a = Analysis(
    ['PET_GUI.py'],
    pathex=[WORKSPACE_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PET_QA_Toolkit_v2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
