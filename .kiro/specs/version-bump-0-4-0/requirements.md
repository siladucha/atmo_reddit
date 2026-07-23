# Requirements Document

## Introduction

Обновление версии системы RAMP с 0.3.0 до 0.4.0. По semver-политике проекта, минорный bump (0.x.0) означает развёртывание новых фич. Текущий майлстоун 0.4.0: первый успешный пост через расширение (тест) + стабильный EPG pipeline. Версия должна быть синхронизирована между бэкендом и расширением браузера.

**Текущее состояние:**
- `reddit_saas/VERSION` = `0.3.0`
- `reddit_saas/pyproject.toml` → `version = "0.3.0"`
- `ramp_extension/manifest.json` → `"version": "0.3.3"` (рассинхронизировано с VERSION)
- `app/version.py` — читает из VERSION файла, экспортирует `__version__`
- `/health` эндпоинт возвращает версию
- UI footer показывает версию во всех шаблонах

## Glossary

- **VERSION_File**: Файл `reddit_saas/VERSION` — единственный источник правды для версии бэкенда
- **Extension_Manifest**: Файл `ramp_extension/manifest.json` — содержит версию расширения Chrome
- **Pyproject_File**: Файл `reddit_saas/pyproject.toml` — метаданные Python-пакета, поле `version`
- **Version_Module**: Модуль `app/version.py` — читает VERSION_File и экспортирует `__version__`
- **Health_Endpoint**: Эндпоинт `/health` — возвращает JSON с текущей версией системы
- **RAMP_System**: Платформа RAMP целиком (бэкенд + расширение браузера)

## Requirements

### Requirement 1: Обновление VERSION файла

**User Story:** As a developer, I want to update the VERSION file to 0.4.0, so that all system components read the correct version from the single source of truth.

#### Acceptance Criteria

1. WHEN the VERSION_File is read, THE Version_Module SHALL return "0.4.0" as the current version string
2. THE VERSION_File SHALL contain exactly the string "0.4.0" followed by a newline character

### Requirement 2: Синхронизация pyproject.toml

**User Story:** As a developer, I want pyproject.toml version to match the VERSION file, so that Python packaging metadata stays consistent.

#### Acceptance Criteria

1. THE Pyproject_File SHALL contain `version = "0.4.0"` in the `[project]` section
2. WHEN the system is imported, THE Pyproject_File version SHALL match the value in VERSION_File

### Requirement 3: Синхронизация версии расширения браузера

**User Story:** As a developer, I want the browser extension version to match the RAMP backend version, so that the version sync rule is enforced.

#### Acceptance Criteria

1. THE Extension_Manifest SHALL contain `"version": "0.4.0"` in its JSON structure
2. WHEN the extension is loaded, THE Extension_Manifest version SHALL equal the VERSION_File value

### Requirement 4: Верификация через Health Endpoint

**User Story:** As an operator, I want the health endpoint to report 0.4.0, so that I can verify the deployed version.

#### Acceptance Criteria

1. WHEN a GET request is made to `/health`, THE Health_Endpoint SHALL return a JSON response containing `"version": "0.4.0"`

### Requirement 5: Отображение версии в UI

**User Story:** As an operator, I want to see the correct version in the UI footer, so that I can confirm the running version visually.

#### Acceptance Criteria

1. WHILE the application is running, THE RAMP_System SHALL display "0.4.0" in the footer of all HTML pages rendered from `base.html` and `admin_base.html`

### Requirement 6: Целостность версионной синхронизации

**User Story:** As a developer, I want a single bump operation to update all version sources atomically, so that no component is left with a stale version.

#### Acceptance Criteria

1. THE RAMP_System SHALL maintain identical version strings across VERSION_File, Pyproject_File, and Extension_Manifest after the bump
2. IF any version source contains a value different from "0.4.0" after the bump, THEN THE RAMP_System SHALL be considered in an inconsistent state requiring correction
