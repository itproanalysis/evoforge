param([Parameter(Mandatory=$true)][string]$VideoDirectory)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$videoRoot = (Resolve-Path -LiteralPath $VideoDirectory).Path
$scenes = Get-Content -LiteralPath (Join-Path $videoRoot 'scenes.json') -Raw | ConvertFrom-Json
$narrator = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $narrator.SelectVoice('Microsoft Zira Desktop')
    $narrator.Rate = -1
    foreach ($scene in $scenes) {
        if ($scene.audio -notmatch '^scene-[0-9]{2}\.wav$') { throw 'Unexpected scene filename' }
        $audioFile = Join-Path $videoRoot $scene.audio
        $narrator.SetOutputToWaveFile($audioFile)
        $narrator.Speak($scene.narration)
        $narrator.SetOutputToNull()
    }
} finally {
    $narrator.Dispose()
}
