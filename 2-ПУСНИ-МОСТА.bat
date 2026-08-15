@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Мостът чете коментарите от TikTok и ги подава на играта.
rem Трябва да върви, докато стриймваш. Пусни него преди играта.

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py"
if not defined PY goto nopython

set "TIKTOK="
if exist "tiktok-user.txt" set /p TIKTOK=<tiktok-user.txt
call :clean
if defined TIKTOK goto remember

:ask
echo.
echo   Как е TikTok името ти? Без маймунка.
echo   Например: oneisthelonliestnumber69
echo.
set /p TIKTOK="   Име: "
call :clean
if not defined TIKTOK goto ask
echo.
echo   Запомних го. Следващия път няма да питам.
echo   (за смяна: изтрий файла tiktok-user.txt)
echo.

:remember
rem Записваме изчистеното име. Един залепен интервал при копиране
rem иначе трови всяко следващо пускане, не само това.
>tiktok-user.txt echo %TIKTOK%

echo   Проверявам дали библиотеката е налична ...
%PY% -c "import TikTokLive" >nul 2>nul
if errorlevel 1 goto install
goto run

:install
echo   Инсталирам я. Това става веднъж и трае минута-две.
echo.
%PY% -m pip install -r bridge\requirements.txt
echo.
%PY% -c "import TikTokLive" >nul 2>nul
if errorlevel 1 goto failed

:run
echo.
echo ==========================================================
echo   Мостът тръгва за @%TIKTOK%
echo.
echo   ОСТАВИ ТОЗИ ПРОЗОРЕЦ ОТВОРЕН, докато стриймваш.
echo   Затвориш ли го, играта спира да получава коментари.
echo ==========================================================
echo.
%PY% bridge\tiktok_bridge.py "@%TIKTOK%" --verbose
echo.
pause
exit /b

:failed
echo.
echo   Инсталацията не мина. Прати ми какво пише отгоре.
echo.
pause
exit /b 1

:nopython
echo.
echo   Python не е намерен на този компютър.
echo.
echo   Свали го от python.org и при инсталацията ЗАДЪЛЖИТЕЛНО
echo   сложи отметка "Add Python to PATH" на първия екран.
echo.
pause
exit /b 1

:clean
rem Маха интервалите и маймунката. Име в TikTok няма как да съдържа
rem интервал, така че махането им е безопасно и спасява копирането.
if not defined TIKTOK goto :eof
set "TIKTOK=%TIKTOK: =%"
if not defined TIKTOK goto :eof
if "%TIKTOK:~0,1%"=="@" set "TIKTOK=%TIKTOK:~1%"
goto :eof
