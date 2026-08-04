# Script PowerShell para rodar Worker Local na RTX 2060 SUPER
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "🦘 RCKangaroo Worker Local - Conexao Pool" -ForegroundColor Yellow
Write-Host "Servidor: https://valyrafi.com.br" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Lê WORKER_TOKEN do .env
$EnvFile = Join-Path $PSScriptRoot ".env"
$WorkerToken = ""
foreach ($line in Get-Content $EnvFile) {
    if ($line -match "^WORKER_TOKEN=(.+)$") { $WorkerToken = $Matches[1] }
}
if ([string]::IsNullOrWhiteSpace($WorkerToken)) {
    Write-Host "❌ WORKER_TOKEN não encontrado no .env!" -ForegroundColor Red
    exit 1
}

$PuzzleNum = Read-Host "👉 Digite o numero do Puzzle (ex: 140) [padrao: 140]"
if ([string]::IsNullOrWhiteSpace($PuzzleNum)) { $PuzzleNum = "140" }

$StartPct = Read-Host "👉 Porcentagem INICIAL do range (0 a 100) [padrao: 85.0]"
if ([string]::IsNullOrWhiteSpace($StartPct)) { $StartPct = "85.0" }

$EndPct = Read-Host "👉 Porcentagem FINAL do range (0 a 100) [padrao: 100.0]"
if ([string]::IsNullOrWhiteSpace($EndPct)) { $EndPct = "100.0" }

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "🚀 Iniciando Worker Local..." -ForegroundColor Green
Write-Host "Puzzle:  #$PuzzleNum" -ForegroundColor White
Write-Host "Range:   $StartPct% ate $EndPct%" -ForegroundColor White
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

Set-Location $PSScriptRoot
python pool/worker/worker.py --server https://valyrafi.com.br --name "Local-RTX2060" --puzzle $PuzzleNum --start-pct $StartPct --end-pct $EndPct --token $WorkerToken --non-interactive

