# Requirements Document

## Introduction

A standalone disk cleanup utility for the local development iMac (228 GB main disk) that automatically removes known space-consuming artifacts — Kiro agent session blobs, Docker build cache, application caches, IDE cached extensions, and logs. The utility runs as a Python CLI script that can be executed manually or scheduled via macOS launchd. It targets predictable, safe cleanup of development-related bloat that regularly pushes disk usage above 97%.

## Glossary

- **Cleanup_Script**: The Python CLI utility that performs disk cleanup operations
- **Cleanup_Target**: A specific directory or file pattern designated for removal (e.g., Kiro session blobs, Docker cache)
- **Cleanup_Rule**: A configuration entry defining a Cleanup_Target, its path pattern, age threshold, and size threshold
- **Disk_Monitor**: The component that checks current disk usage percentage before and after cleanup
- **Cleanup_Report**: A summary output showing space reclaimed, targets processed, errors encountered, and disk usage before/after
- **Dry_Run_Mode**: An execution mode where the Cleanup_Script reports what would be deleted without performing actual deletions
- **Age_Threshold**: The minimum file age (in days) before a file becomes eligible for cleanup
- **Size_Threshold**: The minimum total size of a Cleanup_Target directory before cleanup is triggered
- **Cleanup_Config**: A YAML configuration file defining all Cleanup_Rules and global settings
- **Launchd_Agent**: A macOS user-level launchd plist that schedules periodic execution of the Cleanup_Script

## Requirements

### Requirement 1: Disk Usage Detection

**User Story:** As a developer, I want the cleanup script to check current disk usage before running, so that cleanup only executes when the disk is actually filling up.

#### Acceptance Criteria

1. WHEN invoked, THE Disk_Monitor SHALL report the current disk usage percentage of the main volume
2. THE Cleanup_Script SHALL skip cleanup execution WHEN disk usage is below a configurable threshold (default: 80%)
3. WHEN the `--force` flag is provided, THE Cleanup_Script SHALL execute cleanup regardless of current disk usage
4. WHEN cleanup completes, THE Disk_Monitor SHALL report disk usage before and after cleanup in the Cleanup_Report

### Requirement 2: Kiro Agent Session Blob Cleanup

**User Story:** As a developer, I want old Kiro agent session blobs removed automatically, so that they don't accumulate to 13+ GB.

#### Acceptance Criteria

1. THE Cleanup_Script SHALL target session blob files in `~/Library/Application Support/Kiro/User/globalStorage/kiro.kiroagent/`
2. WHEN a session blob file is older than the configured Age_Threshold (default: 7 days), THE Cleanup_Script SHALL delete the file
3. THE Cleanup_Script SHALL preserve session blob files newer than the Age_Threshold
4. WHEN the Kiro application is currently running, THE Cleanup_Script SHALL skip files that are locked or in active use

### Requirement 3: Docker Build Cache Cleanup

**User Story:** As a developer, I want Docker build cache pruned automatically, so that it doesn't grow beyond 3+ GB unnoticed.

#### Acceptance Criteria

1. WHEN Docker is installed and the Docker daemon is running, THE Cleanup_Script SHALL prune Docker build cache older than the configured Age_Threshold (default: 7 days)
2. WHEN Docker is installed and the Docker daemon is running, THE Cleanup_Script SHALL remove dangling Docker images
3. IF the Docker daemon is not running, THEN THE Cleanup_Script SHALL log a warning and skip Docker cleanup without failing
4. THE Cleanup_Script SHALL report the amount of Docker cache space reclaimed in the Cleanup_Report

### Requirement 4: Application Cache Cleanup

**User Story:** As a developer, I want browser and messaging app caches cleaned periodically, so that Chrome, Telegram, WhatsApp, and IDE update caches don't consume 5+ GB.

#### Acceptance Criteria

1. THE Cleanup_Script SHALL target cache directories for: Chrome, Telegram, WhatsApp, VS Code updates, and Kiro updates under `~/Library/Caches/`
2. WHEN cache files in a target directory are older than the configured Age_Threshold (default: 3 days), THE Cleanup_Script SHALL delete those files
3. THE Cleanup_Script SHALL skip cache directories belonging to applications that are currently running
4. IF a configured cache directory does not exist, THEN THE Cleanup_Script SHALL skip that target without error

### Requirement 5: IDE Extension Cache Cleanup

**User Story:** As a developer, I want stale VS Code and Kiro cached extensions cleaned up, so that they don't accumulate hundreds of megabytes of outdated versions.

#### Acceptance Criteria

1. THE Cleanup_Script SHALL target VS Code cached extensions in `~/Library/Application Support/Code/CachedExtensionVSIXs/`
2. THE Cleanup_Script SHALL target Kiro logs, history, and cached extensions in `~/Library/Application Support/Kiro/`
3. WHEN cached extension files are older than the configured Age_Threshold (default: 14 days), THE Cleanup_Script SHALL delete those files
4. THE Cleanup_Script SHALL preserve the most recent version of each cached extension

### Requirement 6: Dry Run Mode

**User Story:** As a developer, I want to preview what would be deleted before actually running cleanup, so that I can verify the script won't remove anything important.

#### Acceptance Criteria

1. WHEN the `--dry-run` flag is provided, THE Cleanup_Script SHALL list all files and directories that would be deleted without performing actual deletions
2. WHEN in Dry_Run_Mode, THE Cleanup_Script SHALL display the total space that would be reclaimed
3. WHEN in Dry_Run_Mode, THE Cleanup_Script SHALL display the estimated disk usage percentage after cleanup
4. THE Cleanup_Script SHALL default to Dry_Run_Mode when run for the first time (no previous execution recorded)

### Requirement 7: Configuration File

**User Story:** As a developer, I want cleanup rules defined in a configuration file, so that I can add or modify targets without editing the script.

#### Acceptance Criteria

1. THE Cleanup_Script SHALL read Cleanup_Rules from a YAML Cleanup_Config file
2. WHEN no Cleanup_Config file exists at the expected path, THE Cleanup_Script SHALL use built-in default rules
3. THE Cleanup_Config SHALL support per-target settings: path pattern, Age_Threshold, Size_Threshold, and enabled/disabled flag
4. WHEN the Cleanup_Config contains invalid entries, THE Cleanup_Script SHALL report validation errors and skip invalid rules without aborting

### Requirement 8: Cleanup Reporting and Logging

**User Story:** As a developer, I want a clear report after each cleanup run, so that I know what was removed and how much space was freed.

#### Acceptance Criteria

1. WHEN cleanup completes, THE Cleanup_Script SHALL output a Cleanup_Report to stdout containing: targets processed, files deleted count, space reclaimed per target, total space reclaimed, and disk usage before/after
2. THE Cleanup_Script SHALL write a log file to a configurable location (default: `~/.local/share/disk-cleanup/cleanup.log`)
3. THE Cleanup_Script SHALL retain log entries for the last 30 days and rotate older entries
4. IF any errors occur during cleanup, THEN THE Cleanup_Script SHALL include error details in the Cleanup_Report and continue processing remaining targets

### Requirement 9: Scheduled Execution via Launchd

**User Story:** As a developer, I want the cleanup script to run automatically on a schedule, so that I don't have to remember to run it manually.

#### Acceptance Criteria

1. THE Cleanup_Script SHALL provide an `install` subcommand that creates a Launchd_Agent plist in `~/Library/LaunchAgents/`
2. THE Launchd_Agent SHALL schedule the Cleanup_Script to run daily at a configurable time (default: 03:00)
3. THE Cleanup_Script SHALL provide an `uninstall` subcommand that removes the Launchd_Agent plist and unloads the agent
4. WHEN the Mac was asleep at the scheduled time, THE Launchd_Agent SHALL run the cleanup at the next wake

### Requirement 10: Safety Guards

**User Story:** As a developer, I want the cleanup script to have safety mechanisms, so that it cannot accidentally delete critical files or system data.

#### Acceptance Criteria

1. THE Cleanup_Script SHALL only operate on paths within the user's home directory and Docker system paths
2. THE Cleanup_Script SHALL refuse to delete any path that is a symlink pointing outside the configured target directories
3. IF a single cleanup operation would delete more than a configurable maximum (default: 20 GB), THEN THE Cleanup_Script SHALL abort that target and require explicit `--force` confirmation
4. THE Cleanup_Script SHALL verify that each target path matches a known safe pattern before deletion
5. THE Cleanup_Script SHALL log the full path of every deleted file when verbose mode is enabled (`--verbose`)

### Requirement 11: CLI Interface

**User Story:** As a developer, I want a clear command-line interface, so that I can run cleanup manually with different options.

#### Acceptance Criteria

1. THE Cleanup_Script SHALL accept the following subcommands: `run`, `dry-run`, `status`, `install`, `uninstall`
2. WHEN the `status` subcommand is invoked, THE Cleanup_Script SHALL display current disk usage, last cleanup date, space reclaimed in last run, and next scheduled run time
3. THE Cleanup_Script SHALL accept `--target` flag to run cleanup for a specific Cleanup_Target only
4. THE Cleanup_Script SHALL accept `--verbose` flag to output detailed per-file deletion information
5. THE Cleanup_Script SHALL display a progress indicator during cleanup execution
