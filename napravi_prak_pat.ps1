# -*- coding: utf-8 -*-
# Слага пряк път "Български TTS" на работния плот.
# Файлът Е ЗАПАЗЕН С BOM нарочно — Windows PowerShell 5.1 чете .ps1 като
# UTF-8 само когато има BOM. Без него кирилицата се разпада на "?????".

$ErrorActionPreference = "Stop"

try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    if ([string]::IsNullOrWhiteSpace($desktop)) {
        throw "Работният плот не беше намерен."
    }

    $root = Split-Path -Parent $MyInvocation.MyCommand.Path
    $target = Join-Path $root "run.bat"
    if (-not (Test-Path $target)) {
        throw "Липсва run.bat в $root"
    }

    $link = Join-Path $desktop "Български TTS.lnk"

    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($link)
    $sc.TargetPath        = $target
    $sc.WorkingDirectory  = $root
    $sc.IconLocation      = "$env:SystemRoot\System32\SHELL32.dll,138"
    $sc.Description       = "Български TTS бот за TikTok Live"
    $sc.Save()

    if (-not (Test-Path $link)) {
        throw "Прекият път не се записа."
    }

    Write-Host ""
    Write-Host "   Готово: $link"
    Write-Host ""
    exit 0
}
catch {
    Write-Host ""
    Write-Host "   [ГРЕШКА] $($_.Exception.Message)"
    Write-Host ""
    exit 1
}
