# Requirements Document

## Introduction

The UX Manual Overlay is a mandatory unified component present on every screen in the RAMP platform. It provides users with an interactive contextual map of their position in the product flow, replacing traditional static help documentation with an integrated understanding layer. The overlay explains where the user is, what they can do, and where they are going next — tailored to their role and current lifecycle stage.

## Glossary

- **Manual_Overlay**: The unified UX explanation interface component that opens when the Manual button is triggered. Displays screen context, purpose, available actions, role-specific behavior, and flow position.
- **Manual_Button**: A persistent "Manual" / "How it works" button rendered on every screen across all roles in the RAMP platform.
- **Flow_Position_Indicator**: A mandatory embedded visual indicator showing the user's current step within the system lifecycle (e.g., "Flow: Step X / Y" or "Cycle: Trial → Execution → Verification → Billing").
- **Screen_Context**: Metadata describing the screen's position in the overall system flow — lifecycle stage, what preceded the current screen, and what follows.
- **Lifecycle_Stage**: A defined phase in the user journey: onboarding, trial, execution, review, or billing.
- **RAMP_Platform**: The Reddit Avatar Management Platform (FastAPI + Jinja2 + HTMX + Tailwind CSS).
- **Manual_Content_Schema**: The unified standard structure that all Manual content must follow: screen context, screen purpose, available actions, role-specific behavior, and flow position.
- **Role**: One of the 7 RBAC roles in RAMP: owner, partner, client_admin, client_manager, client_viewer, avatar_manager, b2c_user.
- **Base_Template**: One of the two layout templates in the platform — `admin_base.html` (dark theme) or `base.html`/`client_base.html` (light theme).

## Requirements

### Requirement 1: Manual Button Presence

**User Story:** As a user of any role, I want to see a "Manual" / "How it works" button on every screen, so that I can access contextual help at any point in my workflow.

#### Acceptance Criteria

1. THE Manual_Button SHALL be rendered on every screen of the RAMP_Platform regardless of the user's Role.
2. THE Manual_Button SHALL be included in both Base_Template variants (admin_base.html dark theme and base.html/client_base.html light theme).
3. THE Manual_Button SHALL remain visible and accessible across all screen states: empty, loading, error, and success.
4. THE Manual_Button SHALL have a consistent visual position and styling across all screens within a given Base_Template.

### Requirement 2: Manual Overlay Opening

**User Story:** As a user, I want the Manual button to open a unified overlay interface, so that I get contextual information without navigating away from my current screen.

#### Acceptance Criteria

1. WHEN the Manual_Button is clicked, THE Manual_Overlay SHALL open as an overlay on the current screen without triggering a page navigation.
2. WHEN the Manual_Overlay is open, THE RAMP_Platform SHALL display content following the Manual_Content_Schema for the current screen.
3. WHEN the Manual_Overlay is open, THE RAMP_Platform SHALL allow the user to close the overlay and return to the underlying screen without loss of state.
4. IF the Manual_Overlay fails to load content, THEN THE RAMP_Platform SHALL display a fallback message indicating that manual content is unavailable for the current screen.

### Requirement 3: Screen Context in Overall Flow

**User Story:** As a user, I want to understand where the current screen sits in the overall system flow, so that I know what lifecycle stage I am in and what comes before and after.

#### Acceptance Criteria

1. THE Manual_Overlay SHALL display the current Lifecycle_Stage (onboarding, trial, execution, review, or billing) for the screen being viewed.
2. THE Manual_Overlay SHALL describe what preceded the current screen in the user's workflow.
3. THE Manual_Overlay SHALL describe what follows the current screen in the user's workflow.
4. THE Manual_Overlay SHALL present the Screen_Context information in a consistent format across all screens.

### Requirement 4: Screen Purpose

**User Story:** As a user, I want to understand what business function the current screen serves, so that I know what I am expected to do here.

#### Acceptance Criteria

1. THE Manual_Overlay SHALL describe what the user does on the current screen.
2. THE Manual_Overlay SHALL explain what business function or workflow step the current screen serves within the RAMP_Platform.
3. THE Manual_Overlay SHALL use language appropriate to the user's Role context (technical for admin roles, business-focused for client roles).

### Requirement 5: Available Actions

**User Story:** As a user, I want to see what actions are available on the current screen, so that I understand my options and their meaning in the system.

#### Acceptance Criteria

1. THE Manual_Overlay SHALL list all actions available to the user on the current screen.
2. THE Manual_Overlay SHALL explain what each available action means in the context of the RAMP_Platform workflow.
3. WHEN the user's Role restricts available actions, THE Manual_Overlay SHALL display only the actions accessible to that Role.

### Requirement 6: Role-Specific Behavior

**User Story:** As a user, I want to understand how the screen behaves differently for my role, so that I know what is visible and actionable for me versus other roles.

#### Acceptance Criteria

1. THE Manual_Overlay SHALL describe how the current screen's content and actions differ depending on the user's Role.
2. THE Manual_Overlay SHALL indicate which elements on the screen are role-restricted.
3. WHEN a screen has identical behavior across all roles, THE Manual_Overlay SHALL state that the screen behavior is uniform.

### Requirement 7: Flow Position Indicator

**User Story:** As a user, I want to see an embedded indicator of my current position in the system flow, so that I always understand "where I am now" and "where I'm going next."

#### Acceptance Criteria

1. THE Manual_Overlay SHALL display a Flow_Position_Indicator showing the user's current step within the system lifecycle.
2. THE Flow_Position_Indicator SHALL use a consistent format across all screens (e.g., "Flow: Step X / Y" or "Cycle: Trial → Execution → Verification → Billing").
3. THE Flow_Position_Indicator SHALL visually highlight the current step and distinguish it from completed and upcoming steps.
4. THE Flow_Position_Indicator SHALL be consistent with the Flow_Position_Indicator displayed on all other screens in the same lifecycle flow.

### Requirement 8: Unified Component Architecture

**User Story:** As a developer, I want the Manual Overlay to be a single unified component, so that it does not depend on local UI implementation details of individual pages.

#### Acceptance Criteria

1. THE Manual_Overlay SHALL be implemented as a single reusable component included via the Base_Template (not duplicated per page).
2. THE Manual_Overlay SHALL load its content dynamically based on the current screen's route or identifier.
3. THE Manual_Overlay SHALL function independently of page-specific JavaScript or CSS.
4. WHEN a new screen is added to the RAMP_Platform, THE Manual_Overlay SHALL require only a content definition entry for the new screen without modifying the component implementation.

### Requirement 9: Complete Coverage

**User Story:** As a QA engineer, I want to verify that every screen in the system has a Manual with complete content, so that no user encounters a screen without contextual explanation.

#### Acceptance Criteria

1. THE RAMP_Platform SHALL have Manual content defined for 100% of screens accessible to any Role.
2. THE Manual content for every screen SHALL contain a Flow_Position_Indicator.
3. THE Manual content for every screen SHALL follow the complete Manual_Content_Schema (screen context, purpose, available actions, role-specific behavior, flow position).
4. IF a screen is accessed that has no Manual content defined, THEN THE RAMP_Platform SHALL log a warning indicating the missing manual entry.

### Requirement 10: Theme Compatibility

**User Story:** As a user, I want the Manual Overlay to match the visual theme of the platform I am using, so that it feels native and not like a separate system.

#### Acceptance Criteria

1. WHEN rendered within admin_base.html, THE Manual_Overlay SHALL use the dark theme styling consistent with the admin panel.
2. WHEN rendered within base.html or client_base.html, THE Manual_Overlay SHALL use the light theme styling consistent with the client portal.
3. THE Manual_Overlay SHALL use Tailwind CSS classes consistent with the RAMP_Platform design system.
