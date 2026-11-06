# Pull the base images needed by docker compose build, with retry.
#
# Why: docker.1ms.run and the other mirrors rate-limit and drop connections
# ("short read: expected N bytes but got M: unexpected EOF"), so a single
# docker pull often dies halfway. This retries per image and skips images
# that are already present.
#
# NOTE: keep this file pure ASCII. Windows PowerShell 5.1 reads .ps1 files
# using the ANSI code page, so UTF-8 Chinese comments break the parser.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools/pull_images.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools/pull_images.ps1 -IncludeMysql
param(
  [string]$Mirror = "docker.1ms.run",
  [int]$Attempts = 6,
  [switch]$IncludeMysql
)

$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
$logDir = Join-Path $root 'test-artifacts'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$images = @(
  'library/python:3.12-slim',
  'library/maven:3.9.9-eclipse-temurin-21',
  'library/eclipse-temurin:21-jre',
  'library/node:22-alpine',
  'library/nginx:alpine'
)
if ($IncludeMysql) { $images += 'library/mysql:8.0.39' }

function Test-HasImage([string]$ref) {
  $short = $ref -replace '^library/', ''
  $found = docker images --format '{{.Repository}}:{{.Tag}}' 2>$null | Select-String -SimpleMatch $short
  return [bool]$found
}

foreach ($img in $images) {
  $short = $img -replace '^library/', ''
  if (Test-HasImage $img) {
    Write-Host "[pull] present, skip: $short"
    continue
  }
  $target = "$Mirror/$img"
  $out = Join-Path $logDir ("pull-" + ($short -replace '[:/]', '-') + ".log")
  $ok = $false
  for ($i = 1; $i -le $Attempts; $i++) {
    Write-Host "[pull] attempt $i/$Attempts : $target"
    & docker pull $target *> $out
    if ($LASTEXITCODE -eq 0 -and (Test-HasImage $img)) {
      Write-Host "[pull] ok: $short"
      $ok = $true
      break
    }
    $tail = (Get-Content $out -Tail 1 -ErrorAction SilentlyContinue) -join ''
    Write-Host "[pull] failed: $tail"
    Start-Sleep -Seconds (10 * $i)
  }
  if (-not $ok) { Write-Host "[pull] giving up after $Attempts attempts: $short" }
}

Write-Host "[pull] images now:"
docker images --format '  {{.Repository}}:{{.Tag}} {{.Size}}'
