@echo off
setlocal
echo [INFO] Checking for requirements.txt...
if exist "requirements.txt" (
  echo [INFO] Installing modules from requirements.txt...
  "C:\Users\KendallWilliams\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m pip install -r "requirements.txt"
) else (
  echo [INFO] No requirements.txt found. Skipping installs.
)
echo [INFO] Done.
endlocal
