# Сваля последната версия и я слага върху текущата папка.
#
# Пуска се от 0-ОБНОВИ.bat, не се стартира на ръка.
#
# Какво пази:
#   tiktok-user.txt   - името ти; не е в хранилището, значи не се пипа
#   config.js         - презаписва се, но старият се пази до него
#
# Защо PowerShell, а не всичко в .bat: PowerShell прочита целия скрипт в
# паметта преди да го изпълни. Ако обновяването презапише самия скрипт по
# средата, нищо не се обърква.

$ErrorActionPreference = 'Stop'

$url  = 'https://github.com/TikTokstar/tts-/archive/refs/heads/claude/bulgarian-dumichki-tiktok-lq2kbf.zip'
$here = Split-Path -Parent $PSScriptRoot     # папката на играта, не tools\

function Say($text) { Write-Host "  $text" }

try {
    Say 'Свалям последната версия ...'

    $tmp = Join-Path $env:TEMP ('dumichki-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    $zip = Join-Path $tmp 'new.zip'

    # TLS 1.2 - на по-стари Windows по подразбиране е изключен и GitHub отказва.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing

    Say 'Разархивирам ...'
    Expand-Archive -Path $zip -DestinationPath $tmp -Force

    $src = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
    if (-not $src) { throw 'Архивът излезе празен.' }

    # Настройките се презаписват, но старите остават до тях - ако си пипал
    # цветове или времена, не изчезват безследно.
    $config = Join-Path $here 'game\config.js'
    if (Test-Path $config) {
        Copy-Item $config (Join-Path $here 'game\config-предишен.js') -Force
        Say 'Старите настройки са запазени като game\config-предишен.js'
    }

    # Старите стартери се махат: между версиите се преномерираха и иначе
    # остават стари файлове с подвеждащи имена.
    Get-ChildItem -Path $here -Filter '*.bat' |
        Where-Object { $_.Name -ne '0-ОБНОВИ.bat' } |
        Remove-Item -Force

    Say 'Слагам новото ...'
    Get-ChildItem -Path $src.FullName -Force |
        Where-Object { $_.Name -ne '0-ОБНОВИ.bat' } |
        ForEach-Object {
            Copy-Item $_.FullName -Destination $here -Recurse -Force
        }

    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host ''
    Say 'Готово. Папката е обновена.'
    Write-Host ''
}
catch {
    Write-Host ''
    Say 'Обновяването не мина.'
    Say $_.Exception.Message
    Write-Host ''
    Say 'Свали архива на ръка от:'
    Say $url
    Write-Host ''
    exit 1
}
