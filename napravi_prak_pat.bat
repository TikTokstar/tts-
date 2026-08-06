@echo off
chcp 65001 >nul
setlocal

rem ===================================================================
rem  Слага пряк път на работния плот. Пуска се ВЕДНЪЖ.
rem
rem  Самата работа е в napravi_prak_pat.ps1, а не тук: кирилицата не
rem  оцелява по пътя cmd -> powershell -Command и имената излизат
rem  "?????". Отделен .ps1 с BOM се чете правилно.
rem ===================================================================

cd /d "%~dp0"

echo.
echo   Правя пряк път на работния плот...

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0napravi_prak_pat.ps1"

if errorlevel 1 (
    echo   Направи го ръчно: десен бутон върху run.bat
    echo   -^> Изпрати до -^> Работен плот ^(пряк път^)
    echo.
    pause
    exit /b 1
)

echo   Оттук нататък: двоен клик върху "Български TTS" на плота.
echo.
echo   Съвет: в панела сложи отметка на
echo   "Свързвай се автоматично при пускане",
echo   за да не пипаш нищо повече.
echo.
pause
endlocal
