# Embedded TransitSans font package

This directory belongs to the website/layout workstream. The device workstream consumes the generated package.

## Sources and licence

TransitSans is the website alias for Nimbus Sans Regular/Bold. Exact original OTF bytes are stored in `source/*.otf.b64`, as text-safe Base64, with SHA-256 checks in `sources.json`. The converter decodes them automatically; users do not need to decode, install or convert fonts.

Original font data and derived bitmap data retain the source font's AGPL-3.0 terms and upstream PostScript/PDF exception. `COPYING` and `COPYRIGHT.txt` travel with the package. Converter and renderer helper code use the repository's GPL-3.0-or-later licence. Do not replace these notices with a SIL licence or assume the document exception applies to firmware.

## Build

```sh
python -m pip install -r firmware/tools/requirements-fonts.txt
python firmware/tools/build_fonts.py --layout firmware/layouts/site-default.json --out firmware/generated
```

`--text-file path/to/stop-data.json` can be repeated to include extra characters used by selected stops and destinations. JSON string values are used, not property names. The converter fails if a required glyph is absent from the source fonts.

The default package covers printable ASCII, Māori macrons, directional arrows and common display punctuation. It includes every integer size between each layout region's minimum and preferred font sizes, including effective regions in the schema 1.1 `rendering` object. Weights 400/500 use Regular; weights 600 and above use Bold.

Schema 2.0 TransitSans blocks, departure-list field scales and captions/static text are supported. Other browser font families need their own source assets and are rejected, rather than silently replaced.

## Outputs

- `transit_fonts.h`: compiled-in, MSB-first 1-bit glyph bitmaps, Unicode lookup, advances and kerning.
- `transit_fonts_manifest.json`: source/layout/output hashes, generated sizes, glyph coverage and flash-size estimate.
- `font-preview.png`: a typography/glyph-coverage reference.
- `transit_font_types.h` and `transit_font_renderer.h`: ESP32/Seeed_GFX integration support, copied into the Actions artifact.

The font arrays reside in ESP32 flash; there is no font filesystem upload. The complete default package is sizeable because text fitting can use many sizes. Check `estimated_flash_bytes` and allow sufficient application-partition space for both fonts and the firmware. The generator caps the font estimate at 4 MiB. Board flash capacity alone is not the application partition size.

The bitmap rasterizer pins Pillow/fontTools and records the FreeType version. It thresholds coverage at 128. The helper supports UTF-8, per-glyph positioning, pair kerning and clipping; it does not implement full complex-script shaping or OpenType ligature substitution. Hardware rendering still needs comparison with the browser preview, including baseline placement and fitting.

## Firmware integration

Copy the generated package headers next to the Arduino sketch, then:

```cpp
#include "transit_fonts.h"
#include "transit_font_renderer.h"

const TransitFont* face = transitFindFont(transit_fonts, transit_font_count, true, 42);
if (face) {
  TransitClip clip{620,18,150,48};
  epaper.fillRect(clip.x,clip.y,clip.width,clip.height,TFT_WHITE);
  int width = transitRoundQ6(transitMeasureQ6(*face,clockText.c_str()));
  int x = clip.x + clip.width - width;
  int baseline = clip.y + (clip.height + face->ascent - face->descent)/2;
  transitDrawText(epaper,*face,clockText.c_str(),x,baseline,TFT_BLACK,clip);
}
```

`transitFindFont` returns null for an ungenerated size. Choose an available size while fitting; do not dereference null. `transitDrawText` paints only foreground pixels, so clear the region first. It does not refresh the panel, change power state or take ownership of SPI; retain the hardware agent's refresh/radio policy.

The baseline above is a metrics-based starting point, not a substitute for reproducing the website's Canvas middle-baseline positioning. The hardware agent owns that visual verification and integration.

## GitHub Actions

`build-fonts.yml` runs on font, converter and layout changes. It tests conversion and the C++ helper, generates the package, checks the complete header, and uploads `transit-fonts-<commit SHA>`.

A firmware workflow can reuse it:

```yaml
jobs:
  fonts:
    uses: ./.github/workflows/build-fonts.yml
  firmware:
    needs: fonts
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7.0.1
      - uses: actions/download-artifact@v8.0.2
        with:
          name: ${{ needs.fonts.outputs.artifact_name }}
          path: firmware/generated
      # Copy headers into the sketch/include path and run the board's firmware build.
```

Merge the font-pipeline files from main into the firmware branch before using the relative reusable-workflow path. The font workflow produces font packages; the hardware firmware workflow produces ready-to-flash binaries. No successful board build or physical typography qualification is implied by a font-package build.
