@echo off
chcp 65001 > nul
title AI翻译输入法

:: 检查 Python 是否可用
python --version > nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10 或以上版本。
    pause
    exit /b
)

:: 安装依赖（首次运行）
echo 正在检查依赖包...
pip install -r requirements.txt -q

:: 启动程序
echo 启动 AI翻译输入法...
pythonw main.py

:: 如果 pythonw 不存在则回退到 python
if errorlevel 1 (
    python main.py
)
