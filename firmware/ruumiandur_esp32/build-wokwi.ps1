[CmdletBinding()]
param(
    [string]$ArduinoCli = ""
)

$ErrorActionPreference = "Stop"

$sharedSecrets = Join-Path $PSScriptRoot "..\ruumiandur\secrets.h"
$generatedSecrets = Join-Path $PSScriptRoot "secrets.wokwi.generated.h"
$diagramTemplate = Join-Path $PSScriptRoot "diagram.template.json"
$generatedDiagram = Join-Path $PSScriptRoot "diagram.json"

if (-not (Test-Path -LiteralPath $sharedSecrets)) {
    throw "Shared configuration not found: $sharedSecrets"
}

function Get-CppStringValue {
    param(
        [Parameter(Mandatory)]
        [string]$Source,
        [Parameter(Mandatory)]
        [string]$Name
    )

    $escapedName = [regex]::Escape($Name)
    $pattern = '(?m)^\s*const\s+char\s*\*\s*' + $escapedName + '\s*=\s*"((?:\\.|[^"\\])*)"\s*;'
    $match = [regex]::Match($Source, $pattern)
    if (-not $match.Success) {
        throw "Could not read $Name from $sharedSecrets"
    }
    return [regex]::Unescape($match.Groups[1].Value)
}

$secretSource = Get-Content -Raw -LiteralPath $sharedSecrets
$apiUrl = Get-CppStringValue -Source $secretSource -Name "API_URL"

# Wokwi cannot see the physical access point. Use its built-in open network,
# but keep the API destination synchronized with the shared device settings.
$escapedApiUrl = $apiUrl.Replace('\', '\\').Replace('"', '\"')
$generatedHeader = @"
#pragma once

const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASSWORD = "";
const char* API_URL = "$escapedApiUrl";
"@
$generatedHeader | Set-Content -LiteralPath $generatedSecrets -Encoding utf8
Copy-Item -LiteralPath $diagramTemplate -Destination $generatedDiagram -Force

if (-not $ArduinoCli) {
    $installedCommand = Get-Command arduino-cli -ErrorAction SilentlyContinue
    if ($installedCommand) {
        $ArduinoCli = $installedCommand.Source
    } else {
        $bundledCli = "C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
        if (Test-Path -LiteralPath $bundledCli) {
            $ArduinoCli = $bundledCli
        }
    }
}

if (-not $ArduinoCli -or -not (Test-Path -LiteralPath $ArduinoCli)) {
    throw "arduino-cli was not found. Install Arduino IDE 2 or pass -ArduinoCli with its full path."
}

$buildPath = Join-Path $PSScriptRoot "build\wokwi"
New-Item -ItemType Directory -Force -Path $buildPath | Out-Null

& $ArduinoCli compile `
    --fqbn esp32:esp32:esp32 `
    --warnings all `
    --build-property "compiler.cpp.extra_flags=-DWOKWI_SIMULATION=1" `
    --build-path $buildPath `
    $PSScriptRoot

if ($LASTEXITCODE -ne 0) {
    throw "Wokwi firmware build failed with exit code $LASTEXITCODE."
}

Write-Host "Wokwi firmware ready: $buildPath"
Write-Host "Generated Wokwi-GUEST configuration using API_URL from firmware/ruumiandur/secrets.h"
