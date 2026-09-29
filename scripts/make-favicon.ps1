# Generates a valid 32x32 favicon.ico (PNG-embedded, Vista+ format) from a
# solid brand-coloured tile. Run once to create frontend/public/favicon.ico.
# Kept in the repo so the binary asset is reproducible, not hand-edited.
Add-Type -AssemblyName System.Drawing

$bmp = New-Object System.Drawing.Bitmap 32, 32
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias

$bg = [System.Drawing.Color]::FromArgb(255, 7, 17, 31)
$accent = [System.Drawing.Color]::FromArgb(255, 57, 217, 255)
$good = [System.Drawing.Color]::FromArgb(255, 53, 211, 154)

$g.Clear($bg)
$pen = New-Object System.Drawing.Pen $accent, 2.0
$pen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
$shield = @(
  (New-Object System.Drawing.PointF 16, 5),
  (New-Object System.Drawing.PointF 26, 9),
  (New-Object System.Drawing.PointF 26, 17),
  (New-Object System.Drawing.PointF 16, 28),
  (New-Object System.Drawing.PointF 6, 17),
  (New-Object System.Drawing.PointF 6, 9)
)
$g.DrawPolygon($pen, $shield)

$pulse = New-Object System.Drawing.Pen $good, 1.8
$pulse.LineCap = [System.Drawing.Drawing2D.LineCap]::Round
$pulse.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
$poly = @(
  (New-Object System.Drawing.PointF 9.5, 16.5),
  (New-Object System.Drawing.PointF 13, 16.5),
  (New-Object System.Drawing.PointF 15, 12.5),
  (New-Object System.Drawing.PointF 17.5, 20),
  (New-Object System.Drawing.PointF 19.5, 16.5),
  (New-Object System.Drawing.PointF 22.5, 16.5)
)
$g.DrawPolygon($pulse, $poly)
$g.Dispose()

# PNG bytes (ICO supports an embedded PNG for sizes >= 256, and in practice
# every current browser; this keeps the file tiny and avoids a BMP encoder).
$ms = New-Object System.IO.MemoryStream
$bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
$png = $ms.ToArray()
$bmp.Dispose(); $ms.Dispose()

# ICONDIR = reserved(2) + type(2) + count(2), all little-endian uint16.
$dir = New-Object byte[] 6
$dir[0] = 0; $dir[1] = 0    # reserved
$dir[2] = 1; $dir[3] = 0    # type = 1 (icon)
$dir[4] = 1; $dir[5] = 0    # image count = 1

$entry = New-Object byte[] 16
$entry[0] = 32; $entry[1] = 32                      # width, height
$entry[2] = 0; $entry[3] = 0                        # colours, reserved
$entry[4] = 0; $entry[5] = 0                        # colour planes
$entry[6] = 0; $entry[7] = 0                        # bits per pixel
$len = $png.Length
$entry[8]  = [byte]($len -band 0xFF)
$entry[9]  = [byte](($len -shr 8) -band 0xFF)
$entry[10] = [byte](($len -shr 16) -band 0xFF)
$entry[11] = [byte](($len -shr 24) -band 0xFF)
$entry[12] = 22; $entry[13] = 0; $entry[14] = 0; $entry[15] = 0   # offset

$out = New-Object byte[] (6 + 16 + $len)   # ICONDIR + ICONDIRENTRY + PNG payload
[Array]::Copy($dir, 0, $out, 0, 6)
[Array]::Copy($entry, 0, $out, 6, 16)
[Array]::Copy($png, 0, $out, 22, $len)

$path = "D:\Projects\AEGIS-AI\frontend\public\favicon.ico"
[System.IO.File]::WriteAllBytes($path, $out)
"wrote $path ($($out.Length) bytes, embedded PNG $($png.Length) bytes)"
