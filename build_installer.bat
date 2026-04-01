@echo off
echo ============================================
echo    AI Translation IME - Build Script
echo ============================================
echo.

python --version
if errorlevel 1 (
    echo Python not found!
    pause
    exit /b 1
)

echo.
echo [1/4] Installing dependencies...
python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

echo.
echo [2/4] Installing PyInstaller...
python -m pip install pyinstaller -i https://mirrors.aliyun.com/pypi/simple/

echo.
echo [3/4] Cleaning old files...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

echo.
echo [4/4] Building...
python -m PyInstaller build.spec --noconfirm --clean

echo.
echo ============================================
echo    Done! Check dist folder.
echo ============================================
echo.
echo Next: Use Inno Setup to compile installer.iss
pause
