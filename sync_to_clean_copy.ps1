<#
Synchronise uniquement la liste autorisee depuis l'original, puis teste et controle la copie.
Usage : .\sync_to_clean_copy.ps1 -SourcePath 'D:\projet-original' -PythonPath 'D:\env\Scripts\python.exe'
CleanPath vaut le dossier du script. Le README, .gitignore et les tests adaptes restent proteges.
Publication publique: aucun fichier sous data/ n'est autorise, meme les references publiques.
Les fichiers non listes sont signales, jamais copies. Aucun ajout Git, commit, push ou serveur.
Code de sortie : 0 = controles reussis ; 1 = tests, Git ou controle sensible en echec.
Les nouveaux fichiers signales demandent une revue manuelle, meme avec un code de sortie 0.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [string]$CleanPath = $PSScriptRoot,
    [string]$PythonPath = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Liste examinee avant publication. Toute extension exige une revue manuelle.
$AllowedFiles = @(
    '.gitignore',
    'PROVENANCE.json',
    'README.md',
    'THIRD_PARTY_NOTICES.md',
    'africa_climate_jobs.py',
    'assets/africa-demo.css',
    'assets/africa-demo.js',
    'assets/app.css',
    'assets/app.js',
    'assets/leaflet/LICENSE',
    'assets/leaflet/leaflet.css',
    'assets/leaflet/leaflet.js',
    'bench_range_reader.py',
    'build_africa_basemap.py',
    'build_climate_catalogue.py',
    'build_demo_climate.py',
    'build_map_layers.py',
    'climate_access.py',
    'climate_block_cache.py',
    'climate_normals.py',
    'climate_progress.py',
    'extract_climate_tile.py',
    'harmonize_layers.py',
    'import_catalogue.py',
    'inventory_monthly_climate.py',
    'manage.py',
    'plan_africa_tiles.py',
    'platform_app/__init__.py',
    'platform_app/africa_demo.py',
    'platform_app/reference_catalogue.py',
    'platform_app/computation.py',
    'platform_app/engine.py',
    'platform_app/monthly.py',
    'platform_app/result_tools.py',
    'platform_app/settings.py',
    'platform_app/setup.py',
    'platform_app/soil_ph.py',
    'platform_app/urls.py',
    'platform_app/variety_screen.py',
    'platform_app/views.py',
    'prepare_africa_extent.py',
    'probe_africa_monthly.py',
    'requirements.txt',
    'run_climate_background.py',
    'scripts/soilgrids_ph_0_30_diagnostics.py',
    'scripts/soilgrids_ph_africa.py',
    'templates/africa_demo.html',
    'templates/index.html',
    'tests/range_server.py',
    'tests/test_africa_jobs.py',
    'tests/test_climate_cache.py',
    'tests/test_climate_network.py',
    'tests/test_climate_normals.py',
    'tests/test_computation.py',
    'tests/test_engine.py',
    'tests/test_demo_retouches.py',
    'tests/test_reference_catalogue.py',
    'tests/test_harmonization.py',
    'tests/test_monthly.py',
    'tests/test_result_tools.py',
    'tests/test_setup.py',
    'tests/test_supervisor_stop.py',
    'tests/test_temperature_tab.py',
    'tests/test_ui_proposal.py',
    'tests/test_variety_screen.py',
    'upstream/LICENSE',
    'upstream/similarity.py',
    'upstream/utils.py',
    'verify_climate_outputs.py'

)
$ProtectedFiles = @(
    'README.md', '.gitignore', 'sync_to_clean_copy.ps1',
    'tests/test_engine.py', 'tests/test_variety_screen.py', 'tests/test_temperature_tab.py',
    'tests/test_reference_catalogue.py'
)
$ExcludedDirectories = @('.git', 'data', 'runs', '.venv', 'venv', 'env', '__pycache__', '.pytest_cache', '.agents', '.codex', '.aws')
$BlockedExtensions = @('.xlsx', '.xls', '.csv', '.tsv', '.tif', '.tiff', '.gpkg', '.nc', '.npz', '.npy', '.zip', '.pdf', '.docx', '.jpg', '.pem', '.key', '.sqlite3')

# RTC documentation: Enumerate reviewable files without entering private, generated or linked directories.
function Get-ProjectFiles([string]$Root) {
    $pending = [System.Collections.Generic.Stack[string]]::new()
    $pending.Push($Root)
    while ($pending.Count -gt 0) {
        foreach ($entry in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                Write-Warning "Lien ignore : $($entry.Name)"
                continue
            }
            if ($entry.PSIsContainer) {
                if ($entry.Name -notin $ExcludedDirectories -and $entry.Name -notlike '.test-tmp*' -and $entry.Name -notlike 'tmp*') {
                    $pending.Push($entry.FullName)
                }
            } elseif ($entry.Extension -notin @('.pyc', '.pyo')) {
                $entry
            }
        }
    }
}
# RTC documentation: Express a file path relative to the checked project root for allowlist comparison.
function Get-RelativeName([string]$Root, [string]$FullName) {
    $FullName.Substring($Root.Length + 1).Replace('\', '/')
}
# RTC documentation: Reject paths escaping the root, private file types and reparse points before any copy.
function Assert-SafeFile([string]$Root, [string]$RelativeName) {
    if ([IO.Path]::IsPathRooted($RelativeName) -or $RelativeName -match '(^|[/\\])\.\.([/\\]|$)') {
        throw "Chemin interdit dans la liste : $RelativeName"
    }
    $parts = $RelativeName -split '[/\\]'
    foreach ($part in $parts) {
        if (($part -in $ExcludedDirectories) -or $part -like '.env*' -or $part -like '.test-tmp*' -or $part -like 'tmp*') {
            throw "Entree privee interdite dans la liste : $RelativeName"
        }
    }
    if (([IO.Path]::GetExtension($RelativeName) -in $BlockedExtensions) -or $RelativeName -match '(?i)catalogue.*\.json$') {
        throw "Type prive interdit dans la liste : $RelativeName"
    }
    $full = [IO.Path]::GetFullPath((Join-Path $Root $RelativeName))
    if (-not $full.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Chemin hors du projet : $RelativeName"
    }
    # Refuse aussi un lien sur un parent existant avant toute copie.
    $cursor = $full
    while ($cursor.Length -gt $Root.Length) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Lien interdit pour la copie : $RelativeName"
            }
        }
        $cursor = Split-Path -Parent $cursor
    }
    return $full
}

$sourceRoot = (Resolve-Path -LiteralPath $SourcePath).ProviderPath.TrimEnd('\', '/')
$cleanRoot = (Resolve-Path -LiteralPath $CleanPath).ProviderPath.TrimEnd('\', '/')
foreach ($root in @($sourceRoot, $cleanRoot)) {
    if ((Get-Item -LiteralPath $root -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Les racines ne doivent pas etre des liens.'
    }
}
if ($sourceRoot -eq $cleanRoot -or $sourceRoot.StartsWith($cleanRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or $cleanRoot.StartsWith($sourceRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Les deux dossiers doivent etre distincts et ne pas etre imbriques.'
}
if (-not (Test-Path -LiteralPath (Join-Path $cleanRoot '.git') -PathType Container)) {
    throw 'CleanPath doit etre la copie Git propre initialisee.'
}
if (-not $PythonPath) {
    $PythonPath = Join-Path $cleanRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw 'Indiquer -PythonPath avec le Python de votre environnement de projet.'
    }
}
$pythonExecutable = (Get-Command $PythonPath -CommandType Application -ErrorAction Stop).Source
$gitExecutable = (Get-Command git -CommandType Application -ErrorAction Stop).Source

# Enforce the public boundary before copying: data/ must be absent here.
if (Test-Path -LiteralPath (Join-Path $cleanRoot 'data')) {
    throw 'Publication publique interdite: data/ doit etre absent de la copie.'
}
# Precontrole complet avant mutation. Un fichier absent n'est jamais supprime a destination.
$copyPlan = @()
$protectedChanges = @()
foreach ($relative in $AllowedFiles) {
    $src = Assert-SafeFile $sourceRoot $relative
    $dst = Assert-SafeFile $cleanRoot $relative
    if ($relative -in $ProtectedFiles) {
        if (-not (Test-Path -LiteralPath $dst -PathType Leaf)) { throw "Fichier protege absent : $relative" }
        if ((Test-Path -LiteralPath $src -PathType Leaf) -and (Get-FileHash -LiteralPath $src).Hash -ne (Get-FileHash -LiteralPath $dst).Hash) {
            $protectedChanges += $relative
        }
        continue
    }
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { throw "Fichier autorise absent de l'original : $relative" }
    if (-not (Test-Path -LiteralPath $dst -PathType Leaf) -or (Get-FileHash -LiteralPath $src).Hash -ne (Get-FileHash -LiteralPath $dst).Hash) {
        $copyPlan += [PSCustomObject]@{ Relative = $relative; Source = $src; Destination = $dst }
    }
}
$unlistedSource = @(Get-ProjectFiles $sourceRoot | ForEach-Object { Get-RelativeName $sourceRoot $_.FullName } | Where-Object { $_ -notin $AllowedFiles -and $_ -notin $ProtectedFiles } | Sort-Object)
Write-Host "Fichiers non listes dans l'original (non copies) : $($unlistedSource.Count)"
$unlistedSource | ForEach-Object { Write-Host "  $_" }
Write-Host "Fichiers proteges differents (revue manuelle) : $($protectedChanges.Count)"
$protectedChanges | ForEach-Object { Write-Host "  $_" }
foreach ($item in $copyPlan) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $item.Destination) | Out-Null
    Copy-Item -LiteralPath $item.Source -Destination $item.Destination
    if ((Get-FileHash -LiteralPath $item.Source).Hash -ne (Get-FileHash -LiteralPath $item.Destination).Hash) { throw "Copie non identique : $($item.Relative)" }
}
Write-Host "Fichiers copies : $($copyPlan.Count)"
$copyPlan | ForEach-Object { Write-Host "  $($_.Relative)" }

$failed = $false
Push-Location -LiteralPath $cleanRoot
try {
    Write-Host "Tests de la copie avec : $pythonExecutable"
    & $pythonExecutable -m unittest discover -s tests -q
    $testExitCode = $LASTEXITCODE
    if ($testExitCode -ne 0) { $failed = $true }

    Write-Host 'Recherche sensible (contenu des fichiers, y compris fichiers non listes ; caches et dossiers prives exclus).'
    $patterns = [ordered]@{
        'nom utilisateur personnel' = ('du' + 'sea')
        'chemin utilisateur Windows' = 'C:[/\\]Users'
        'adresse professionnelle' = ('@' + 'cgiar\.org')
        'adresse personnelle' = ('@' + 'gmail')
        'secret reconnaissable' = '(?i)(?:-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{24,})'
        'identifiant sensible affecte en clair' = '(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*[\x22\x27][^\x22\x27\r\n]{4,}[\x22\x27]'
    }
    $technicalCounts = @{ password = 0; token = 0; key = 0 }
    $hits = @()
    $cleanFiles = @(Get-ProjectFiles $cleanRoot)
    $unlistedClean = @()
    foreach ($file in $cleanFiles) {
        $relative = Get-RelativeName $cleanRoot $file.FullName
        if ($relative -notin $AllowedFiles -and $relative -notin $ProtectedFiles) { $unlistedClean += $relative }
        if ($file.Name -like '.env*' -or $file.Extension -in $BlockedExtensions -or $file.Name -match '(?i)catalogue.*\.json$') {
            $hits += "${relative}: fichier prive potentiel, ne pas ajouter a Git"
            continue
        }
        $content = [IO.File]::ReadAllText($file.FullName)
        foreach ($term in @('password', 'token', 'key')) { $technicalCounts[$term] += [regex]::Matches($content, $term, 'IgnoreCase').Count }
        $lineNumber = 0
        foreach ($line in ($content -split '\r?\n')) {
            $lineNumber++
            foreach ($category in $patterns.Keys) {
                if ([regex]::IsMatch($line, $patterns[$category], 'IgnoreCase')) {
                    # Ne jamais imprimer la valeur potentiellement secrete.
                    $hits += "${relative}:${lineNumber}: $category"
                }
            }
        }
    }
    Write-Host "Fichiers examines : $($cleanFiles.Count) ; alertes : $($hits.Count)"
    $hits | ForEach-Object { Write-Warning $_ }
    if ($hits.Count -gt 0) { $failed = $true }
    foreach ($term in @('password', 'token', 'key')) { Write-Host "  $term : $($technicalCounts[$term]) occurrences a examiner (les noms techniques seuls ne bloquent pas)." }
    Write-Host "Fichiers non listes deja presents dans la copie : $($unlistedClean.Count)"
    $unlistedClean | Sort-Object | ForEach-Object { Write-Host "  $_" }

    Write-Host 'Differences Git non indexees :'
    & $gitExecutable diff --stat
    if ($LASTEXITCODE -ne 0) { $failed = $true }
    Write-Host 'Differences Git deja indexees :'
    & $gitExecutable diff --cached --stat
    if ($LASTEXITCODE -ne 0) { $failed = $true }
    Write-Host 'Etat Git, y compris fichiers non suivis :'
    & $gitExecutable status --short --untracked-files=all
    if ($LASTEXITCODE -ne 0) { $failed = $true }
    Write-Host "Bilan : copies=$($copyPlan.Count), non-listes-original=$($unlistedSource.Count), proteges-differents=$($protectedChanges.Count), tests-exit=$testExitCode, alertes=$($hits.Count)."
    Write-Host 'Revue manuelle requise. Aucun ajout Git, commit, push, suppression ou serveur effectue.'
} finally {
    Pop-Location
}
if ($failed) { exit 1 }
exit 0
