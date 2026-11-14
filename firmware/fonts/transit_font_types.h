// Converter and renderer support: GPL-3.0-or-later. Font data retains its own licence.
#pragma once
#include <stdint.h>
#include <stddef.h>
#if defined(ARDUINO)
#include <Arduino.h>
#define OTD_FONT_FLASH PROGMEM
#else
#define OTD_FONT_FLASH
#endif
struct TransitGlyph {uint32_t codepoint,offset;uint16_t width,height;int16_t xOffset,yOffset;int32_t advanceQ6;};
struct TransitKerning {uint16_t leftIndex,rightIndex;int16_t adjustmentQ6;};
struct TransitFont {uint16_t pixels;bool bold;uint16_t glyphCount,kerningCount;int16_t ascent,descent;const uint8_t* bitmap;const TransitGlyph* glyphs;const TransitKerning* kerning;};
