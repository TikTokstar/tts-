@echo off
chcp 65001 >nul
setlocal

rem ===================================================================
rem  Безопасно обновяване на бота.
rem
rem  Пусни го, ако TikTok спре да се свързва или гласът спре — обикновено
rem  значи, че TikTok или Microsoft са сменили нещо и вече има поправена
rem  версия на библиотеката.
rem
rem  1. Тегли последния код (git pull)
rem  2. Запомня сегашните версии на пакетите
rem  3. Обновява до най-новите в рамките на тестваните големи версии
rem  4. Проверява ги — и ако не минат, ВРЪЩА старите
rem ===================================================================

cd /d "%~dp0"
title Обновяване — Български TTS

echo.
echo   Обновяване на Български TTS
echo   ===========================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo   Ботът още не е инсталиран. Пусни първо run.bat.
    echo.
    pause
    exit /b 1
)
set "VENV_PY=.venv\Scripts\python.exe"

rem --- 1. Кодът ------------------------------------------------------
where git >nul 2>&1
if errorlevel 1 (
    echo   [ВНИМАНИЕ] git не е намерен — пропускам обновяването на кода.
) else (
    echo   Тегля последната версия на кода...
    git pull --ff-only
    if errorlevel 1 (
        echo   [ВНИМАНИЕ] Кодът не се обнови. Продължавам само с пакетите.
    )
)
echo.

rem --- 2. Снимка на сегашните версии ---------------------------------
"%VENV_PY%" -m pip freeze > ".venv\predi_obnovqvane.txt"
echo   Запомних сегашните версии ^(за връщане, ако нещо се счупи^).
echo.

rem --- 3. Обновяване -------------------------------------------------
echo   Обновявам пакетите...
"%VENV_PY%" -m pip install --upgrade pip --quiet
"%VENV_PY%" -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo.
    echo   [ГРЕШКА] Обновяването не мина. Връщам старите версии...
    "%VENV_PY%" -m pip install -r ".venv\predi_obnovqvane.txt" --quiet
    echo   Върнато. Провери интернет връзката и опитай пак.
    echo.
    pause
    exit /b 1
)
echo.

rem --- 4. Проверка ---------------------------------------------------
echo   Проверявам новите версии...
"%VENV_PY%" main.py --check
if errorlevel 1 (
    echo.
    echo   Новите версии НЕ минаха проверката. Връщам старите...
    "%VENV_PY%" -m pip install -r ".venv\predi_obnovqvane.txt" --quiet
    echo.
    "%VENV_PY%" main.py --check
    echo.
    echo   Старите версии са върнати. Прати ми текста от този прозорец.
    echo.
    pause
    exit /b 1
)

copy /y "requirements.txt" ".venv\requirements.installed.txt" >nul
echo.
echo   Готово. Пусни бота нормално ^(прекия път или run.bat^).
echo.
pause
endlocal
