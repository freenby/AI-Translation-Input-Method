@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo    AI翻译输入法 - 打包脚本
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    pause
    exit /b 1
)

echo 当前解释器:
python -c "import sys; print(sys.executable)"
python --version
echo.

:: 检查并安装 PyInstaller（必须绑定当前 python）
echo [1/4] 检查 PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo      正在安装 PyInstaller...
    python -m pip install pyinstaller pyinstaller-hooks-contrib -i https://mirrors.aliyun.com/pypi/simple/
)

:: 安装项目依赖（绑定当前 python）
echo [2/4] 安装项目依赖...
python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

:: 清理旧的构建文件
echo [3/4] 清理旧文件...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

:: 使用当前 python 的 PyInstaller 打包（关键）
echo [4/4] 开始打包...
python -m PyInstaller build.spec --noconfirm --clean

if errorlevel 1 (
    echo.
    echo [错误] 打包失败！请检查错误信息。
    pause
    exit /b 1
)

echo.
echo ============================================
echo    打包完成！
echo ============================================
echo.
echo 输出目录: dist\AI翻译输入法\
echo.
echo 下一步:
echo   1. 安装 Inno Setup: https://jrsoftware.org/isinfo.php
echo   2. 用 Inno Setup 打开 installer.iss
echo   3. 点击 Build ^> Compile 生成安装程序
echo   4. 安装程序将输出到 installer_output 文件夹
echo.
pause
