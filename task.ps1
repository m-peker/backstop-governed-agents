<#
.SYNOPSIS
    Developer loop for Windows, mirroring the Makefile target for target.

.DESCRIPTION
    Windows does not ship `make`. Rather than push every contributor through a
    toolchain install, this script exposes the same commands. The two are kept in
    step by a CI job that diffs their target lists.

.EXAMPLE
    ./task.ps1 setup
    ./task.ps1 check
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Target = 'help'
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Invoke-Step {
    param([string]$Label, [scriptblock]$Body)
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE" }
}

function Show-Help {
    Write-Host ""
    Write-Host "Backstop developer tasks" -ForegroundColor Green
    Write-Host ""
    $rows = @(
        @('setup',     'Install Python and Node dependencies'),
        @('up',        'Start the local data and observability plane'),
        @('down',      'Stop the local plane, keeping volumes'),
        @('logs',      'Tail the local plane'),
        @('dev',       'Run the API with reload'),
        @('web',       'Run the console'),
        @('seed',      'Write the synthetic dataset to seed-data/generated'),
        @('demo',      'Resolve one ticket end to end through the tool gateway'),
        @('test',      'Run the test suite'),
        @('lint',      'Lint'),
        @('fmt',       'Format'),
        @('typecheck', 'Type check'),
        @('check',     'Everything CI runs'),
        @('evals',     'Run the golden set'),
        @('redteam',   'Run the attack corpus'),
        @('governance','Check prompt hashes, rule citations and planted ambiguities'),
        @('clean',     'Remove caches and build output'),
        @('doctor',    'Report which required tools are missing')
    )
    foreach ($row in $rows) {
        Write-Host ("  {0,-12} {1}" -f $row[0], $row[1])
    }
    Write-Host ""
}

function Invoke-Doctor {
    $required = @(
        @{ Name = 'uv';     Hint = 'https://docs.astral.sh/uv/getting-started/installation/' },
        @{ Name = 'node';   Hint = 'https://nodejs.org - version 20 or newer' },
        @{ Name = 'npm';    Hint = 'ships with node' },
        @{ Name = 'docker'; Hint = 'Docker Desktop - required for postgres, redis, grafana' },
        @{ Name = 'git';    Hint = 'https://git-scm.com' }
    )
    $missing = 0
    foreach ($tool in $required) {
        $found = Get-Command $tool.Name -ErrorAction SilentlyContinue
        if ($found) {
            Write-Host ("  [ok]      {0,-8} {1}" -f $tool.Name, $found.Source) -ForegroundColor Green
        }
        else {
            $missing++
            Write-Host ("  [missing] {0,-8} {1}" -f $tool.Name, $tool.Hint) -ForegroundColor Yellow
        }
    }
    Write-Host ""
    if ($missing -gt 0) {
        Write-Host "$missing tool(s) missing. The API and tests run without docker;" -ForegroundColor Yellow
        Write-Host "readiness checks and the data plane do not." -ForegroundColor Yellow
    }
    else {
        Write-Host "All required tools present." -ForegroundColor Green
    }
}

switch ($Target.ToLowerInvariant()) {
    'help' { Show-Help }
    'doctor' { Invoke-Doctor }

    'setup' {
        Invoke-Step 'uv sync' { uv sync --all-packages }
        Invoke-Step 'npm install' { npm install }
    }
    'up' {
        Invoke-Step 'docker compose up' { docker compose up -d }
        Write-Host 'postgres :5432  redis :6379  prometheus :9090  grafana :3002'
    }
    'down' { Invoke-Step 'docker compose down' { docker compose down } }
    'logs' { docker compose logs -f --tail=100 }

    'dev' { uv run uvicorn backstop_api.main:create_app --factory --reload --host 0.0.0.0 --port 8000 }
    'web' { npm run dev --workspace '@backstop/web' }
    'seed' { Invoke-Step 'seed' { uv run python scripts/seed.py } }
    'demo' { Invoke-Step 'demo' { uv run python scripts/demo_ticket.py } }

    'test' { Invoke-Step 'pytest' { uv run pytest --cov --cov-report=term-missing } }
    'lint' {
        Invoke-Step 'ruff check' { uv run ruff check . }
        Invoke-Step 'ruff format --check' { uv run ruff format --check . }
    }
    'fmt' {
        Invoke-Step 'ruff format' { uv run ruff format . }
        Invoke-Step 'ruff check --fix' { uv run ruff check --fix . }
    }
    'typecheck' { Invoke-Step 'mypy' { uv run mypy apps packages mcp-servers } }
    'check' {
        & $PSCommandPath lint
        & $PSCommandPath typecheck
        & $PSCommandPath test
    }

    'evals' { Invoke-Step 'golden set' { uv run python -m evals.runners.golden } }
    'redteam' { Invoke-Step 'attack corpus' { uv run python -m evals.runners.redteam } }
    'governance' { Invoke-Step 'governance' { uv run python scripts/check_governance.py all } }

    'clean' {
        foreach ($path in @('.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', '.coverage')) {
            if (Test-Path $path) { Remove-Item -Recurse -Force $path }
        }
        Get-ChildItem -Recurse -Directory -Filter '__pycache__' |
            Remove-Item -Recurse -Force
        Write-Host 'Cleaned.' -ForegroundColor Green
    }

    default {
        Write-Host "Unknown target '$Target'." -ForegroundColor Red
        Show-Help
        exit 1
    }
}
