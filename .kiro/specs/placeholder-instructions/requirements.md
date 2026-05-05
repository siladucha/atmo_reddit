# Requirements Document

## Introduction

Добавить инструктивные placeholder-тексты (подсказки) во все текстовые поля ввода в админ-панели Reddit Marketing SaaS. Placeholder отображается серым текстом на фоне пустого поля и исчезает при вводе данных. Цель — помочь администратору понять, какие данные ожидаются в каждом поле, без обращения к документации.

## Glossary

- **Admin_Panel**: Административная панель платформы Reddit Marketing SaaS, использующая тёмную тему (`admin_base.html`), Jinja2-шаблоны, HTMX и Tailwind CSS
- **Placeholder**: HTML-атрибут `placeholder` на элементах `<input>` и `<textarea>`, отображающий подсказку серым текстом внутри пустого поля
- **Text_Input_Field**: Элемент формы типа `<input type="text">`, `<input type="email">`, `<input type="password">` или `<textarea>`, предназначенный для ввода текстовых данных пользователем
- **Hint_Text**: Краткий пояснительный текст, описывающий ожидаемый формат или содержание поля ввода
- **Template**: Jinja2-шаблон (`.html` файл) в директории `reddit_saas/app/templates/`
- **Partial**: HTMX-фрагмент шаблона в директории `reddit_saas/app/templates/partials/`, используемый для inline CRUD-операций

## Requirements

### Requirement 1: Placeholder for Client Profile Fields

**User Story:** As an admin, I want to see instructive placeholder text in client profile form fields, so that I understand what data to enter for each client attribute.

#### Acceptance Criteria

1. WHEN the client_name field is empty, THE Admin_Panel SHALL display the Placeholder "e.g. Acme Corp" in the client_name Text_Input_Field
2. WHEN the brand_name field is empty, THE Admin_Panel SHALL display the Placeholder "e.g. AcmeTech" in the brand_name Text_Input_Field
3. WHEN the company_profile field is empty, THE Admin_Panel SHALL display the Placeholder "Brief description of the company, its products, and market position" in the company_profile textarea
4. WHEN the company_worldview field is empty, THE Admin_Panel SHALL display the Placeholder "Company's values, mission, and perspective on the industry" in the company_worldview textarea
5. WHEN the company_problem field is empty, THE Admin_Panel SHALL display the Placeholder "Key problem the company solves for its customers" in the company_problem textarea
6. WHEN the competitive_landscape field is empty, THE Admin_Panel SHALL display the Placeholder "Main competitors and how the company differentiates" in the competitive_landscape textarea
7. WHEN the brand_voice field is empty, THE Admin_Panel SHALL display the Placeholder "Tone and style of communication, e.g. professional, friendly, technical" in the brand_voice textarea
8. WHEN the icp_profiles field is empty, THE Admin_Panel SHALL display the Placeholder "Ideal customer profiles: roles, industries, pain points" in the icp_profiles textarea

### Requirement 2: Placeholder Consistency Across Duplicate Forms

**User Story:** As an admin, I want the same placeholder text for the same field across all forms where it appears, so that the experience is consistent.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display identical Placeholder text for the client_name field in admin_client_new.html, admin_client_detail.html, and admin_onboard_step1.html Templates
2. THE Admin_Panel SHALL display identical Placeholder text for the brand_name field in admin_client_new.html, admin_client_detail.html, and admin_onboard_step1.html Templates
3. THE Admin_Panel SHALL display identical Placeholder text for all client profile textarea fields (company_profile, company_worldview, company_problem, competitive_landscape, brand_voice, icp_profiles) across admin_client_new.html, admin_client_detail.html, and admin_onboard_step1.html Templates

### Requirement 3: Placeholder for User Management Fields

**User Story:** As an admin, I want to see placeholder hints in user creation fields, so that I know the expected format for email, password, and name.

#### Acceptance Criteria

1. WHEN the email field is empty, THE Admin_Panel SHALL display the Placeholder "user@example.com" in the email Text_Input_Field on admin_users.html
2. WHEN the password field is empty, THE Admin_Panel SHALL display the Placeholder "Minimum 8 characters" in the password Text_Input_Field on admin_users.html
3. WHEN the full_name field is empty, THE Admin_Panel SHALL display the Placeholder "e.g. John Smith" in the full_name Text_Input_Field on admin_users.html

### Requirement 4: Placeholder for Keyword Field

**User Story:** As an admin, I want to see an example keyword in the keyword input field, so that I understand the expected format.

#### Acceptance Criteria

1. WHEN the keyword name field is empty, THE Admin_Panel SHALL display the Placeholder "e.g. cybersecurity tools" in the keyword name Text_Input_Field on admin_keywords.html
2. WHEN the keyword name field is empty, THE Admin_Panel SHALL display the Placeholder "e.g. breathing exercises" in the keyword name Text_Input_Field on admin_onboard_step3.html

### Requirement 5: Placeholder for Persona Fields

**User Story:** As an admin, I want to see placeholder hints in persona creation fields, so that I understand what a persona name and voice profile should contain.

#### Acceptance Criteria

1. WHEN the persona_name field is empty, THE Admin_Panel SHALL display the Placeholder "e.g. Security Expert" in the persona_name Text_Input_Field on admin_personas.html
2. WHEN the voice_profile field is empty, THE Admin_Panel SHALL display the Placeholder "Communication style, tone, and personality traits" in the voice_profile Text_Input_Field on admin_personas.html
3. WHEN the persona_name field is empty, THE Admin_Panel SHALL display the Placeholder "e.g. Wellness Enthusiast" in the persona_name Text_Input_Field on admin_onboard_step5.html

### Requirement 6: Placeholder for Onboarding Wizard Subreddit Field

**User Story:** As an admin, I want to see an example subreddit name in the onboarding wizard, so that I know the expected format.

#### Acceptance Criteria

1. WHEN the subreddit_name field is empty, THE Admin_Panel SHALL display the Placeholder "e.g. cybersecurity" in the subreddit_name Text_Input_Field on admin_onboard_step2.html

### Requirement 7: Preserve Existing Placeholders

**User Story:** As an admin, I want existing placeholder text to remain unchanged, so that no current UX guidance is lost.

#### Acceptance Criteria

1. THE Admin_Panel SHALL retain the existing Placeholder "e.g. cybersecurity" on the subreddit_name field in admin_subreddits.html
2. THE Admin_Panel SHALL retain the existing Placeholder "e.g. create" on the action filter field in admin_audit_logs.html
3. THE Admin_Panel SHALL retain the existing Placeholder "New pwd" on the new_password field in the admin_user_row.html Partial
4. THE Admin_Panel SHALL retain the existing Placeholder "subreddit_name" on the subreddit_name field in admin_onboard_step2.html
5. THE Admin_Panel SHALL retain the existing Placeholder "e.g. Wellness Enthusiast" on the persona_name field in admin_onboard_step5.html
6. THE Admin_Panel SHALL retain the existing Placeholder "Describe the persona's voice, tone, and communication style..." on the voice_profile field in admin_onboard_step5.html

### Requirement 8: Placeholder Visual Styling

**User Story:** As an admin, I want placeholder text to be visually distinct from entered data, so that I can easily tell the difference.

#### Acceptance Criteria

1. THE Admin_Panel SHALL render Placeholder text in a muted color that contrasts with the white user-entered text on the dark-themed background
2. WHEN a user types into a Text_Input_Field, THE Admin_Panel SHALL hide the Placeholder text
3. WHEN a user clears a Text_Input_Field, THE Admin_Panel SHALL display the Placeholder text again

### Requirement 9: Placeholder Accessibility

**User Story:** As an admin using assistive technology, I want placeholder text to not replace proper labels, so that screen readers can identify each field.

#### Acceptance Criteria

1. THE Admin_Panel SHALL retain all existing `<label>` elements alongside Placeholder attributes on Text_Input_Fields
2. IF a Text_Input_Field has a Placeholder, THEN THE Admin_Panel SHALL ensure the corresponding `<label>` element remains present and visible
