# Слага пряк път "Български TTS" на работния плот.
# Файлът Е ЗАПАЗЕН С BOM — PowerShell 5.1 чете .ps1 като UTF-8 само с BOM.
#
# ЗАЩО В ДВЕ СТЪПКИ: WScript.Shell е стар COM обект и прекарва пътя през
# ANSI кодовата страница на системата. Ако "Език за програми без Unicode"
# не е български, кирилицата в името става "?" ОЩЕ ПРЕДИ записа, а "?" е
# забранен символ в имена на файлове — оттам и провалът на Save().
# Затова: създаваме с латинско име през COM, после преименуваме през
# .NET (Move-Item), който работи с Unicode без уговорки.

$ErrorActionPreference = "Stop"

$NAME_BG = "Български TTS.lnk"
$NAME_TMP = "TikTok-TTS.lnk"

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

    $tmp = Join-Path $desktop $NAME_TMP
    $final = Join-Path $desktop $NAME_BG

    # Стъпка 1: през COM, само с латински символи в пътя.
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($tmp)
    $sc.TargetPath       = $target
    $sc.WorkingDirectory = $root
    $sc.IconLocation     = "$env:SystemRoot\System32\SHELL32.dll,138"
    $sc.Save()

    if (-not (Test-Path $tmp)) {
        throw "Прекият път не се записа."
    }

    # Стъпка 2: преименуване през .NET — тук кирилицата минава.
    try {
        if (Test-Path $final) { Remove-Item $final -Force }
        Move-Item -LiteralPath $tmp -Destination $final -Force
        $made = $final
    }
    catch {
        # Ако и това не стане, оставяме работещия пряк път с латинско име.
        $made = $tmp
    }

    if (-not (Test-Path -LiteralPath $made)) {
        throw "Прекият път изчезна след преименуването."
    }

    Write-Host ""
    Write-Host "   Готово: $made"
    Write-Host ""
    exit 0
}
catch {
    Write-Host ""
    Write-Host "   [ГРЕШКА] $($_.Exception.Message)"
    Write-Host ""
    exit 1
}
