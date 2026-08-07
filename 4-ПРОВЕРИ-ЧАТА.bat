@echo off
chcp 65001 >nul
rem Проверка дали коментарите влизат. На страницата натисни
rem бутона "TikTokLive мост".
start "" "%~dp0game\chat-test.html"
