# Pull the four Milvus standalone images, trying mirrors in order.
#
# Why this script exists: registry-1.docker.io is blocked on this machine, and
# minio's official repo is unavailable on every mirror that was probed. The
# mapping below is the combination that actually worked; keep it in sync with
# the "image acquisition" note at the top of deploy/milvus/docker-compose.yml.
#
# ASCII only on purpose: Windows PowerShell 5.1 reads .ps1 with the ANSI code
# page, so UTF-8 Chinese comments break parsing ("Array index expression is
# missing or not valid").
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools/pull_milvus.ps1
#   powershell -ExecutionPolicy Bypass -File tools/pull_milvus.ps1 -SkipExisting

param(
    [switch]$SkipExisting
)

$ErrorActionPreference = 'Continue'

# target image -> ordered list of sources to try
$plan = @(
    @{
        Target  = 'quay.io/coreos/etcd:v3.5.13'
        Sources = @('quay.io/coreos/etcd:v3.5.13')
    },
    @{
        Target  = 'minio/minio:RELEASE.2024-04-18T19-09-19Z'
        Sources = @(
            'minio/minio:RELEASE.2024-04-18T19-09-19Z',
            'dockerproxy.net/bitnamilegacy/minio:2024.4.18'
        )
    },
    @{
        Target  = 'milvusdb/milvus:v3.0.0'
        Sources = @(
            'milvusdb/milvus:v3.0.0',
            'dockerproxy.net/milvusdb/milvus:v3.0.0'
        )
    },
    @{
        Target  = 'zilliz/attu:v3.0.0'
        Sources = @(
            'zilliz/attu:v3.0.0',
            'dockerproxy.net/zilliz/attu:v3.0.0'
        )
    }
)

function Test-Image([string]$name) {
    docker image inspect $name *> $null
    return ($LASTEXITCODE -eq 0)
}

$failed = @()

foreach ($item in $plan) {
    $target = $item.Target
    if ($SkipExisting -and (Test-Image $target)) {
        Write-Host "[skip] $target already present"
        continue
    }

    $done = $false
    foreach ($src in $item.Sources) {
        Write-Host "[pull] $src"
        docker pull $src
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[pull] failed: $src"
            continue
        }
        if ($src -ne $target) {
            docker tag $src $target
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[tag] failed: $src -> $target"
                continue
            }
            Write-Host "[tag] $src -> $target"
        }
        $done = $true
        break
    }

    if (-not $done) {
        $failed += $target
        Write-Host "[miss] $target : no source worked"
    }
}

Write-Host ''
docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}' |
    Select-String -Pattern 'etcd|minio|milvus|attu'

if ($failed.Count -gt 0) {
    Write-Host ''
    Write-Host "[result] FAILED: $($failed -join ', ')"
    Write-Host '[hint] minio official repo is blocked here; the bitnamilegacy image needs'
    Write-Host '       user: "0" in deploy/milvus/docker-compose.yml or it cannot write its volume.'
    exit 1
}

Write-Host ''
Write-Host '[result] OK - all four images present. Next:'
Write-Host '       docker compose -f deploy/milvus/docker-compose.yml up -d'
exit 0
