@echo off
chcp 65001 >nul
rem Отваря страницата за проверка на връзката с чата.
rem Там натискаш бутона TikFinity и пишеш нещо в чата на стрийма.
start "" "%~dp0game\chat-test.html"
