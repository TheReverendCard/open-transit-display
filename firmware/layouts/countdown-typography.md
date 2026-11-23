# Countdown typography for transit signs

Use the fitted size of “In 20 min” as the Museum layout's reference. Choose one font size when configuring each sign layout and keep it stable for all ordinary numeric minute values the layout supports. On other panel sizes, fit the supported range once at layout time. Reserve width for the widest supported number.

Keep “In” and “min” anchored at fixed positions on a common baseline. Give the number its own fixed-width field with tabular figures when available. On e-paper, redraw the number field against a clean background while keeping the surrounding text in the same pixel positions. This limits the area affected by differential refreshes and reduces the risk of shadows around the side text.

Check 20 → 19 and 10 → 9 on the panel. Verify that the size, baseline and side text stay steady and that the previous digits clear. The Museum hybrid trial prompted this follow-up. The typography change is pending.
