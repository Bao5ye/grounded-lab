$ErrorActionPreference = 'Stop'
$compiler64 = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$compiler32 = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
$compiler = if (Test-Path -LiteralPath $compiler64) { $compiler64 } else { $compiler32 }
if (-not (Test-Path -LiteralPath $compiler)) { throw '未找到 .NET Framework C# 编译器。' }
$source = Join-Path $PSScriptRoot '启动器.cs'
$output = Join-Path $PSScriptRoot '扎根理论工作台.exe'
& $compiler /nologo /target:exe /nowin32manifest /reference:System.Web.Extensions.dll "/out:$output" $source
if ($LASTEXITCODE -ne 0) { throw "编译失败，退出代码 $LASTEXITCODE。" }
Write-Host "构建完成：$output"