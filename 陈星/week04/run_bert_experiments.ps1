$ErrorActionPreference = "Stop"
$python = "D:\miniconda3\envs\py312\python.exe"

& $python .\bert_finetune_experiment.py --learning-rate 2e-5 --run-name lr_2e-5
& $python .\bert_finetune_experiment.py --learning-rate 5e-5 --run-name lr_5e-5
