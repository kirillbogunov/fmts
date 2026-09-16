# FMTS v0.5.3 — QR labels, iPhone PWA safe area, comment photos

## QR / equipment labels

- Added a printable **80 × 100 mm equipment label**.
- The label shows the equipment name, site/store, inventory number and QR code before the QR itself.
- Added a dedicated **Print label** action from the equipment card.
- The QR still uses `PUBLIC_BASE_URL` and opens the equipment scan workflow.

## iPhone / installed PWA

- Fixed the top header overlapping the iPhone status-bar area (time / battery / Dynamic Island area).
- The mobile top bar now respects `safe-area-inset-top` and its clickable controls are positioned below the protected iOS area.
- Changed the Apple standalone status bar from translucent overlay mode to normal black status-bar mode.
- Service worker cache version bumped so the corrected CSS is delivered to installed PWAs.

## Comments and attachments

- A technician/comment author can attach up to 5 photos to one comment (configurable).
- Comment photos are shown as thumbnails in the ticket history and open in the protected FMTS viewer.
- Existing ticket attachments now open in a viewer instead of forcing a download.
- Images, PDFs and text open inline; unsupported office/archive formats open a viewer page with an explicit download button instead of downloading automatically.
- Attachment access keeps the existing RBAC/ticket row-level security checks.
- Added an automatic additive migration for `attachments.comment_id` for existing SQLite/PostgreSQL databases.
