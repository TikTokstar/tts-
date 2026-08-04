@echo off
chcp 65001 >nul
setlocal

rem ===================================================================
rem  Български TTS бот за TikTok Live
rem  Този файл прави всичко: среда, пакети, пускане.
rem  Просто щракни два пъти върху него.
rem ===================================================================

cd /d "%~dp0"
title Български TTS за TikTok Live

echo.
echo   Български TTS за TikTok Live
echo   ============================
echo.

rem --- 1. Има ли Python? ---------------------------------------------
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo   [ГРЕШКА] Python не е намерен.
    echo.
    echo   Изтегли Python 3.11 от https://www.python.org/downloads/
    echo   При инсталацията ЗАДЪЛЖИТЕЛНО сложи отметка
    echo   "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

rem --- 2. Виртуална среда --------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo   Създавам виртуална среда... ^(еднократно, около минута^)
    %PY% -m venv .venv
    if errorlevel 1 (
        echo   [ГРЕШКА] Средата не се създаде.
        pause
        exit /b 1
    )
    set "FRESH=1"
)

set "VENV_PY=.venv\Scripts\python.exe"

rem --- 3. Пакети -----------------------------------------------------
rem Инсталираме при първо пускане. За да ги обновиш после, изтрий
rem файла .venv\.installed и пусни run.bat пак.
set "NEED_INSTALL="
if defined FRESH set "NEED_INSTALL=1"
if not exist ".venv\.installed" set "NEED_INSTALL=1"

if defined NEED_INSTALL (
    echo   Инсталирам пакетите... ^(еднократно^)
    echo.
    "%VENV_PY%" -m pip install --upgrade pip --quiet
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo   [ГРЕШКА] Пакетите не се инсталираха.
        echo   Провери интернет връзката и пусни файла пак.
        pause
        exit /b 1
    )
    echo готово> ".venv\.installed"
    echo.
    echo   Пакетите са готови.
    echo.
)

rem --- 4. Настройки --------------------------------------------------
if not exist ".env" (
    if exist ".env.example" copy ".env.example" ".env" >nul
)

rem --- 5. Бърза проверка на транслитерацията -------------------------
echo   Проверявам транслитерацията...
"%VENV_PY%" -c "import translit; assert translit.transliterate('kak si be')=='как си бе'; print('   OK: kak si be -> как си бе')"
if errorlevel 1 (
    echo   [ВНИМАНИЕ] Проверката не мина, но продължавам.
)
echo.

rem --- 6. Пускане ----------------------------------------------------
echo   Пускам бота. Панелът се отваря на http://localhost:8777
echo   За спиране: затвори този прозорец или натисни Ctrl+C.
echo.

"%VENV_PY%" main.py %*

set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
    echo.
    echo   Ботът спря с код %EXITCODE%.
    echo   Ако е грешка, погледни съобщенията по-горе.
    echo.
)
pause
endlocal
