# Site layout and font handoff

The Site's original single-service and four-row layout is now available in [site-default.json](../firmware/layouts/site-default.json). This is a layout specification, not completed firmware. Font conversion and firmware integration have explicit owners below.

## Responsibility assignment (13 October 2026)

This assignment resolves the circular handoff between the two ChatGPT conversations.

| Work | Owner | Required result |
| --- | --- | --- |
| Original font assets, provenance, copyright and licence notices | **Website/layout conversation**: the conversation that created this handoff document and the Site layout export | Verified source assets and documented licence requirements |
| Font conversion and its GitHub Actions automation | **Website/layout conversation** | Reproducible conversion driven by the layout; embedded font arrays, Unicode lookup/metrics, and a manifest of generated sizes and glyphs |
| Font usage/integration in Seeed_GFX device firmware | **Hardware-testing conversation**: the conversation developing the Museum-stop display and working LoRa connection | Device renderer uses the generated fonts and preserves layout text-fitting behaviour |
| Firmware compilation and ready-to-flash hardware builds | **Hardware-testing conversation**, consuming the font-generation step maintained by the website/layout conversation | Firmware builds include the generated fonts automatically |
| Museum-stop rendering, structured LoRa arrivals, regional refresh, clock behaviour and timetable-aware sleep/wake | **Hardware-testing conversation** | Tested device behaviour on the actual display |

**The website/layout conversation owns font conversion. It must not hand conversion back to the hardware-testing conversation. The hardware-testing conversation owns integrating the conversion output, not writing a second converter.**

### Handoff contract

The website/layout conversation will provide:
- the font sources and applicable notices;
- a converter and GitHub Actions entry point that the firmware build can invoke;
- compiled-in font data, glyph lookup and metrics suitable for the device renderer, covering required layout sizes and Māori characters;
- a manifest identifying source hashes, glyph coverage, generated sizes and output format;
- an integration example describing how the hardware renderer loads and draws those fonts.

The hardware-testing conversation will integrate that output into its renderer and build workflow, then validate it on the device. It can continue its existing hardware milestones while conversion is pending.

**Current status:** font identity, hashes and layout geometry are documented. Automated font conversion has not yet been delivered by the website/layout conversation. The assignment above is a work commitment, not a claim that the conversion pipeline or faithful typography is already complete.

## Exact typography

`TransitSans` is a CSS alias. The actual OpenType fonts bundled with the Site identify themselves as **Nimbus Sans Regular** and **Nimbus Sans Bold**, from Artifex/URW Base35.

| Asset in the Site source | Web weight | SHA-256 |
| --- | --- | --- |
| `public/display-sans-regular.otf` | 400 | `7c25be4d78155523080ab85b10277150657ff7dabbcad7037bdd536c9b6d0d08` |
| `public/display-sans-bold.otf` | 900 | `7f33328e6b4d4cd21b45fa625791928c9407dc702db6780e56b09ca9a3ecaa67` |

The originals remain in the Site source. Their URLs are relative to https://open-transit-display.thereverendjc.chatgpt.site and inherit Site access:
- `/display-sans-regular.otf`
- `/display-sans-bold.otf`
- `/font-license.txt`

Both font character maps were checked for ā ē ī ō ū Ā Ē Ī Ō Ū, the right arrow, and the em dash; none of those glyphs is missing.

The bundled copyright notice identifies **AGPL-3 with Font exception**. The upstream [licence](https://github.com/ArtifexSoftware/urw-base35-fonts/blob/master/LICENSE) describes its exception for PostScript/PDF documents. Retain the complete applicable licence and copyright notices when vendoring fonts. Do not describe these assets as SIL-licensed or treat that document exception as a general firmware exception. The repository's existing GPL licence has not been changed.

## Faithful rendering

Schema `1.1` retains its existing fields for compatibility. The additive `rendering` object records details formerly hard-coded in the browser renderer:

- white background, foreground colour, outer frame and stroke widths;
- route badge rectangles and corner radii;
- single-view separators;
- `rendering.single.regions`: the effective text rectangles, sizes, alignment and weights, including captions and update-age text;
- conditions for scheduled versus live fields;
- multi-view row origins, row heights, dividers, route badges and text weights.

For the single view, prefer `rendering.single.regions` over the nominal `single` rectangles when matching the current browser image. Region rectangles are [x, y, width, height], in pixels. Multi-row regions remain relative to each row origin. Editing/refresh overlays are excluded from the device image.

Changing the font conversion pipeline does not require changing the USB framebuffer test, which receives already-rendered pixels. A device-side text renderer must bundle the converted font assets itself.
