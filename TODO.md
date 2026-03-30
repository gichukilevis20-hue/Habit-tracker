# TODO: Fix First Calendar Misalignment on Resize

## Steps:
- [x] 1. Update tracker/views.py: Add `calendar_weeks` grouping to home() context.
- [x] 2. Edit tracker/templates/tracker/home.html: Refactor calendar to loop over weeks.
- [x] 3. Update static/tracker/app.css: Fix .calendar-grid to semantic 7-col responsive.
- [x] 4. Add JS resize observer in home.html extra_js for layout refresh.
- [x] 5. Test on /home/: Resize window, verify days align to Mon-Sun headers matching actual dates.

**Fixed: First calendar now uses semantic week rows with fixed 7-column responsive grid. Days stay aligned to correct weekdays on resize.**

Current progress: Task complete.

