# Requirements Document

## Introduction

This feature adds clipboard paste support for screenshots in the `/report-issue` bug report form. Users can paste an image from their clipboard (Cmd+V / Ctrl+V) directly into the form as an alternative to manually selecting a file via the file input. The pasted image is previewed inline and submitted alongside the form data using the existing screenshot upload mechanism.

## Glossary

- **Report_Form**: The public-facing bug report form at `/report-issue`, rendered by the `report_issue.html` template
- **Clipboard_Handler**: The client-side JavaScript component that intercepts paste events and extracts image data from the clipboard
- **Screenshot_Preview**: The UI element that displays a thumbnail preview, file size, and removal button for a pasted image
- **File_Input**: The existing `<input type="file">` element that accepts screenshot uploads
- **Save_Screenshot_Service**: The backend service function `save_screenshot()` that persists uploaded images to `/static/uploads/bugs/` with UUID filenames

## Requirements

### Requirement 1: Clipboard Paste Capture

**User Story:** As a bug reporter, I want to paste a screenshot from my clipboard using Cmd+V or Ctrl+V, so that I can attach visual evidence without manually saving and selecting a file.

#### Acceptance Criteria

1. WHEN a user pastes clipboard content containing an image on the Report_Form page, THE Clipboard_Handler SHALL extract the image blob from the clipboard data
2. WHEN the Clipboard_Handler extracts an image blob, THE Clipboard_Handler SHALL assign the blob to the File_Input element using the DataTransfer API
3. WHEN clipboard content contains no image data, THE Clipboard_Handler SHALL take no action and allow default paste behavior
4. THE Clipboard_Handler SHALL support image MIME types including `image/png`, `image/jpeg`, `image/gif`, and `image/webp`

### Requirement 2: Paste Preview Display

**User Story:** As a bug reporter, I want to see a preview of my pasted screenshot before submitting, so that I can confirm the correct image was captured.

#### Acceptance Criteria

1. WHEN an image is successfully extracted from the clipboard, THE Screenshot_Preview SHALL become visible showing a thumbnail of the pasted image
2. WHEN an image is successfully extracted from the clipboard, THE Screenshot_Preview SHALL display the file size in kilobytes
3. WHILE the Screenshot_Preview is visible, THE Report_Form SHALL display a "Remove" button that allows the user to discard the pasted image
4. WHEN the user clicks the "Remove" button, THE Screenshot_Preview SHALL become hidden and THE File_Input SHALL be cleared

### Requirement 3: Paste-to-Upload Integration

**User Story:** As a bug reporter, I want my pasted screenshot to be uploaded when I submit the form, so that the QA team receives the visual evidence with my report.

#### Acceptance Criteria

1. WHEN the Report_Form is submitted with a pasted image assigned to the File_Input, THE Save_Screenshot_Service SHALL receive the image as a standard file upload
2. THE Save_Screenshot_Service SHALL save pasted images to `/static/uploads/bugs/` with a UUID-based filename and the appropriate file extension
3. WHEN a pasted image has no explicit filename, THE Save_Screenshot_Service SHALL default to `.png` extension
4. THE Save_Screenshot_Service SHALL store the resulting URL in the `screenshot_url` field of the bug report record

### Requirement 4: File Input and Paste Coexistence

**User Story:** As a bug reporter, I want the paste functionality to coexist with the file picker, so that I can use whichever method is more convenient.

#### Acceptance Criteria

1. WHEN the user pastes an image after selecting a file via the File_Input, THE Clipboard_Handler SHALL replace the previously selected file with the pasted image
2. WHEN the user selects a file via the File_Input after pasting an image, THE File_Input SHALL use the newly selected file and THE Screenshot_Preview SHALL become hidden
3. THE Report_Form SHALL accept at most one screenshot per submission regardless of input method

### Requirement 5: Size and Type Validation

**User Story:** As a system administrator, I want pasted images to respect the same constraints as file uploads, so that storage and security are maintained.

#### Acceptance Criteria

1. IF a pasted image exceeds 10 MB, THEN THE Clipboard_Handler SHALL display an error message and SHALL NOT assign the image to the File_Input
2. IF a pasted clipboard item has a MIME type not starting with `image/`, THEN THE Clipboard_Handler SHALL ignore that item
3. THE Save_Screenshot_Service SHALL only accept file extensions `.png`, `.jpg`, `.jpeg`, `.gif`, and `.webp`, defaulting to `.png` for unrecognized extensions
