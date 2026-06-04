param(
  [Parameter(Mandatory=$true)][string]$InputVideo,
  [Parameter(Mandatory=$true)][string]$OutputVideo
)

$ErrorActionPreference = "Stop"

ffmpeg -y `
  -i $InputVideo `
  -c:v libx264 `
  -pix_fmt yuv420p `
  -profile:v high `
  -crf 18 `
  -preset medium `
  -c:a aac `
  -b:a 192k `
  $OutputVideo

