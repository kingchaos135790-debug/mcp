# Preferred Windows paths on this PC
$env:GOROOT = 'E:\Program Files\Go'
$env:GOBIN = 'E:\Program Files\go-bin'
$env:Path = "$env:GOROOT\bin;$env:GOBIN;$env:Path"

# Build Zoekt (currently fails at latest upstream revision on this machine)
go install github.com/sourcegraph/zoekt/cmd/zoekt-index@latest
go install github.com/sourcegraph/zoekt/cmd/zoekt-webserver@latest

# Start Qdrant from the local Windows binary
Set-Location 'E:\Program Files\qdrant'
.\qdrant.exe

# Start Zoekt after binaries exist
Set-Location 'E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp'
zoekt-webserver -listen :6070 -index .\data\index
