#pragma once
#include <Arduino.h>
struct Rect { int16_t x, y, w, h; };
enum TestMode : uint8_t { ONE_PASS = 0, ERASE_REDRAW = 1, DIRTY_RECT = 2, FULL_ONLY = 3 };
