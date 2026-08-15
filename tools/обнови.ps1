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
#
# ВНИМАНИЕ: този файл ЗАДЪЛЖИТЕЛНО се пази с UTF-8 BOM. Windows PowerShell
# 5.1 чете .ps1 без BOM като ANSI, кирилицата се разпада на боклук и
# скриптът дори не се разбира - кавичките в развалените низове го чупят
# още при разчитането. Затова и .gitattributes го маркира като двоичен.
#
# ЧАСТНО ХРАНИЛИЩЕ: докато проектът е частен, свалянето иска пропуск.
# Браузърът го има от влизането в GitHub, но Invoke-WebRequest - не, и
# връща 404, все едно клонът не съществува. Или сложи token до скрипта
# (виж по-долу), или направи хранилището публично, или сваляй на ръка.

$ErrorActionPreference = 'Stop'

$owner  = 'TikTokstar'
$repo   = 'tts-'
$branch = 'claude/bulgarian-dumichki-tiktok-lq2kbf'

$url    = "https://codeload.github.com/$owner/$repo/zip/refs/heads/$branch"
$byHand = "https://github.com/$owner/$repo/archive/refs/heads/$branch.zip"

$here = Split-Path -Parent $PSScriptRoot     # папката на играта, не tools\
$self = '0-ОБНОВИ.bat'                       # него го върти cmd.exe точно сега

function Say($text) { Write-Host "  $text" }

try {
    Say 'Свалям последната версия ...'

    $tmp = Join-Path $env:TEMP ('dumichki-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    $zip = Join-Path $tmp 'new.zip'

    # TLS 1.2 - на по-стари Windows по подразбиране е изключен и GitHub отказва.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    # Пропуск, ако си сложил такъв. Файлът не влиза в хранилището.
    $headers = @{}
    $tokenFile = Join-Path $here 'github-token.txt'
    if (Test-Path $tokenFile) {
        $token = (Get-Content $tokenFile -Raw).Trim()
        if ($token) { $headers['Authorization'] = "token $token" }
    }

    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -Headers $headers

    # Всеки zip започва с PK. Ако GitHub е върнал страница за вход или
    # "404: Not Found", файлът е текст - Expand-Archive би се оплакал от
    # "повреден архив" и би пратил да се търси несъществуващ проблем.
    $head = [System.IO.File]::ReadAllBytes($zip) | Select-Object -First 2
    if ($head.Count -lt 2 -or $head[0] -ne 0x50 -or $head[1] -ne 0x4B) {
        throw 'GitHub не върна архив. Най-вероятно хранилището е частно и свалянето иска пропуск.'
    }

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
        Where-Object { $_.Name -ne $self } |
        Remove-Item -Force

    Say 'Слагам новото ...'
    Get-ChildItem -Path $src.FullName -Force |
        Where-Object { $_.Name -ne $self } |
        ForEach-Object {
            Copy-Item $_.FullName -Destination $here -Recurse -Force
        }

    # Предпазна мрежа: ако сравнението по име някога се провали, горният ред
    # трие обновяването и следващият не го връща. Тогава оставаш без начин
    # да се обновиш - затова се проверява изрично.
    $selfPath = Join-Path $here $self
    if (-not (Test-Path $selfPath)) {
        $fromZip = Join-Path $src.FullName $self
        if (Test-Path $fromZip) { Copy-Item $fromZip $selfPath -Force }
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
    Say 'Свали на ръка: отвори този адрес в браузъра, в който си влязъл в GitHub:'
    Write-Host ''
    Say $byHand
    Write-Host ''
    Say 'Адресът работи от браузър, защото там пропускът ти вече е наличен.'
    Write-Host ''
    exit 1
}
