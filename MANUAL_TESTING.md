# Manual Calibre Kindle MTP Test

Automated tests use stubs because Calibre's embedded runtime and physical MTP devices are not available in ordinary CI.

1. Build `Annotations.zip` from the repository root with plugin files at the ZIP root.
2. In Calibre 9.6.0 on macOS, install the ZIP from Preferences > Plugins > Load plugin from file.
3. Restart Calibre.
4. Connect a Kindle that appears through Calibre's `MTP Device Interface`.
5. Wait until Calibre finishes listing books on the device.
6. Configure the Annotations plugin destination column if needed.
7. Select Annotations > Fetch annotations from Kindle.
8. Confirm the progress dialog completes without `imp` or `create_annotations_path` errors.
9. Confirm annotated Kindle books are listed, preview annotations, and import one book.
10. Verify the selected Calibre book receives annotations in the configured destination.
