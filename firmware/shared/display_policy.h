#pragma once
#include <stdint.h>

namespace otd {
enum class Page { Transit, TransitNotice, TransitEmergencyBanner, Emergency };
struct NoticeState {
  bool verified = false;
  bool cancelled = false;
  bool emergency = false;
  bool critical = false;
  int64_t starts = 0;
  int64_t expires = 0;
};
// Call only after signature, delegation, target and persistent revision checks.
inline Page page(const NoticeState& n, int64_t now, int64_t next_seconds = -1,
                 bool emergency_enabled = true, bool clock_trusted = false) {
  if (!clock_trusted || !n.verified || n.cancelled || now < n.starts || now >= n.expires)
    return Page::Transit;
  if (!n.emergency) return Page::TransitNotice;
  if (!emergency_enabled) return Page::Transit;
  if (n.critical) return Page::Emergency;
  if (next_seconds >= 0 && next_seconds <= 300) return Page::TransitEmergencyBanner;
  return ((now - n.starts) / 30) % 2 == 0 ? Page::Emergency : Page::TransitEmergencyBanner;
}
}  // namespace otd
