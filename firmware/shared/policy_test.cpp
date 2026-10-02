#include "display_policy.h"
#include <cassert>
int main() {
  using namespace otd;
  NoticeState n{true, false, true, false, 1000, 2000};
  assert(page(n, 1000, 301, true, true) == Page::Emergency);
  assert(page(n, 1030, 301, true, true) == Page::TransitEmergencyBanner);
  assert(page(n, 1000, 300, true, true) == Page::TransitEmergencyBanner);
  assert(page(n, 2000, 301, true, true) == Page::Transit);
  assert(page(n, 999, 301, true, true) == Page::Transit);
  assert(page(n, 1000) == Page::Transit);
  assert(page(n, 1000, 301, false, true) == Page::Transit);
  n.critical = true;
  assert(page(n, 1000, 1, true, true) == Page::Emergency);
  n.cancelled = true;
  assert(page(n, 1000, 1, true, true) == Page::Transit);
}
