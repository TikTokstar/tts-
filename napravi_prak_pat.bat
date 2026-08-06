@echo off
chcp 65001 >nul
setlocal

rem ===================================================================
rem  Слага пряк път на работния плот.
rem  Пуска се ВЕДНЪЖ. После ботът тръгва с двоен клик от плота.
rem ===================================================================

cd /d "%~dp0"

set "TARGET=%~dp0run.bat"
set "ICON=%SystemRoot%\System32\SHELL32.dll,138"

echo.
echo   Правя пряк път на работния плот...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$link = Join-Path $desktop 'Български TTS.lnk';" ^
  "$shell = New-Object -ComObject WScript.Shell;" ^
  "$sc = $shell.CreateShortcut($link);" ^
  "$sc.TargetPath = '%TARGET%';" ^
  "$sc.WorkingDirectory = '%~dp0';" ^
  "$sc.IconLocation = '%ICON%';" ^
  "$sc.Description = 'Български TTS бот за TikTok Live';" ^
  "$sc.Save();" ^
  "Write-Host ('   Готово: ' + $link)"

if errorlevel 1 (
    echo.
    echo   [ГРЕШКА] Прекият път не се направи.
    echo   Направи го ръчно: десен бутон върху run.bat
    echo   -^> Изпрати до -^> Работен плот ^(пряк път^)
    echo.
    pause
    exit /b 1
)

echo.
echo   Оттук нататък: двоен клик върху "Български TTS" на плота.
echo.
echo   Съвет: в панела сложи отметка на
echo   "Свързвай се автоматично при пускане",
echo   за да не пипаш нищо повече.
echo.
pause
endlocal
