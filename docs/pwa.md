# Use the phone app

Open the canonical trusted HTTPS address and sign in once. On Android Chrome, choose **Install app** from the browser menu/install hint. On iPhone, use Safari → Share → Add to Home Screen. Open the installed icon and confirm it uses the same address. Native physical-device installation still needs checking on the owner's phones; desktop Chromium phone emulation is not the same test.

Select an expo in Capture. You can create or switch expos while offline. Start a **New booth** for each stall; all following photos belong to that booth until you start another. Use Take photo repeatedly or Choose from gallery for several images/PDFs. Mark Card/Brochure when useful. Add notes to a photo, booth or expo and use quick tags for context.

Blobs and capture IDs are written to IndexedDB before upload. Expo assignment is fixed at capture time, including during retries. Queued notes can be edited/deleted; the latest revision wins. The app asks for persistent storage and reports near-full storage when the browser provides that information. Phones can still remove unused browser storage, especially on iPhone: sync promptly after returning. Keep the app open until the queue confirms Saved.

Sync runs on app open/focus, network return, every 30 seconds while open, and through Sync now. The order is new expos → booths → files → notes/tags. A file leaves phone storage only after the server acknowledges both the stored file and its capture receipt. Interrupted sync resumes with stable client UUIDs and SHA-256 checks. Saved receipts can remain without their original blobs so linked note edits can still sync. Never clear browser storage or uninstall to fix a connection while unsaved captures remain.

The app shell and capture workflow work offline. Full library browsing/search require the server. The service worker caches application assets only; it does not cache authenticated records, notes, originals or export downloads. Logout preserves unsynced capture data; sign back in to sync it.

On supported Android installations, Gallery/Files → Share → Expo Buddy places photos/PDFs into the queue. If no active expo was available, choose one explicitly for those files. A share failure keeps any items already queued and shows an error; verify the filenames before retrying. iPhone does not provide the same Web Share Target workflow; use Choose from gallery. Closed-app background uploads are not promised; iPhone uploads while the app is open.

After sync, ordinary captures prepare/read/extract automatically. Explicit booth/front/back groups ask you to confirm pages first. Confirm individual groups, use Accept all with Undo, or keep each file separate. Only confirmed groups proceed to AI extraction. Private notes are searchable and stay out of AI. The optional capture note explicitly accompanies new photos as AI context.

Keyboard shortcuts on PC: `/` focuses search, `U` opens capture, `Ctrl/Cmd+K` opens the command palette, `J/K` navigates review, and `E` opens/focuses editing on a detail screen. Desktop Upload provides per-file progress and retains the original session/ID for a retry.

The capture screen now starts with photos and one optional note. Booth/type controls are inside the optional grouping details. “Keep note” stores a private note; leaving text in the capture box attaches it to the next photos as explicit AI context. Ordinary photos process automatically.

When a new app version is ready, use the “Update app” prompt after finishing any unsaved typing. Durable queued photos remain in IndexedDB. For the first upgrade from the older release without this prompt, close every tab and installed window for this origin, then reopen.
