# Render: vhs demo.tape  (requires ffmpeg + ttyd on PATH)
Output docs/demo.gif
Set FontSize 14
Set Width 1100
Set Height 700
Set Shell powershell
Set Theme "Catppuccin Mocha"
Set Padding 20
Type ".\.venv\Scripts\Activate.ps1"
Enter
Sleep 1s
Type "python scripts\test_run.py"
Enter
Sleep 6s
