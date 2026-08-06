@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Този файл ти трябва САМО ако browser източникът иска адрес, а не
rem приема път до файл. Пробвай първо без него.

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py"

if not defined PY (
  echo.
  echo   Python не е намерен на този компютър.
  echo.
  echo   Този файл ти трябва само ако browser източникът иска адрес.
  echo   Ако играта тръгва с файла - изобщо не ти трябва.
  echo.
  echo   Ако все пак ти трябва: свали Python от python.org и при
  echo   инсталацията сложи отметка "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

echo.
echo   Адресът за browser източника:
echo       http://127.0.0.1:8080/index.html
echo.
echo   Остави този прозорец отворен, докато стриймваш.
echo   Затвориш ли го, играта спира.
echo.
%PY% tools\serve.py
pause
