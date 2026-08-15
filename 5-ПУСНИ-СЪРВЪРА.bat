@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Трябва ти САМО ако browser източникът иска адрес, а не приема
rem път до файл. Пробвай първо без него.

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py"
if not defined PY goto nopython

echo.
echo   Сървър за папката:
echo   %~dp0
echo.
%PY% tools\serve.py
pause
exit /b

:nopython
echo.
echo   Python не е намерен. Свали го от python.org и сложи
echo   отметка "Add Python to PATH".
echo.
pause
exit /b 1
