# Starts the embedding + rerank model service on this PC so it can use the GPU.
# Run it from any folder, in a PowerShell window where the conda environment is active:
#   conda activate mindnest
#   .\scripts\start-models.ps1          real models (BGE-M3, first run downloads a few GB)
#   .\scripts\start-models.ps1 -Fake    placeholder vectors, for quick pipeline checks only
param([switch]$Fake)

Set-Location (Split-Path $PSScriptRoot -Parent)
if ($Fake) { $env:MODEL_BACKEND = "fake" } else { Remove-Item Env:MODEL_BACKEND -ErrorAction SilentlyContinue }
python -m uvicorn mindnest_models.main:app --host 0.0.0.0 --port 8100
