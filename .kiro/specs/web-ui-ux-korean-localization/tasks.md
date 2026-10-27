# Implementation Plan: EvoForge Web UI/UX Enhancement and Korean Localization

## Overview

This implementation plan converts the feature design into actionable coding tasks. The implementation follows a bottom-up approach: infrastructure first (dependencies, configuration), then core components, then i18n integration, and finally page migrations. Each task builds on previous tasks, with checkpoints for validation.

## Tasks

- [ ] 1. Set up project dependencies and configuration
  - [ ] 1.1 Install required npm packages
    - Install next-intl, tailwindcss, postcss, autoprefixer, and development dependencies
    - Update package.json with exact versions
    - Run `npm install` to verify dependencies resolve correctly
    - _Requirements: 10.1, 10.5_
  
  - [ ] 1.2 Configure Tailwind CSS with design tokens
    - Create/update `tailwind.config.ts` with color palette, spacing scale, typography tokens
    - Define dark theme colors: background (#0b0e14, #141b2d, #111726), borders (#263048, #33405c), text (#e8edf5, #8b96ad), accents (#2563eb, #22c55e, #ef4444, #f59e0b, #38bdf8)
    - Configure content paths to scan for Tailwind classes
    - Update `postcss.config.js` if needed
    - _Requirements: 10.1, 10.3, 11.1, 11.5_
  
  - [ ] 1.3 Create global styles file
    - Create/update `apps/web/styles/globals.css`
    - Import Tailwind directives (@tailwind base, components, utilities)
    - Define CSS variables for theme colors matching design tokens
    - Set base body styles (margin: 0, font-family, background, color)
    - _Requirements: 10.3, 11.5_
  
  - [ ] 1.4 Configure next-intl core setup
    - Create `apps/web/lib/i18n.ts` with locale definitions (en, ko) and getRequestConfig
    - Export locales array, Locale type, and defaultLocale constant
    - Implement message loading from JSON files by locale
    - Set timeZone and now configuration
    - _Requirements: 1.1, 1.2, 1.6_
  
  - [ ] 1.5 Create next-intl middleware for locale routing
    - Create `apps/web/middleware.ts` using createMiddleware from next-intl
    - Configure locale routing with localePrefix: 'as-needed'
    - Set matcher to handle '/' and '/(ko|en)/:path*' routes
    - _Requirements: 1.1, 3.3_

- [ ] 2. Create translation files and storage utilities
  - [ ] 2.1 Create English translation file (en.json)
    - Create `apps/web/messages/en.json` with all translation keys
    - Organize by namespaces: common, languages, navigation, mission-control, lab, evidence, login, layout, errors
    - Include all labels, buttons, placeholders, error messages, state names from design
    - Use ICU MessageFormat syntax for interpolation (e.g., "Hello {name}")
    - _Requirements: 4.1-4.7, 5.1-5.8, 6.1-6.7, 7.1-7.5, 8.1-8.5, 9.1-9.6, 30.1-30.4_
  
  - [ ] 2.2 Create Korean translation file (ko.json)
    - Create `apps/web/messages/ko.json` with all translation keys matching en.json structure
    - Translate all English content to Korean
    - Maintain same interpolation placeholders as English version
    - Verify JSON syntax validity
    - _Requirements: 4.1-4.7, 5.1-5.8, 6.1-6.7, 7.1-7.5, 8.1-8.5, 9.1-9.6, 30.1-30.4_
  
  - [ ] 2.3 Implement language storage utility
    - Create `apps/web/lib/languageStorage.ts`
    - Implement getStoredLanguage() with localStorage read and validation
    - Implement setStoredLanguage(locale) with localStorage write and error handling
    - Handle SSR by checking typeof window !== 'undefined'
    - Return null on storage errors (catch and ignore)
    - _Requirements: 2.1, 2.3, 2.4, 2.5_

- [ ] 3. Build core UI component library
  - [ ] 3.1 Create Button component
    - Create `apps/web/components/ui/Button.tsx`
    - Define ButtonProps interface with variant, size, loading, disabled, children, and HTML button attributes
    - Implement variants: primary (bg-blue-600), secondary (bg-cyan-600), danger (bg-red-600), ghost (border-only)
    - Implement sizes: sm, md, lg with appropriate padding and text size
    - Implement loading state with spinner and aria-busy attribute
    - Implement disabled state with reduced opacity and not-allowed cursor
    - Apply focus-visible ring with brand color
    - Include proper TypeScript types extending ButtonHTMLAttributes
    - _Requirements: 12.1-12.7_
  
  - [ ]* 3.2 Write property test for Button disabled state
    - **Property 5: Button disabled state prevents interaction**
    - **Validates: Requirements 12.4, 12.5**
    - Use fast-check to generate random disabled/loading/variant combinations
    - Verify onClick is NOT called when disabled=true or loading=true
    - Verify onClick IS called when both are false
    - Run 100 iterations minimum
  
  - [ ]* 3.3 Write property test for Button keyboard activation
    - **Property 6: Button keyboard activation**
    - **Validates: Requirements 12.6, 20.3**
    - Use fast-check to generate random Button props (non-disabled)
    - Simulate Enter and Space key presses with focused button
    - Verify onClick handler is called for both keys
    - Run 100 iterations minimum
  
  - [ ] 3.4 Create Input component
    - Create `apps/web/components/ui/Input.tsx`
    - Define InputProps interface with error, errorMessage, label, and HTML input attributes
    - Implement base styles with dark background and border
    - Implement focus state with blue ring and brighter border
    - Implement error state with red border and aria-invalid attribute
    - Implement disabled state with reduced opacity and not-allowed cursor
    - Render label element when label prop provided
    - Render error message with aria-describedby when error=true
    - _Requirements: 13.1-13.7_
  
  - [ ]* 3.5 Write property test for Input error state
    - **Property 7: Input error state displays visual indicator**
    - **Validates: Requirements 13.6**
    - Use fast-check to generate random Input props with error boolean
    - Verify error border class and aria-invalid present when error=true
    - Verify error styling absent when error=false
    - Run 100 iterations minimum
  
  - [ ] 3.6 Create Card component
    - Create `apps/web/components/ui/Card.tsx`
    - Define CardProps interface with children, header, footer, className
    - Implement container with background (#141b2d), border (#263048), rounded corners (10px), padding (14px)
    - Conditionally render header section above children
    - Render children in main body area
    - Conditionally render footer section below children
    - Support className prop for additional styling
    - _Requirements: 14.1-14.5_
  
  - [ ] 3.7 Create Loading component
    - Create `apps/web/components/ui/Loading.tsx`
    - Define LoadingProps interface with message (optional translated text) and size
    - Implement animated spinner using CSS animation or SVG
    - Implement sizes: sm (16px), md (32px), lg (48px)
    - Render translated message below spinner when provided
    - Add role="status" and aria-live="polite" for screen readers
    - Add aria-label with loading message
    - _Requirements: 15.1-15.5_
  
  - [ ] 3.8 Create Error component
    - Create `apps/web/components/ui/Error.tsx`
    - Define ErrorProps interface with message (required), details (optional), dismissible, onDismiss
    - Implement red background tint and red text (#ef4444)
    - Render translated error message prominently
    - Render optional technical details in expandable/collapsed section
    - Implement dismiss button when dismissible=true with aria-label
    - Add role="alert" and aria-live="assertive" for screen readers
    - _Requirements: 16.1-16.5, 26.1-26.5_
  
  - [ ] 3.9 Create Badge component for mission states
    - Create `apps/web/components/ui/Badge.tsx`
    - Define BadgeProps interface with state (MissionState type) and children
    - Implement color mapping: PR_OPENED=green (#22c55e), FAILED/CANCELLED=red (#ef4444), RAN/REVIEWED=blue (#38bdf8), others=amber (#f59e0b)
    - Apply inline display, rounded pill shape (border-radius: 20px), small padding (2px 10px)
    - Use dark background text color (#0b0e14) for readability
    - Add aria-label with full translated state description
    - _Requirements: 17.1-17.5_
  
  - [ ] 3.10 Create barrel export for UI components
    - Create `apps/web/components/ui/index.ts`
    - Export all UI components: Button, Input, Card, Loading, Error, Badge
    - Enables cleaner imports: `import { Button, Input } from '@/components/ui'`
    - _Requirements: 12.1, 13.1, 14.1, 15.1, 16.1, 17.1_

- [ ] 4. Checkpoint - Verify component library builds and renders
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Create LanguageSwitcher and integrate i18n provider
  - [ ] 5.1 Create LanguageSwitcher component
    - Create `apps/web/components/LanguageSwitcher.tsx`
    - Define LanguageSwitcherProps interface with currentLocale
    - Implement dropdown or button group showing language options
    - Highlight current language selection
    - On language selection, call setStoredLanguage(newLocale)
    - Use Next.js router to navigate to /${newLocale}/current-page
    - Apply keyboard navigation support (arrow keys, enter/space)
    - Add aria-label="Select language" for accessibility
    - Use useTranslations hook to get language names from 'languages' namespace
    - _Requirements: 3.1-3.6_
  
  - [ ] 5.2 Create API error translation utility
    - Create `apps/web/lib/apiErrors.ts`
    - Implement getErrorMessageKey(error) function
    - Map HTTP status codes to translation keys: 401→errors.unauthorized, 402→errors.budget-exhausted, 403→errors.forbidden, 404→errors.not-found, 429→errors.rate-limit, 5xx→errors.server-error
    - Map network errors to errors.network-error
    - Default to errors.unknown for unmapped errors
    - _Requirements: 30.1-30.5_
  
  - [ ] 5.3 Update lib/api.ts to use error translation
    - Import getErrorMessageKey from apiErrors
    - Wrap fetch error handling to include translation key
    - Attach translationKey property to thrown errors for downstream consumption
    - Preserve original error message for debugging
    - _Requirements: 30.1, 30.4_

- [ ] 6. Migrate root layout to use i18n and components
  - [ ] 6.1 Update app directory structure for locale routing
    - Create `apps/web/app/[locale]` directory
    - Move existing page files into [locale] directory (page.tsx, lab/page.tsx, evidence/page.tsx, login/page.tsx)
    - Keep API routes in `apps/web/app/api` (unchanged)
    - _Requirements: 1.1, 8.1_
  
  - [ ] 6.2 Create locale-aware root layout
    - Create `apps/web/app/[locale]/layout.tsx`
    - Import NextIntlClientProvider from next-intl
    - Get messages for current locale using server-side API
    - Wrap children with NextIntlClientProvider passing messages and locale
    - Update metadata with translated title and description
    - Replace inline styles with Tailwind classes
    - Use Button component for navigation if applicable
    - Integrate LanguageSwitcher in header
    - Translate all navigation labels, footer text, and API base label
    - _Requirements: 1.2, 8.1-8.5, 10.2, 29.5_
  
  - [ ] 6.3 Update global layout for locale parameter
    - Update `apps/web/app/layout.tsx` if it exists as root layout
    - Ensure it wraps [locale] layout correctly
    - Import globals.css to apply Tailwind styles
    - Set lang attribute dynamically based on locale if possible
    - _Requirements: 10.5_

- [ ] 7. Migrate Mission Control page
  - [ ] 7.1 Update Mission Control page to use translations
    - Update `apps/web/app/[locale]/page.tsx`
    - Add 'use client' directive
    - Import useTranslations from next-intl
    - Create t = useTranslations('mission-control')
    - Replace all hardcoded strings with t('key') calls
    - Translate heading, description, labels, buttons, metrics, states, error messages
    - _Requirements: 4.1-4.7, 29.1, 29.6_
  
  - [ ] 7.2 Update Mission Control page to use UI components
    - Replace inline-styled buttons with Button component (primary variant for "Run mission", danger for "Stop")
    - Replace input elements with Input component
    - Replace card divs with Card component
    - Use Badge component for mission state display
    - Use Error component for error display
    - Use Loading component when busy=true
    - Replace inline styles with Tailwind utility classes
    - _Requirements: 10.2, 12.1, 13.1, 14.1, 15.1, 16.1, 17.1, 29.1, 29.6_
  
  - [ ] 7.3 Implement responsive layout for Mission Control
    - Apply Tailwind responsive classes (sm:, md:, lg:) for breakpoints
    - Stack dashboard metrics vertically on screens < 768px
    - Stack mission input form vertically on screens < 768px
    - Ensure usability on screens as small as 320px
    - Test with browser DevTools responsive mode
    - _Requirements: 18.1-18.5_

- [ ] 8. Migrate Evidence page
  - [ ] 8.1 Update Evidence page to use translations
    - Update `apps/web/app/[locale]/evidence/page.tsx`
    - Add 'use client' directive
    - Import useTranslations from next-intl
    - Create t = useTranslations('evidence')
    - Replace all hardcoded strings with t('key') calls
    - Translate heading, description, input placeholder, button text, stage names, error messages
    - _Requirements: 6.1-6.7, 29.3, 29.6_
  
  - [ ] 8.2 Update Evidence page to use UI components
    - Replace inline-styled buttons with Button component
    - Replace input elements with Input component
    - Replace card divs with Card component
    - Use Badge component for evidence stage indicators
    - Use Error component for error display
    - Use Loading component during fetch
    - Replace inline styles with Tailwind utility classes
    - _Requirements: 10.2, 12.1, 13.1, 14.1, 15.1, 16.1, 17.1, 29.3, 29.6_
  
  - [ ] 8.3 Implement enhanced evidence timeline visualization
    - Create visual timeline component showing ObjectiveVersion→Task→Candidate→Gate→Review→PR→Outcome
    - Apply visual styling for completed stages (e.g., filled circles or checkmarks)
    - Apply warning indicators for missing evidence
    - Connect stages with visual connectors (lines or arrows)
    - Make timeline responsive: horizontal scroll or vertical stack on mobile
    - _Requirements: 25.1-25.5_

- [ ] 9. Checkpoint - Verify Mission Control and Evidence pages work correctly
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Migrate Improvement Lab page
  - [ ] 10.1 Update Lab page to use translations
    - Update `apps/web/app/[locale]/lab/page.tsx`
    - Add 'use client' directive
    - Import useTranslations from next-intl
    - Create t = useTranslations('lab')
    - Replace all hardcoded strings with t('key') calls
    - Translate heading, description, labels, buttons, status messages, gate results, tooltips
    - Handle interpolation for dynamic values (test counts, verdict, PR URL)
    - _Requirements: 5.1-5.8, 29.2, 29.6_
  
  - [ ] 10.2 Update Lab page to use UI components
    - Replace inline-styled buttons with Button component (various variants: primary for "Review", secondary for "Run on server", success/primary for "Create PR", danger for "Merge blocked")
    - Replace input elements with Input component
    - Replace card divs with Card component
    - Use Badge component for gate results and verdict display
    - Use Error component for error display
    - Use Loading component during async operations
    - Replace inline styles with Tailwind utility classes
    - _Requirements: 10.2, 12.1, 13.1, 14.1, 15.1, 16.1, 17.1, 29.2, 29.6_
  
  - [ ] 10.3 Implement responsive layout for Lab page
    - Apply Tailwind responsive classes for breakpoints
    - Stack form inputs vertically on screens < 768px
    - Stack button groups vertically on screens < 768px
    - Make code blocks horizontally scrollable on narrow screens
    - Ensure usability on screens as small as 320px
    - _Requirements: 19.1-19.5_

- [ ] 11. Migrate Login page
  - [ ] 11.1 Update Login page to use translations
    - Update `apps/web/app/[locale]/login/page.tsx`
    - Add 'use client' directive (if not already present)
    - Import useTranslations from next-intl
    - Create t = useTranslations('login')
    - Replace all hardcoded strings with t('key') calls
    - Translate heading, form labels, button text, error messages, loading text
    - _Requirements: 7.1-7.5, 29.4, 29.6_
  
  - [ ] 11.2 Update Login page to use UI components
    - Replace inline-styled buttons with Button component (primary variant)
    - Replace input elements with Input component (type="password" for password field)
    - Replace form container with Card component if applicable
    - Use Error component for error display
    - Use Loading component or button loading state during sign-in
    - Replace inline styles with Tailwind utility classes
    - _Requirements: 10.2, 12.1, 13.1, 14.1, 15.1, 16.1, 29.4, 29.6_

- [ ] 12. Implement accessibility enhancements
  - [ ] 12.1 Add focus management for interactive elements
    - Verify all buttons, inputs, and links have visible focus indicators (using Tailwind focus-visible classes)
    - Test tab order through all pages
    - Implement focus trap for modal dialogs if any exist
    - Ensure focus moves to first interactive element when modals open
    - _Requirements: 20.1-20.5, 23.1-23.4_
  
  - [ ] 12.2 Add ARIA labels and semantic HTML
    - Audit all components for semantic HTML usage (button, nav, main, header, footer)
    - Add aria-label to LanguageSwitcher
    - Add aria-label to mission state badges
    - Ensure form inputs have associated label elements or aria-label
    - Add role="status" to loading states
    - Add role="alert" to error states
    - _Requirements: 21.1-21.5_
  
  - [ ]* 12.3 Write property test for keyboard navigation
    - **Property 8: Tab navigation reaches all interactive elements**
    - **Validates: Requirements 20.1**
    - Use fast-check to generate random page component trees
    - Query all interactive elements (buttons, inputs, links, [role="button"])
    - Simulate repeated Tab key presses
    - Verify focus cycles through all interactive elements without skipping
    - Run 100 iterations minimum
  
  - [ ]* 12.4 Write property test for ARIA label presence
    - **Property 9: Non-semantic components have ARIA labels**
    - **Validates: Requirements 21.2**
    - Define semantic HTML element whitelist (button, input, nav, a, etc.)
    - Use fast-check to generate random component instances
    - Filter for non-semantic elements (divs with onClick, custom controls)
    - Verify presence of aria-label, aria-labelledby, or role attribute
    - Run 100 iterations minimum
  
  - [ ]* 12.5 Write property test for color contrast compliance
    - **Property 10: Theme color pairs meet contrast requirements**
    - **Validates: Requirements 22.1**
    - Define all text colors from theme: #e8edf5, #8b96ad, #cfe3ff, #93c5fd, etc.
    - Define all background colors from theme: #0b0e14, #141b2d, #111726, #0f1524, etc.
    - Use fast-check to generate all text/background pairs
    - Calculate contrast ratio using WCAG formula
    - Verify ratio >= 4.5:1 for all pairs
    - Run 100 iterations minimum

- [ ] 13. Write unit tests for components and utilities
  - [ ]* 13.1 Write unit tests for Button component
    - Test all variants render with correct classes
    - Test all sizes render with correct classes
    - Test disabled state prevents onClick
    - Test loading state shows spinner and prevents onClick
    - Test children render correctly
    - Use Vitest + React Testing Library
    - _Requirements: 12.1-12.7_
  
  - [ ]* 13.2 Write unit tests for Input component
    - Test different input types render correctly
    - Test error state applies error styling and aria-invalid
    - Test disabled state applies correct styling
    - Test label association when label prop provided
    - Test error message renders with aria-describedby
    - Use Vitest + React Testing Library
    - _Requirements: 13.1-13.7_
  
  - [ ]* 13.3 Write unit tests for language storage utility
    - Test getStoredLanguage returns stored locale
    - Test getStoredLanguage returns null when storage empty
    - Test getStoredLanguage handles invalid values
    - Test setStoredLanguage persists locale to localStorage
    - Test SSR safety (typeof window check)
    - Use Vitest with localStorage mock
    - _Requirements: 2.1-2.5_
  
  - [ ]* 13.4 Write unit tests for API error translation utility
    - Test getErrorMessageKey maps 401 to errors.unauthorized
    - Test getErrorMessageKey maps 402 to errors.budget-exhausted
    - Test getErrorMessageKey maps 404 to errors.not-found
    - Test getErrorMessageKey maps 429 to errors.rate-limit
    - Test getErrorMessageKey maps 5xx to errors.server-error
    - Test getErrorMessageKey maps network errors to errors.network-error
    - Test getErrorMessageKey defaults to errors.unknown
    - Use Vitest
    - _Requirements: 30.1-30.5_

- [ ] 14. Write property-based tests for i18n system
  - [ ]* 14.1 Write property test for i18n system availability
    - **Property 1: I18n system provides translations for all supported locales**
    - **Validates: Requirements 1.1, 1.2, 1.3**
    - Use fast-check to generate random locale (en or ko) and random translation key
    - Load messages for generated locale
    - Verify translation value is a non-empty string
    - Run 100 iterations minimum
  
  - [ ]* 14.2 Write property test for translation interpolation
    - **Property 2: Translation interpolation preserves values**
    - **Validates: Requirements 1.4**
    - Use fast-check to generate random translation keys with placeholders
    - Generate random interpolation values (strings, numbers)
    - Call translation function with values
    - Verify output string contains all provided values
    - Run 100 iterations minimum
  
  - [ ]* 14.3 Write property test for language preference persistence
    - **Property 3: Language preference persists across sessions**
    - **Validates: Requirements 2.1, 2.2**
    - Use fast-check to generate random locale selection (en or ko)
    - Clear localStorage to simulate fresh session
    - Call setStoredLanguage(locale)
    - Call getStoredLanguage()
    - Verify retrieved value equals stored value
    - Run 100 iterations minimum
  
  - [ ]* 14.4 Write property test for language switcher reflects locale
    - **Property 4: Language switcher reflects current locale**
    - **Validates: Requirements 3.1, 3.2, 3.3**
    - Use fast-check to generate random current locale state
    - Render LanguageSwitcher with currentLocale prop
    - Verify switcher displays corresponding language name
    - Simulate switching to other locale
    - Verify router navigation called with correct locale path
    - Run 100 iterations minimum

- [ ] 15. Write integration tests for migrated pages
  - [ ]* 15.1 Write integration test for Mission Control page
    - Mock API responses (getDashboard, postMission, getMission, etc.)
    - Render Mission Control page with mocked next-intl provider
    - Test "Run mission" workflow: input goal, click button, verify API calls
    - Test language switching updates all displayed text
    - Test error handling displays translated error messages
    - Verify metrics display correctly
    - Use Vitest + React Testing Library
    - _Requirements: 4.1-4.7, 29.1, 29.6_
  
  - [ ]* 15.2 Write integration test for Lab page
    - Mock API responses (postReview, postRun, postPR, etc.)
    - Render Lab page with mocked next-intl provider
    - Test "Review" workflow: input goal, click Review, verify API call and verdict display
    - Test "Create PR" workflow: click button, verify API call and PR URL display
    - Test language switching updates all displayed text
    - Test gate result display with color coding
    - Use Vitest + React Testing Library
    - _Requirements: 5.1-5.8, 29.2, 29.6_
  
  - [ ]* 15.3 Write integration test for Evidence page
    - Mock API response for getEvidence
    - Render Evidence page with mocked next-intl provider
    - Test evidence fetch: input ID, click Fetch, verify API call and evidence display
    - Test timeline visualization renders correctly
    - Test language switching updates all displayed text
    - Test missing evidence indicators display correctly
    - Use Vitest + React Testing Library
    - _Requirements: 6.1-6.7, 29.3, 29.6_
  
  - [ ]* 15.4 Write integration test for Login page
    - Mock login API response
    - Render Login page with mocked next-intl provider
    - Test login workflow: input credentials, click Sign in, verify API call
    - Test error handling for invalid credentials
    - Test language switching updates form labels
    - Use Vitest + React Testing Library
    - _Requirements: 7.1-7.5, 29.4, 29.6_

- [ ] 16. Write property test for migration functional equivalence
  - [ ]* 16.1 Write property test for migrated pages preserve behavior
    - **Property 11: Migrated pages preserve behavior**
    - **Validates: Requirements 29.6**
    - For each page (Mission Control, Lab, Evidence, Login), define valid user workflows
    - Use fast-check to generate random workflow execution sequences
    - Execute workflow on migrated page with mocked APIs
    - Capture API call sequences, state updates, and rendered outputs
    - Verify equivalent behavior to expected baseline (manually defined)
    - Run 100 iterations minimum per page

- [ ] 17. Final checkpoint - Run all tests and verify complete functionality
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 18. Documentation and polish
  - [ ] 18.1 Add JSDoc comments to all UI components
    - Add JSDoc comments to Button, Input, Card, Loading, Error, Badge components
    - Document props interface with descriptions and types
    - Include usage examples in JSDoc
    - Document accessibility considerations (ARIA attributes, keyboard support)
    - _Requirements: 28.1-28.4_
  
  - [ ] 18.2 Add JSDoc comments to utility functions
    - Document i18n configuration functions
    - Document language storage functions
    - Document API error translation function
    - Include usage examples
    - _Requirements: 28.1, 28.3_
  
  - [ ] 18.3 Update README with i18n usage instructions
    - Document how to add new translations
    - Document how to add new languages
    - Document translation file structure and namespaces
    - Document how to use useTranslations hook in new components
    - Document how language switching works
    - _Requirements: 28.1-28.5_
  
  - [ ] 18.4 Create component usage examples
    - Create example usage for each UI component (inline code examples or separate example files)
    - Show different variants, sizes, and states
    - Show accessibility best practices
    - Consider creating Storybook stories if Storybook is available
    - _Requirements: 28.3, 28.5_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP delivery
- Property-based tests validate universal correctness properties from the design document
- Unit tests validate specific component behaviors and edge cases
- Integration tests validate full page workflows and user interactions
- Each task includes requirement references for traceability
- Checkpoints ensure incremental validation before moving to complex integrations
- Component library is built first to enable reuse in all pages
- I18n infrastructure is set up before page migrations to enable translation integration
- Pages are migrated in order of complexity: Layout → Mission Control → Evidence → Lab → Login
- Testing tasks are distributed throughout implementation to catch issues early
- Documentation tasks are at the end to capture final implementation state

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "1.5", "2.1", "2.2"] },
    { "id": 2, "tasks": ["2.3", "3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.4"] },
    { "id": 4, "tasks": ["3.5", "3.6", "3.7", "3.8", "3.9"] },
    { "id": 5, "tasks": ["3.10", "5.1", "5.2"] },
    { "id": 6, "tasks": ["5.3", "6.1"] },
    { "id": 7, "tasks": ["6.2", "6.3"] },
    { "id": 8, "tasks": ["7.1", "8.1"] },
    { "id": 9, "tasks": ["7.2", "8.2"] },
    { "id": 10, "tasks": ["7.3", "8.3"] },
    { "id": 11, "tasks": ["10.1"] },
    { "id": 12, "tasks": ["10.2"] },
    { "id": 13, "tasks": ["10.3", "11.1"] },
    { "id": 14, "tasks": ["11.2", "12.1"] },
    { "id": 15, "tasks": ["12.2", "12.3", "12.4", "12.5"] },
    { "id": 16, "tasks": ["13.1", "13.2", "13.3", "13.4"] },
    { "id": 17, "tasks": ["14.1", "14.2", "14.3", "14.4"] },
    { "id": 18, "tasks": ["15.1", "15.2", "15.3", "15.4"] },
    { "id": 19, "tasks": ["16.1"] },
    { "id": 20, "tasks": ["18.1", "18.2", "18.3", "18.4"] }
  ]
}
```
