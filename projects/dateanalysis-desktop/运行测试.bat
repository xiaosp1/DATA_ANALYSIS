@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found.
    pause
    exit /b 1
)
set QT_QPA_PLATFORM=offscreen
".venv\Scripts\python.exe" -m pytest tests/test_scale_feature.py tests/test_cross_category.py tests/test_descriptive_service.py -q -W error
echo.
echo === UI smoke 韣销需题替有礻｜笫呈我量辐芄python tests/ui_smoke_test.py ===
pause
