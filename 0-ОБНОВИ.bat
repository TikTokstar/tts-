@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ==========================================================
echo   Обновяване на Думички
echo ==========================================================
echo.
echo   Сваля последната версия върху тази папка.
echo   Името ти в tiktok-user.txt се пази.
echo   Старите настройки се пазят като game\config-предишен.js
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\обнови.ps1"

echo.
pause
