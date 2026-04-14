@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt
pyinstaller --noconfirm --clean --onedir --distpath dist_v5 --windowed --name LiveCaptionsRecorder ^
  --add-data "C:\Users\111\miniforge3\Library\lib\tcl8.6;tcl8.6" ^
  --add-data "C:\Users\111\miniforge3\Library\lib\tk8.6;tk8.6" ^
  --add-binary "C:\Users\111\miniforge3\Library\bin\tcl86t.dll;." ^
  --add-binary "C:\Users\111\miniforge3\Library\bin\tk86t.dll;." ^
  --add-binary "C:\Users\111\miniforge3\Library\bin\ffi-8.dll;." ^
  --add-binary "C:\Users\111\miniforge3\Library\bin\liblzma.dll;." ^
  --add-binary "C:\Users\111\miniforge3\Library\bin\libbz2.dll;." ^
  --add-binary "C:\Users\111\miniforge3\Library\bin\libcrypto-3-x64.dll;." ^
  app.py
echo.
echo Build finished:
echo %cd%\dist_v5\LiveCaptionsRecorder\LiveCaptionsRecorder.exe
endlocal
