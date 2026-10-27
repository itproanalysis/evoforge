# Requirements Document

## Introduction

EvoForge Web UI/UX Enhancement and Korean Localization introduces internationalization support (i18n) and comprehensive UI/UX improvements to the EvoForge Next.js web application. The system enables Korean and English language support with user preference persistence, implements modern component architecture with reusable design patterns, and enhances the visual design, accessibility, and user experience across all pages including Mission Control, Improvement Lab, Evidence Timeline, and Login.

## Glossary

- **Web_Application**: The Next.js-based EvoForge web UI (apps/web)
- **I18n_System**: The internationalization system managing translations and language switching
- **Language_Preference**: User's selected interface language (Korean or English)
- **UI_Component**: Reusable React component following the design system
- **Style_System**: The styling approach (Tailwind CSS or CSS modules)
- **Mission_Control_Page**: The main dashboard page for mission management
- **Lab_Page**: The Improvement Lab page for candidate review and testing
- **Evidence_Page**: The Evidence Timeline page for viewing evidence chains
- **Login_Page**: The authentication page for owner login
- **Layout_Component**: The root layout component shared across all pages
- **API_Client**: The client-side API integration module (lib/api.ts)
- **Storage_Service**: Browser local storage or cookie service for preference persistence
- **Responsive_Design**: UI that adapts to different screen sizes and devices
- **Accessibility_Compliance**: WCAG 2.1 AA compliance for web accessibility
- **Loading_State**: UI feedback during asynchronous operations
- **Error_State**: UI feedback for error conditions
- **Theme_System**: The dark theme color palette and design tokens

## Requirements

### Requirement 1: Internationalization Foundation

**User Story:** As a developer, I want a robust i18n system integrated into the web application, so that all UI text can be displayed in multiple languages.

#### Acceptance Criteria

1. THE I18n_System SHALL support Korean and English languages
2. THE I18n_System SHALL provide translation functions accessible in all React components
3. THE I18n_System SHALL load translation resources for the selected Language_Preference
4. THE I18n_System SHALL support interpolation for dynamic values in translated strings
5. THE I18n_System SHALL support pluralization rules for count-based messages
6. THE I18n_System SHALL default to English WHEN no Language_Preference is persisted

### Requirement 2: Language Preference Persistence

**User Story:** As a user, I want my language preference to be remembered across sessions, so that I don't have to select my language every time I visit.

#### Acceptance Criteria

1. WHEN a user selects a language, THE Storage_Service SHALL persist the Language_Preference
2. WHEN the Web_Application loads, THE I18n_System SHALL retrieve the Language_Preference from the Storage_Service
3. THE Storage_Service SHALL store the Language_Preference in browser local storage
4. WHEN the Language_Preference cannot be retrieved, THE I18n_System SHALL default to English
5. THE Storage_Service SHALL support Language_Preference values of "ko" and "en"

### Requirement 3: Language Switcher Component

**User Story:** As a user, I want to easily switch between Korean and English languages, so that I can read the interface in my preferred language.

#### Acceptance Criteria

1. THE Layout_Component SHALL display a language switcher UI_Component
2. WHEN a user clicks the language switcher, THE Web_Application SHALL display language options (Korean, English)
3. WHEN a user selects a language, THE I18n_System SHALL update the displayed language
4. WHEN a user selects a language, THE Storage_Service SHALL persist the new Language_Preference
5. THE language switcher SHALL display the current language selection
6. THE language switcher SHALL be accessible via keyboard navigation

### Requirement 4: Mission Control Page Translation

**User Story:** As a user, I want the Mission Control page to be fully translated, so that I can understand mission status and controls in my language.

#### Acceptance Criteria

1. THE Mission_Control_Page SHALL display all labels in the selected Language_Preference
2. THE Mission_Control_Page SHALL translate dashboard metric labels (Missions by state, Active missions, Blocked merges, etc.)
3. THE Mission_Control_Page SHALL translate button text (Run mission, Stop)
4. THE Mission_Control_Page SHALL translate input placeholders (Objective, repo_ref)
5. THE Mission_Control_Page SHALL translate mission state badges (CREATED, GENERATED, REVIEWED, RAN, PR_OPENED, CANCELLED, FAILED)
6. THE Mission_Control_Page SHALL translate error messages
7. THE Mission_Control_Page SHALL translate section headings and descriptions

### Requirement 5: Improvement Lab Page Translation

**User Story:** As a user, I want the Improvement Lab page to be fully translated, so that I can review candidates and create PRs in my language.

#### Acceptance Criteria

1. THE Lab_Page SHALL display all labels in the selected Language_Preference
2. THE Lab_Page SHALL translate section headings (Candidate diff, Tests, Server run, Sealed tests)
3. THE Lab_Page SHALL translate button text (Review, Create PR, Merge, Run on server)
4. THE Lab_Page SHALL translate input placeholders and labels (goal, repo path, base sha)
5. THE Lab_Page SHALL translate status messages (verdict, findings, sealed tests count)
6. THE Lab_Page SHALL translate error and warning messages
7. THE Lab_Page SHALL translate gate result labels (PASS, FAIL, INCONCLUSIVE)
8. THE Lab_Page SHALL translate tooltips and help text

### Requirement 6: Evidence Page Translation

**User Story:** As a user, I want the Evidence Timeline page to be fully translated, so that I can view evidence chains in my language.

#### Acceptance Criteria

1. THE Evidence_Page SHALL display all labels in the selected Language_Preference
2. THE Evidence_Page SHALL translate evidence stage names (ObjectiveVersion, Task, Candidate, Gate, Review, PR, Outcome)
3. THE Evidence_Page SHALL translate button text (Fetch evidence)
4. THE Evidence_Page SHALL translate input placeholders (evidence / command id)
5. THE Evidence_Page SHALL translate the "증거 부족" (Evidence missing) badge
6. THE Evidence_Page SHALL translate error messages
7. THE Evidence_Page SHALL translate section descriptions

### Requirement 7: Login Page Translation

**User Story:** As a user, I want the Login page to be fully translated, so that I can authenticate in my language.

#### Acceptance Criteria

1. THE Login_Page SHALL display all labels in the selected Language_Preference
2. THE Login_Page SHALL translate form labels (Username, Password)
3. THE Login_Page SHALL translate button text (Sign in)
4. THE Login_Page SHALL translate the page heading (Owner login)
5. THE Login_Page SHALL translate error messages (Invalid credentials, Too many attempts, Login failed)
6. THE Login_Page SHALL translate loading state text (Signing in...)

### Requirement 8: Layout Component Translation

**User Story:** As a user, I want the shared layout elements to be fully translated, so that navigation and metadata appear in my language.

#### Acceptance Criteria

1. THE Layout_Component SHALL display all navigation labels in the selected Language_Preference
2. THE Layout_Component SHALL translate navigation links (Mission Control, Improvement Lab, Evidence)
3. THE Layout_Component SHALL translate page title and description metadata
4. THE Layout_Component SHALL translate the API base URL label
5. THE Layout_Component SHALL translate footer text

### Requirement 9: Translation Resource Files

**User Story:** As a developer, I want well-organized translation files, so that translations are maintainable and easy to update.

#### Acceptance Criteria

1. THE I18n_System SHALL load translations from separate resource files for each language
2. THE Web_Application SHALL organize translations by page or feature domain
3. THE I18n_System SHALL support nested translation keys for hierarchical organization
4. THE Web_Application SHALL include English (en) translation files
5. THE Web_Application SHALL include Korean (ko) translation files
6. THE translation files SHALL use JSON or similar structured format

### Requirement 10: Style System Implementation

**User Story:** As a developer, I want a modern styling approach, so that styles are maintainable and consistent across components.

#### Acceptance Criteria

1. THE Web_Application SHALL implement a Style_System (Tailwind CSS or CSS modules)
2. THE Style_System SHALL replace inline styles in existing components
3. THE Style_System SHALL support the existing dark theme color palette
4. THE Style_System SHALL provide reusable utility classes or style definitions
5. THE Style_System SHALL integrate with the Next.js build configuration

### Requirement 11: Design Token System

**User Story:** As a developer, I want centralized design tokens, so that colors, spacing, and typography are consistent.

#### Acceptance Criteria

1. THE Theme_System SHALL define color tokens for background, border, text, and accent colors
2. THE Theme_System SHALL define spacing tokens for consistent layout spacing
3. THE Theme_System SHALL define typography tokens for font sizes, weights, and line heights
4. THE Theme_System SHALL define border radius tokens for consistent corner rounding
5. THE Theme_System SHALL preserve the existing dark theme color values
6. THE UI_Component SHALL reference design tokens instead of hardcoded values

### Requirement 12: Reusable Button Component

**User Story:** As a developer, I want a reusable Button component, so that button styles and behaviors are consistent.

#### Acceptance Criteria

1. THE Web_Application SHALL provide a Button UI_Component
2. THE Button SHALL support variant props (primary, secondary, danger, ghost)
3. THE Button SHALL support size props (small, medium, large)
4. THE Button SHALL support disabled state with appropriate visual feedback
5. THE Button SHALL support loading state with spinner or text change
6. THE Button SHALL be keyboard accessible
7. THE Button SHALL apply consistent focus styles

### Requirement 13: Reusable Input Component

**User Story:** As a developer, I want a reusable Input component, so that form inputs have consistent styling and behavior.

#### Acceptance Criteria

1. THE Web_Application SHALL provide an Input UI_Component
2. THE Input SHALL support text, password, and other HTML input types
3. THE Input SHALL support placeholder text
4. THE Input SHALL support disabled state
5. THE Input SHALL support error state with visual indicator
6. THE Input SHALL apply consistent focus styles
7. THE Input SHALL be keyboard accessible

### Requirement 14: Reusable Card Component

**User Story:** As a developer, I want a reusable Card component, so that content containers have consistent styling.

#### Acceptance Criteria

1. THE Web_Application SHALL provide a Card UI_Component
2. THE Card SHALL support children content rendering
3. THE Card SHALL apply consistent background, border, and padding styles
4. THE Card SHALL support optional header and footer sections
5. THE Card SHALL match the existing card visual design

### Requirement 15: Loading State Component

**User Story:** As a user, I want clear visual feedback during loading operations, so that I know the application is processing my request.

#### Acceptance Criteria

1. THE Web_Application SHALL provide a Loading UI_Component
2. THE Loading component SHALL display a spinner or skeleton animation
3. WHEN an asynchronous operation is in progress, THE Web_Application SHALL display the Loading component
4. THE Loading component SHALL include translated loading text
5. THE Loading component SHALL be visually distinct from content areas

### Requirement 16: Error State Component

**User Story:** As a user, I want clear error messages when operations fail, so that I understand what went wrong.

#### Acceptance Criteria

1. THE Web_Application SHALL provide an Error UI_Component
2. THE Error component SHALL display translated error messages
3. THE Error component SHALL use a distinct error color (red tone)
4. WHEN an API call fails, THE Web_Application SHALL display the Error component
5. THE Error component SHALL support dismissible state WHERE appropriate

### Requirement 17: Mission State Badge Component

**User Story:** As a user, I want mission states to be visually distinct, so that I can quickly understand mission status.

#### Acceptance Criteria

1. THE Web_Application SHALL provide a Badge UI_Component for mission states
2. THE Badge SHALL apply color coding based on state (green for PR_OPENED, red for FAILED/CANCELLED, blue for RAN/REVIEWED, amber for others)
3. THE Badge SHALL display translated state text
4. THE Badge SHALL have rounded corners and appropriate padding
5. THE Badge SHALL be readable with sufficient contrast

### Requirement 18: Responsive Layout for Mission Control

**User Story:** As a user, I want Mission Control to work well on different screen sizes, so that I can use it on mobile or tablet devices.

#### Acceptance Criteria

1. THE Mission_Control_Page SHALL implement Responsive_Design
2. WHEN screen width is less than 768px, THE dashboard metrics SHALL stack vertically
3. WHEN screen width is less than 768px, THE mission input form SHALL stack vertically
4. THE Mission_Control_Page SHALL remain usable on screens as small as 320px width
5. THE Mission_Control_Page SHALL use relative units (rem, em, %) for sizing WHERE appropriate

### Requirement 19: Responsive Layout for Lab Page

**User Story:** As a user, I want the Improvement Lab to work well on different screen sizes, so that I can review candidates on any device.

#### Acceptance Criteria

1. THE Lab_Page SHALL implement Responsive_Design
2. WHEN screen width is less than 768px, THE form inputs SHALL stack vertically
3. WHEN screen width is less than 768px, THE button groups SHALL stack vertically
4. THE Lab_Page SHALL remain usable on screens as small as 320px width
5. THE code blocks SHALL be horizontally scrollable on narrow screens

### Requirement 20: Keyboard Navigation Support

**User Story:** As a user relying on keyboard navigation, I want all interactive elements to be keyboard accessible, so that I can use the application without a mouse.

#### Acceptance Criteria

1. THE Web_Application SHALL support tab navigation through all interactive elements
2. THE UI_Component SHALL provide visible focus indicators
3. THE Web_Application SHALL support Enter key activation for buttons
4. THE language switcher SHALL be navigable with keyboard
5. THE form inputs SHALL be navigable with keyboard tab order

### Requirement 21: Screen Reader Accessibility

**User Story:** As a user relying on screen readers, I want proper semantic markup and labels, so that I can understand and navigate the application.

#### Acceptance Criteria

1. THE Web_Application SHALL use semantic HTML elements (button, nav, main, header, footer)
2. THE UI_Component SHALL include appropriate ARIA labels WHERE semantic HTML is insufficient
3. THE form inputs SHALL have associated label elements
4. THE mission state badges SHALL include aria-label with translated text
5. THE loading states SHALL announce status to screen readers

### Requirement 22: Color Contrast Compliance

**User Story:** As a user with visual impairments, I want sufficient color contrast, so that I can read all text content.

#### Acceptance Criteria

1. THE Theme_System SHALL ensure text-to-background contrast meets WCAG 2.1 AA standards (4.5:1 for normal text)
2. THE Button component SHALL maintain sufficient contrast in all states
3. THE error messages SHALL maintain sufficient contrast
4. THE disabled UI elements SHALL be visually distinguishable but may have reduced contrast

### Requirement 23: Focus Management

**User Story:** As a keyboard user, I want logical focus management, so that I can efficiently navigate through the interface.

#### Acceptance Criteria

1. WHEN a modal or dialog opens, THE Web_Application SHALL move focus to the first interactive element
2. WHEN a modal or dialog closes, THE Web_Application SHALL restore focus to the triggering element
3. THE Web_Application SHALL trap focus within modal dialogs
4. THE Web_Application SHALL skip to main content link WHERE appropriate

### Requirement 24: Enhanced Data Visualization for Metrics

**User Story:** As a user, I want better visual representation of dashboard metrics, so that I can quickly understand system status.

#### Acceptance Criteria

1. THE Mission_Control_Page SHALL display metrics in visually distinct Card components
2. THE Mission_Control_Page SHALL use visual hierarchy (label size, color, weight) to distinguish metric names from values
3. THE Mission_Control_Page SHALL group related metrics together
4. THE Mission_Control_Page SHALL use color coding for critical metrics (e.g., blocked merges in warning color)
5. WHERE numeric thresholds apply, THE Mission_Control_Page SHALL apply color coding (green for healthy, amber for warning, red for critical)

### Requirement 25: Enhanced Mission Timeline Visualization

**User Story:** As a user, I want to see mission progress visually, so that I understand where a mission is in its lifecycle.

#### Acceptance Criteria

1. THE Evidence_Page SHALL display evidence stages in a visual timeline
2. THE Evidence_Page SHALL indicate completed stages with visual styling
3. THE Evidence_Page SHALL indicate missing evidence with warning indicators
4. THE Evidence_Page SHALL connect timeline stages with visual connectors
5. THE timeline SHALL work on mobile screens with horizontal scroll or vertical stacking

### Requirement 26: Improved Error Handling UI

**User Story:** As a user, I want helpful error messages, so that I know how to resolve issues.

#### Acceptance Criteria

1. WHEN an API call fails with 402, THE Web_Application SHALL display a translated budget exhausted message
2. WHEN an API call fails with 429, THE Web_Application SHALL display a translated rate limit message
3. WHEN an API call fails with network error, THE Web_Application SHALL display a translated connection error message
4. WHEN an operation fails, THE Error component SHALL display actionable guidance WHERE possible
5. THE Error component SHALL display the error type or code for debugging

### Requirement 27: Loading State Improvements

**User Story:** As a user, I want clear feedback during long operations, so that I know the application is working.

#### Acceptance Criteria

1. WHEN a mission is running, THE Mission_Control_Page SHALL display progress indication
2. WHEN evidence is loading, THE Evidence_Page SHALL display a loading skeleton or spinner
3. WHEN API calls take longer than 500ms, THE Web_Application SHALL display loading feedback
4. THE Loading component SHALL include translated status text (e.g., "Loading mission...", "Running tests...")
5. THE Loading component SHALL disable interactive elements to prevent duplicate requests

### Requirement 28: Component Library Documentation

**User Story:** As a developer, I want documentation for UI components, so that I know how to use them correctly.

#### Acceptance Criteria

1. THE Web_Application SHALL include JSDoc comments for all UI_Component exports
2. THE JSDoc comments SHALL document component props and their types
3. THE JSDoc comments SHALL include usage examples
4. THE JSDoc comments SHALL document accessibility considerations
5. WHERE applicable, THE Web_Application SHALL include Storybook stories or similar component showcase

### Requirement 29: Migration of Existing Pages

**User Story:** As a developer, I want all existing pages migrated to the new component system, so that the UI is consistent.

#### Acceptance Criteria

1. THE Mission_Control_Page SHALL use the reusable UI_Component library
2. THE Lab_Page SHALL use the reusable UI_Component library
3. THE Evidence_Page SHALL use the reusable UI_Component library
4. THE Login_Page SHALL use the reusable UI_Component library
5. THE Layout_Component SHALL use the reusable UI_Component library
6. THE migrated pages SHALL maintain functional equivalence to existing pages
7. THE migrated pages SHALL pass existing functionality tests

### Requirement 30: API Error Translation

**User Story:** As a user, I want API error messages in my selected language, so that I understand what went wrong.

#### Acceptance Criteria

1. WHEN the API_Client receives an error response, THE Web_Application SHALL translate the error message
2. THE I18n_System SHALL provide translations for common HTTP status codes
3. THE I18n_System SHALL provide translations for application-specific error codes
4. WHEN an error has no translation, THE Web_Application SHALL display the original error message
5. THE Error component SHALL display both translated error summary and technical details WHERE helpful
