@echo off
chcp 65001 >nul
echo.
echo ==========================================================
echo   Проверка защо играта не намира TikFinity
echo ==========================================================
echo.

echo [1] Върви ли изобщо TikFinity?
echo.
tasklist /fi "imagename eq TikFinity.exe" 2>nul | find /i "TikFinity" >nul
if %errorlevel%==0 (
  echo     ДА - програмата е отворена.
) else (
  tasklist 2>nul | find /i "tikfinity" >nul
  if errorlevel 1 (
    echo     НЕ - не намирам такъв процес. Отвори TikFinity.
  ) else (
    echo     ДА - намирам процес с това име.
  )
)
echo.

echo [2] Слуша ли нещо на порт 21213?
echo.
netstat -ano | findstr /c:":21213" | findstr /i "LISTENING" >nul
if %errorlevel%==0 (
  echo     ДА - нещо слуша. Играта трябва да може да се закачи.
  echo     Ако пак е червено, пиши ми.
) else (
  echo     НЕ - никой не слуша на 21213.
  echo.
  echo     Това е причината. TikFinity не излага локалния си
  echo     WebSocket. Или е изключен в настройките, или е
  echo     платена функция, или е на друг порт.
)
echo.

echo [3] Кои портове наблизо слушат:
echo.
netstat -ano | findstr /i "LISTENING" | findstr /r ":212[0-9][0-9] :80[0-9][0-9] :30[0-9][0-9]"
echo.
echo     Ако видиш непознат порт тук, пробвай него:
echo     отвори game\chat-test.html?source=tikfinity^&port=ЧИСЛОТО
echo.

echo ==========================================================
echo   Прати ми снимка на този прозорец.
echo ==========================================================
echo.
pause
