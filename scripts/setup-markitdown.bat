@echo off
REM Evolux - markitdown setup script
REM Installs markitdown for file-to-markdown conversion (PDF, DOCX, PPTX, etc.)

echo.
echo ========================================
echo  Evolux - markitdown Setup
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.9+ first.
    echo         https://www.python.org/downloads/
    exit /b 1
)

echo [1/2] Installing markitdown...
pip install "markitdown[all]" --quiet
if %errorlevel% neq 0 (
    echo [WARN] Full install failed, trying basic...
    pip install markitdown --quiet
)

echo [2/2] Verifying installation...
markitdown --version >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo [OK] markitdown installed successfully!
    echo.
    echo Supported formats:
    echo   PDF, DOCX, PPTX, XLSX, HTML, CSV, JSON, XML
    echo   Images (EXIF + OCR), Audio (transcription)
    echo   ZIP, YouTube, EPUB, Email
) else (
    echo.
    echo [WARN] markitdown CLI not in PATH, but Python package is installed.
    echo        Evolux will use Python API as fallback.
)

echo.
echo Setup complete!
