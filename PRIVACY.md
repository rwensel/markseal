# Privacy

MarkSeal runs entirely on your machine. It does not collect telemetry, analytics, or usage data, and it does not upload screenshots, PDFs, or their contents.

MarkSeal includes a bundled local PII model (GLiNER PII Small) for personal names and postal addresses. It runs on your machine and reads only the OCR text from the image being scanned. The model is installed with the app; MarkSeal never downloads it at runtime and never sends recognized text or images anywhere.

The only network access is the optional update check. It is off by default. When enabled, it fetches a small public release manifest and, if an update exists, the installer; it exchanges release metadata (version, notes, download URL, SHA-256) and never image data. No account is required.

The application reads and writes only the images and PDFs you open, the files you export, and its local settings and performance logs. Nothing is sent to the maintainer.
