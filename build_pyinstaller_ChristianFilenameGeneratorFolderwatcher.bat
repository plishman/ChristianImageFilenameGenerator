@echo off
setlocal

set "PYTHON_EXE=C:\Users\phill\anaconda3\envs\ChristianImageFilenameGenerator\python.exe"

"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean ChristianImageRenamerFolderWatcher.spec

if errorlevel 1 (
    echo.
    echo PyInstaller build failed.
    exit /b 1
)

echo.
echo PyInstaller build succeeded. Output: dist\ChristianImageRenamerFolderWatcher.exe
exit /b 0
