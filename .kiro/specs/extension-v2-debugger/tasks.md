# Implementation Plan

## Overview

Extension v2 replaces the unreliable shadow DOM click approach with chrome.debugger API for trusted mouse events. Includes new Day Schedule popup UI, automated execution after approval, health monitoring, and retry logic.

## Tasks

- [ ] 1. Create debugger engine module with trustedClick function
- [ ] 2. Improve App Promo Banner Dismissal with expanded selectors
- [ ] 3. Implement localStorage Draft Cleanup for Reddit draft keys
- [ ] 4. Update Content Scripts with new message handlers
- [ ] 5. Build Backend API Extensions with PATCH endpoint and health fields
- [ ] 6. Implement Retry Logic with per-error-type strategy
- [ ] 7. Create updated execution flow in background/executor.js
- [ ] 8. Implement Health Monitoring tracking consecutive failures
- [ ] 9. Implement Edit Before Approve with inline textarea
- [ ] 10. Implement Batch Approval with Approve All button
- [ ] 11. Create scheduler module in background/scheduler.js
- [ ] 12. Build Popup v3 Day Schedule UI
- [ ] 13. Run Integration Testing for all flows
- [ ] 14. Build and Deploy extension v2.0.0

## Task Dependency Graph

```
1 → 7
2 → 7
3 → 7
4 → 7
6 → 11
8 → 11
7 → 11
5 → 9
5 → 10
5 → 8
9 → 12
10 → 12
11 → 12
12 → 13
13 → 14
```

## Notes

- Extension source lives at /Volumes/2SSD/Projects/ReddirSaaS/ramp_extension/
- Backend routes in app/routes/extension_api.py
- Wave 1 (no deps): Tasks 1, 2, 3, 4, 5, 6
- Wave 2 (deps on Wave 1): Tasks 7, 8, 9, 10
- Wave 3: Task 11
- Wave 4: Task 12
- Wave 5: Task 13
- Wave 6: Task 14
