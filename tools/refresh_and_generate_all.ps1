Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

param(
	[switch]$StopExisting = $true
)

function Get-VenvPythonPath {
	$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
	$py = Join-Path $repoRoot '.venv\Scripts\python.exe'
	if (-not (Test-Path $py)) {
		throw "venv Python not found: $py"
	}
	return (Resolve-Path $py).Path
}

function Stop-GenerateProcesses {
	# Stop any stale generator processes to avoid duplicate writes / confusing mtime checks.
	$procs = Get-CimInstance Win32_Process |
	Where-Object { $_.CommandLine -and ($_.CommandLine -match 'tools\\generate_numbers\.py') }

	foreach ($p in $procs) {
		try {
			Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
			Write-Host "[info] Stopped stale generator PID=$($p.ProcessId)"
		}
		catch {
			Write-Host "[warn] Failed to stop PID=$($p.ProcessId): $($_.Exception.Message)"
		}
	}
}

function Test-NetworkOk([string]$pythonExe) {
	$code = @'
import sys
import urllib.request

def ok(url: str) -> bool:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "CheatSheet-of_Numbers/1.0 (tools/refresh_and_generate_all.ps1)"
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            r.read(2048)
        return True
    except Exception as e:
        print("[net]", type(e).__name__, str(e))
        return False

w_ok = ok("https://ja.wikipedia.org/w/api.php?action=query&titles=31&prop=info&format=json")
d_ok = ok("https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q31&format=json")

if w_ok and d_ok:
    print("[net] ok")
    raise SystemExit(0)

print("[net] not ok")
raise SystemExit(2)
'@

	& $pythonExe -c $code
	return ($LASTEXITCODE -eq 0)
}

function Get-NumberFilePath([int]$n) {
	$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
	$h = [Math]::Floor($n / 100)
	$name = $n.ToString('000') + '.md'
	return Join-Path $repoRoot (Join-Path (Join-Path 'numbers' ("{0}xx" -f $h)) $name)
}

function Print-MTime([string]$pythonExe, [int]$n) {
	$filePath = Get-NumberFilePath $n
	$code = @"
from pathlib import Path
import datetime as dt
p = Path(r'''$filePath''')
s = p.stat()
print(f"{p.as_posix()}\t{dt.datetime.fromtimestamp(s.st_mtime).isoformat(timespec='seconds')}\t{s.st_size}")
"@
	& $pythonExe -c $code
}

$pythonExe = Get-VenvPythonPath

if ($StopExisting) {
	Stop-GenerateProcesses
}

$ranges = @(
	@{ label = '0-99'; start = 0; end = 99 },
	@{ label = '100-199'; start = 100; end = 199 },
	@{ label = '200-299'; start = 200; end = 299 },
	@{ label = '300-399'; start = 300; end = 399 },
	@{ label = '400-499'; start = 400; end = 499 },
	@{ label = '500-599'; start = 500; end = 599 },
	@{ label = '600-699'; start = 600; end = 699 },
	@{ label = '700-799'; start = 700; end = 799 },
	@{ label = '800-899'; start = 800; end = 899 },
	@{ label = '900-999'; start = 900; end = 999 }
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Push-Location $repoRoot
try {
	foreach ($r in $ranges) {
		$label = $r.label
		$start = [int]$r.start
		$end = [int]$r.end

		Write-Host "\n== range $label ==" -ForegroundColor Cyan

		$netOk = Test-NetworkOk $pythonExe
		if ($netOk) {
			Write-Host "[mode] online + refresh" -ForegroundColor Green
		}
		else {
			Write-Host "[mode] offline (cache only)" -ForegroundColor Yellow
		}

		Write-Host "[before] mtimes" -ForegroundColor DarkGray
		Print-MTime $pythonExe $start
		Print-MTime $pythonExe $end

		$args = @(
			'tools/generate_numbers.py',
			'--wikipedia-sections',
			'--only', $label
		)

		if ($netOk) {
			$args += @('--refresh-wikidata', '--refresh-wikipedia', '--refresh-wikipedia-sections')
		}
		else {
			$args += @('--offline')
		}

		& $pythonExe @args
		if ($LASTEXITCODE -ne 0) {
			throw "generate_numbers.py failed for range $label (exit=$LASTEXITCODE)"
		}

		Write-Host "[after] mtimes" -ForegroundColor DarkGray
		Print-MTime $pythonExe $start
		Print-MTime $pythonExe $end

		if ($StopExisting) {
			Stop-GenerateProcesses
		}
	}

	Write-Host "\n== internal link check ==" -ForegroundColor Cyan
	& $pythonExe 'tools/check_internal_links.py'
	if ($LASTEXITCODE -ne 0) {
		throw "check_internal_links.py failed (exit=$LASTEXITCODE)"
	}

	Write-Host "\n[done] refresh/generate completed" -ForegroundColor Green
}
finally {
	Pop-Location
}
