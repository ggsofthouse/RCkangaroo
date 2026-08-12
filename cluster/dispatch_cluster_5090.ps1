param(
    [Parameter(Mandatory = $true)] [string] $HostsCsv,
    [Parameter(Mandatory = $true)] [string] $KeyPath,
    [ValidateSet("benchmark", "p100-residue20")] [string] $Mode = "benchmark",
    [int] $Seconds = 30,
    [int] $RangeBits = 139,
    [int] $DpBits = 20,
    [int] $InvSm = 10,
    [string] $ResultsDir = ".\cluster-results"
)

$ErrorActionPreference = "Stop"
$repoUrl = "https://github.com/ggsofthouse/RCkangaroo.git"
$remoteRepo = "/workspace/RCkangaroo-cluster"
$hosts = @(Import-Csv -LiteralPath $HostsCsv)
if ($hosts.Count -eq 0) { throw "Hosts CSV is empty" }
if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) { throw "SSH key not found: $KeyPath" }
New-Item -ItemType Directory -Path $ResultsDir -Force | Out-Null
$resolvedKey = (Resolve-Path -LiteralPath $KeyPath).Path

$runs = foreach ($node in $hosts) {
    foreach ($field in @("name", "host", "port", "user")) {
        if (-not $node.$field) { throw "Missing '$field' in hosts CSV" }
    }
    if ($node.name -notmatch '^[A-Za-z0-9._-]+$') { throw "Unsafe node name: $($node.name)" }
    if ($node.port -notmatch '^\d+$') { throw "Invalid SSH port for $($node.name)" }
    $stdout = Join-Path $ResultsDir "$($node.name).stdout.log"
    $stderr = Join-Path $ResultsDir "$($node.name).stderr.log"
    $remote = 'set -euo pipefail; if [ ! -d ''{0}/.git'' ]; then git clone --depth 1 ''{1}'' ''{0}''; fi; cd ''{0}''; test -z "$(git status --porcelain)" || {{ echo dirty-repo >&2; exit 3; }}; git fetch origin main; git checkout main; git merge --ff-only origin/main; chmod +x cluster/cluster_5090_node.sh; RESULT_DIR=/workspace/rck-cluster-results cluster/cluster_5090_node.sh ''{2}'' ''{3}'' ''{4}'' ''{5}'' ''{6}''' -f $remoteRepo, $repoUrl, $Mode, $Seconds, $RangeBits, $DpBits, $InvSm
    $args = @("-i", $resolvedKey, "-p", [string]$node.port, "-o", "StrictHostKeyChecking=accept-new", "$($node.user)@$($node.host)", "bash", "-lc", $remote)
    $proc = Start-Process ssh -ArgumentList $args -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    [pscustomobject]@{ Node=$node; Process=$proc; Stdout=$stdout; Stderr=$stderr }
}

foreach ($run in $runs) {
    $run.Process.WaitForExit()
    if ($run.Process.ExitCode -ne 0) {
        Write-Warning "$($run.Node.name) failed: exit $($run.Process.ExitCode); see $($run.Stderr)"
        continue
    }
    $archive = Join-Path $ResultsDir "$($run.Node.name).tar.gz"
    & scp -i $resolvedKey -P $run.Node.port "$($run.Node.user)@$($run.Node.host):/workspace/rck-cluster-results/*_$Mode.tar.gz" $archive
    if ($LASTEXITCODE -ne 0) { Write-Warning "Could not download $($run.Node.name) results" }
}
Write-Host "Finished. Results: $(Resolve-Path -LiteralPath $ResultsDir)"
