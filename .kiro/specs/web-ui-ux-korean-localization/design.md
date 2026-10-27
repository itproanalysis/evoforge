# Design Document

## Overview

This design implements internationalization (i18n) support and comprehensive UI/UX enhancements for the EvoForge Next.js web application. The solution integrates `next-intl` for server-side and client-side translations, establishes a Tailwind CSS-based design system with centralized design tokens, creates a reusable component library following React and accessibility best practices, and migrates all existing pages to use the new component architecture while maintaining functional equivalence.

The design prioritizes developer experience through type-safe translations, component reusability, and clear migration paths. It also prioritizes user experience through responsive layouts, accessible components, and seamless language switching with persistence.

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Next.js App Router                        │
├─────────────────────────────────────────────────────────────┤
│  Root Layout (apps/web/app/layout.tsx)                      │
│  ├─ I18nProvider (next-intl context)                        │
│  ├─ LanguageSwitcher component                              │
│  └─ Page content with translation hooks                     │
├─────────────────────────────────────────────────────────────┤
│  Pages (Mission Control, Lab, Evidence, Login)              │
│  ├─ Use UI components (Button, Input, Card, etc.)          │
│  ├─ Use useTranslations() hook                              │
│  └─ Use API client with error translation                   │
├─────────────────────────────────────────────────────────────┤
│  Component Library (apps/web/components/)                   │
│  ├─ Button (variants: primary, secondary, danger, ghost)   │
│  ├─ Input (types: text, password, states: error, disabled) │
│  ├─ Card (sections: header, body, footer)                   │
│  ├─ Loading (spinner + translated text)                     │
│  ├─ Error (dismissible, translated messages)                │
│  ├─ Badge (state-based color coding)                        │
│  └─ LanguageSwitcher (dropdown, keyboard accessible)        │
├─────────────────────────────────────────────────────────────┤
│  Translation Layer                                          │
│  ├─ messages/en.json (English translations)                 │
│  ├─ messages/ko.json (Korean translations)                  │
│  ├─ next-intl configuration (i18n.ts)                       │
│  └─ Language preference storage (localStorage)              │
├─────────────────────────────────────────────────────────────┤
│  Styling System                                             │
│  ├─ Tailwind CSS (utility classes)                          │
│  ├─ tailwind.config.ts (design tokens)                      │
│  └─ globals.css (base styles, CSS variables)                │
├─────────────────────────────────────────────────────────────┤
│  API Client (lib/api.ts)                                    │
│  ├─ Error translation mapping                               │
│  └─ Status code to translation key mapping                  │
└─────────────────────────────────────────────────────────────┘
```

### Technology Choices

**I18n Library: next-intl**
- **Rationale**: Optimized for Next.js App Router with server and client component support, type-safe message keys via TypeScript, built-in support for ICU MessageFormat (interpolation, pluralization, date/number formatting)
- **Alternatives considered**: react-i18next (more complex setup for Next.js 15 App Router), custom solution (would require implementing interpolation, pluralization, and SSR support)

**Styling System: Tailwind CSS**
- **Rationale**: Utility-first approach reduces CSS bundle size, excellent TypeScript support, responsive design utilities, dark mode support, easy integration with Next.js
- **Alternatives considered**: CSS Modules (requires more boilerplate for responsive variants), Styled Components (adds runtime overhead)

**Language Persistence: localStorage**
- **Rationale**: Simple client-side storage, no server dependency, survives page reloads, compatible with all modern browsers
- **Alternatives considered**: Cookies (would require middleware updates, unnecessary for client-only preference)

### Directory Structure

```
apps/web/
├── app/
│   ├── [locale]/              # Dynamic locale segment
│   │   ├── page.tsx           # Mission Control (migrated)
│   │   ├── lab/
│   │   │   └── page.tsx       # Improvement Lab (migrated)
│   │   ├── evidence/
│   │   │   └── page.tsx       # Evidence Timeline (migrated)
│   │   ├── login/
│   │   │   └── page.tsx       # Login page (migrated)
│   │   └── layout.tsx         # Root layout with I18nProvider
│   └── api/                   # API routes (unchanged)
├── components/
│   ├── ui/
│   │   ├── Button.tsx
│   │   ├── Input.tsx
│   │   ├── Card.tsx
│   │   ├── Loading.tsx
│   │   ├── Error.tsx
│   │   ├── Badge.tsx
│   │   └── index.ts           # Barrel export
│   ├── LanguageSwitcher.tsx
│   └── index.ts
├── lib/
│   ├── api.ts                 # Updated with error translation
│   └── i18n.ts                # next-intl configuration
├── messages/
│   ├── en.json                # English translations
│   └── ko.json                # Korean translations
├── styles/
│   └── globals.css
├── middleware.ts              # next-intl middleware for locale routing
├── tailwind.config.ts         # Design tokens
└── i18n.ts                    # I18n configuration export
```

## Components and Interfaces

### I18n System

#### next-intl Configuration

**File: `lib/i18n.ts`**

```typescript
import { getRequestConfig } from 'next-intl/server';
import { notFound } from 'next/navigation';

export const locales = ['en', 'ko'] as const;
export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = 'en';

export default getRequestConfig(async ({ locale }) => {
  // Validate locale
  if (!locales.includes(locale as Locale)) {
    notFound();
  }

  return {
    messages: (await import(`../messages/${locale}.json`)).default,
    timeZone: 'UTC',
    now: new Date(),
  };
});
```

**File: `middleware.ts`**

```typescript
import createMiddleware from 'next-intl/middleware';
import { locales, defaultLocale } from './lib/i18n';

export default createMiddleware({
  locales,
  defaultLocale,
  localePrefix: 'as-needed', // Don't prefix default locale
});

export const config = {
  matcher: ['/', '/(ko|en)/:path*'],
};
```

#### Language Preference Storage

**File: `lib/languageStorage.ts`**

```typescript
import type { Locale } from './i18n';

const STORAGE_KEY = 'evoforge.language';

export function getStoredLanguage(): Locale | null {
  if (typeof window === 'undefined') return null;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === 'ko' || stored === 'en' ? stored : null;
  } catch {
    return null;
  }
}

export function setStoredLanguage(locale: Locale): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // Ignore storage errors
  }
}
```

#### Translation Hook Usage Pattern

```typescript
'use client';

import { useTranslations } from 'next-intl';

export default function MissionControl() {
  const t = useTranslations('mission-control');
  
  return (
    <main>
      <h1>{t('heading')}</h1>
      <p>{t('description')}</p>
      <Button>{t('run-mission')}</Button>
    </main>
  );
}
```

### Component Library

#### Button Component

**File: `components/ui/Button.tsx`**

**Props Interface:**
```typescript
interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  children: React.ReactNode;
}
```

**Variants:**
- `primary`: Blue background (#2563eb), white text, used for primary actions
- `secondary`: Cyan/teal background (#0891b2), white text, used for secondary actions
- `danger`: Red background (#dc2626), white text, used for destructive actions
- `ghost`: Transparent background, border-only, used for tertiary actions

**States:**
- Default: Full opacity, pointer cursor
- Hover: Slightly darker background
- Disabled: Reduced opacity (50%), not-allowed cursor, no hover effect
- Loading: Shows spinner, disabled interaction, maintains button width

**Accessibility:**
- Semantic `<button>` element
- `disabled` attribute when disabled or loading
- `aria-busy="true"` when loading
- Focus visible ring with brand color

#### Input Component

**File: `components/ui/Input.tsx`**

**Props Interface:**
```typescript
interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  error?: boolean;
  errorMessage?: string;
  label?: string;
}
```

**States:**
- Default: Dark background (#0b0e14), light border (#33405c)
- Focus: Blue ring (#2563eb), brighter border
- Error: Red border (#ef4444), red ring on focus, error message below
- Disabled: Reduced opacity, not-allowed cursor

**Accessibility:**
- Associated `<label>` when label prop provided
- `aria-invalid="true"` when error is true
- `aria-describedby` linking to error message
- Focus visible ring

#### Card Component

**File: `components/ui/Card.tsx`**

**Props Interface:**
```typescript
interface CardProps {
  children: React.ReactNode;
  header?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
}
```

**Structure:**
- Container: Dark background (#141b2d), border (#263048), rounded corners (10px), padding (14px)
- Header: Optional, rendered above main content
- Body: Main content area
- Footer: Optional, rendered below main content

#### Loading Component

**File: `components/ui/Loading.tsx`**

**Props Interface:**
```typescript
interface LoadingProps {
  message?: string; // Optional translated loading text
  size?: 'sm' | 'md' | 'lg';
}
```

**Implementation:**
- Spinner: Animated circular spinner using CSS animation
- Message: Displayed below spinner, uses translated text if provided
- Sizes: Small (16px), Medium (32px), Large (48px)

**Accessibility:**
- `role="status"` for screen reader announcement
- `aria-live="polite"` for dynamic updates
- `aria-label` with loading message

#### Error Component

**File: `components/ui/Error.tsx`**

**Props Interface:**
```typescript
interface ErrorProps {
  message: string; // Translated error message
  details?: string; // Optional technical details
  dismissible?: boolean;
  onDismiss?: () => void;
}
```

**Implementation:**
- Red background tint (#7f1d1d with low opacity)
- Red text (#ef4444)
- Error icon (optional)
- Dismiss button when dismissible=true
- Technical details in expandable section

**Accessibility:**
- `role="alert"` for immediate screen reader announcement
- `aria-live="assertive"` for critical errors
- Dismiss button with `aria-label="Dismiss error"`

#### Badge Component

**File: `components/ui/Badge.tsx`**

**Props Interface:**
```typescript
interface BadgeProps {
  state: MissionState; // "PR_OPENED" | "FAILED" | "CANCELLED" | "REVIEWED" | "RAN" | "GENERATED" | "CREATED"
  children: React.ReactNode; // Translated state text
}
```

**Color Coding:**
- `PR_OPENED`: Green (#22c55e) - success state
- `FAILED`, `CANCELLED`: Red (#ef4444) - error states
- `RAN`, `REVIEWED`: Blue (#38bdf8) - in-progress states
- `GENERATED`, `CREATED`: Amber (#f59e0b) - pending states

**Implementation:**
- Inline display, small padding (2px 10px)
- Rounded pill shape (border-radius: 20px)
- Bold text, dark background text color (#0b0e14)
- Uppercase or title case state names

**Accessibility:**
- `aria-label` with full translated state description
- Color is not the only indicator (text + color)

#### LanguageSwitcher Component

**File: `components/LanguageSwitcher.tsx`**

**Props Interface:**
```typescript
interface LanguageSwitcherProps {
  currentLocale: Locale;
}
```

**Implementation:**
- Dropdown or button group showing language options
- Current language highlighted
- Click to switch language
- Updates URL to `/ko/*` or `/en/*` or `/*` (default)
- Persists selection to localStorage

**Interaction Flow:**
1. User clicks language switcher
2. Dropdown shows "English" and "한국어"
3. User selects language
4. `setStoredLanguage(newLocale)` called
5. Router navigates to `/${newLocale}/current-page`
6. Page re-renders with new translations

**Accessibility:**
- `<select>` or custom dropdown with keyboard navigation
- Arrow keys to navigate options
- Enter/Space to select
- `aria-label="Select language"`

## Data Models

### Translation File Structure

**English (`messages/en.json`):**

```json
{
  "common": {
    "app-name": "EvoForge",
    "api-label": "API",
    "loading": "Loading...",
    "error": "Error",
    "cancel": "Cancel",
    "save": "Save",
    "close": "Close"
  },
  "languages": {
    "english": "English",
    "korean": "한국어"
  },
  "navigation": {
    "mission-control": "Mission Control",
    "improvement-lab": "Improvement Lab",
    "evidence": "Evidence"
  },
  "mission-control": {
    "heading": "Mission Control",
    "description": "POST /api/evoforge/v1/missions · single-command lifecycle",
    "objective-label": "Objective",
    "objective-placeholder": "Fix flaky login retry",
    "repo-ref-label": "repo_ref",
    "run-mission": "Run mission",
    "stop-mission": "Stop",
    "running-mission": "Running mission…",
    "mission-id": "mission_id",
    "evidence-label": "evidence",
    "error-prefix": "Error: ",
    "metrics": {
      "active-missions": "Active missions",
      "blocked-merges": "Blocked merges",
      "validated": "Validated (WVI)",
      "spent": "Spent",
      "reserved": "Reserved",
      "unknown-holds": "Unknown holds"
    },
    "states": {
      "CREATED": "Created",
      "GENERATED": "Generated",
      "REVIEWED": "Reviewed",
      "RAN": "Ran",
      "PR_OPENED": "PR Opened",
      "CANCELLED": "Cancelled",
      "FAILED": "Failed"
    },
    "ledger": {
      "heading": "Ledger snapshot (GET /v1/ledger)",
      "spent-cents": "spent_cents",
      "reserved-cents": "reserved_cents",
      "unknown-reservations": "unknown_reservations"
    }
  },
  "lab": {
    "heading": "Improvement Lab",
    "description": "candidate diff → sealed tests → review → PR. INCONCLUSIVE blocks merge.",
    "goal-label": "goal",
    "goal-placeholder": "Goal from Mission Control",
    "candidate-diff": "Candidate diff",
    "tests-heading": "Tests ({count})",
    "server-run-heading": "Server run (POST /v1/runs)",
    "server-run-description": "Apply diff in hygiene sandbox and run candidate tests (visible) and Critic sealed tests (held-out) on server. Repo must be in server's EVO_REPO_ROOTS. Run Review first to get sealed tests.",
    "repo-path-label": "repo path",
    "repo-path-placeholder": "C:/repos/project",
    "base-sha-label": "base sha",
    "run-on-server": "Run on server (held-out {count})",
    "running": "Running…",
    "review-button": "Review (POST /v1/candidates/review)",
    "reviewing": "Reviewing…",
    "create-pr": "Create PR (POST /v1/pr/create)",
    "creating-pr": "Creating…",
    "merge": "Merge",
    "merge-blocked": "Merge (blocked)",
    "merge-blocked-description": "INCONCLUSIVE/FAIL gates prevent merge. Exception approval required.",
    "sealed-tests-heading": "Sealed tests ({count})",
    "sealed-suites-heading": "Sealed v0 + X_SINGLE (read-only)",
    "sealed-suites-description": "Server-measured baseline catalogue. Catalogue loads over GET only; sealed task code never leaves the server.",
    "run-info": "visible {visPass}/{visN}{visTimeout} · held-out {heldPass}/{heldN}{heldTimeout} · base {base}",
    "review-verdict": "review verdict: {verdict}",
    "pr-created": "PR: {url}",
    "error-prefix": "Error: "
  },
  "evidence": {
    "heading": "Evidence Timeline",
    "description": "GET /v1/evidence/{id} · ObjectiveVersion→Task→Candidate→Gate→Review→PR→Outcome",
    "input-placeholder": "evidence / command id",
    "fetch-button": "Fetch evidence",
    "loading": "Loading…",
    "error-prefix": "Error: ",
    "evidence-missing": "Evidence missing",
    "event-label": "Event {id}",
    "loading-event": "Loading event…",
    "stages": {
      "ObjectiveVersion": "Objective Version",
      "Task": "Task",
      "Candidate": "Candidate",
      "Gate": "Gate",
      "Review": "Review",
      "PR": "PR",
      "Outcome": "Outcome"
    }
  },
  "login": {
    "heading": "Owner login",
    "username-label": "Username",
    "password-label": "Password",
    "sign-in": "Sign in",
    "signing-in": "Signing in...",
    "error-invalid-credentials": "Invalid credentials",
    "error-too-many-attempts": "Too many login attempts. Please try again later.",
    "error-login-failed": "Login failed. Please try again."
  },
  "layout": {
    "title": "EvoForge — Mission Control",
    "description": "Hackathon Indie-track UI: generate → gate → review → PR → evidence.",
    "footer": "Builder: Muse Spark 1.3 via Meta Model API · Gates: GH_INTEGRITY (oracle_ast + provisional D-054) · costs are provider_billed actuals in cents from GET /v1/ledger; UNKNOWN holds listed separately"
  },
  "errors": {
    "budget-exhausted": "Budget exhausted: mission step refused with 402",
    "rate-limit": "Rate limit exceeded. Please wait before trying again.",
    "network-error": "Network connection error. Please check your connection and try again.",
    "unauthorized": "Unauthorized. Please log in.",
    "forbidden": "Access forbidden.",
    "not-found": "Resource not found.",
    "server-error": "Server error. Please try again later.",
    "unknown": "An unknown error occurred.",
    "status-code": "HTTP {code}: {message}"
  }
}
```

**Korean (`messages/ko.json`):**

```json
{
  "common": {
    "app-name": "EvoForge",
    "api-label": "API",
    "loading": "로딩 중...",
    "error": "오류",
    "cancel": "취소",
    "save": "저장",
    "close": "닫기"
  },
  "languages": {
    "english": "English",
    "korean": "한국어"
  },
  "navigation": {
    "mission-control": "미션 컨트롤",
    "improvement-lab": "개선 랩",
    "evidence": "증거"
  },
  "mission-control": {
    "heading": "미션 컨트롤",
    "description": "POST /api/evoforge/v1/missions · 단일 명령 수명 주기",
    "objective-label": "목표",
    "objective-placeholder": "불안정한 로그인 재시도 수정",
    "repo-ref-label": "repo_ref",
    "run-mission": "미션 실행",
    "stop-mission": "중지",
    "running-mission": "미션 실행 중…",
    "mission-id": "mission_id",
    "evidence-label": "증거",
    "error-prefix": "오류: ",
    "metrics": {
      "active-missions": "활성 미션",
      "blocked-merges": "차단된 병합",
      "validated": "검증됨 (WVI)",
      "spent": "지출",
      "reserved": "예약",
      "unknown-holds": "알 수 없는 보류"
    },
    "states": {
      "CREATED": "생성됨",
      "GENERATED": "생성됨",
      "REVIEWED": "검토됨",
      "RAN": "실행됨",
      "PR_OPENED": "PR 열림",
      "CANCELLED": "취소됨",
      "FAILED": "실패"
    },
    "ledger": {
      "heading": "원장 스냅샷 (GET /v1/ledger)",
      "spent-cents": "spent_cents",
      "reserved-cents": "reserved_cents",
      "unknown-reservations": "unknown_reservations"
    }
  },
  "lab": {
    "heading": "개선 랩",
    "description": "후보 diff → 봉인 테스트 → 검토 → PR. INCONCLUSIVE는 병합 차단.",
    "goal-label": "목표",
    "goal-placeholder": "미션 컨트롤에서 입력한 목표",
    "candidate-diff": "후보 diff",
    "tests-heading": "테스트 ({count})",
    "server-run-heading": "서버 실행 (POST /v1/runs)",
    "server-run-description": "위생 샌드박스에서 diff를 적용하고 후보 테스트(visible)와 Critic 봉인 테스트(held-out)를 서버가 실행합니다. 저장소는 서버의 EVO_REPO_ROOTS 안에 있어야 합니다. Review를 먼저 실행해 봉인 테스트를 받으세요.",
    "repo-path-label": "repo path",
    "repo-path-placeholder": "C:/repos/project",
    "base-sha-label": "base sha",
    "run-on-server": "서버에서 실행 (held-out {count})",
    "running": "실행 중…",
    "review-button": "검토 (POST /v1/candidates/review)",
    "reviewing": "검토 중…",
    "create-pr": "PR 생성 (POST /v1/pr/create)",
    "creating-pr": "생성 중…",
    "merge": "병합",
    "merge-blocked": "병합 (차단됨)",
    "merge-blocked-description": "INCONCLUSIVE/FAIL 게이트가 있어 Merge가 비활성화됩니다. 예외 승인이 필요합니다.",
    "sealed-tests-heading": "봉인 테스트 ({count})",
    "sealed-suites-heading": "Sealed v0 + X_SINGLE (읽기 전용)",
    "sealed-suites-description": "서버 측정 기준 카탈로그. 카탈로그는 GET으로만 로드; 봉인된 작업 코드는 서버를 벗어나지 않습니다.",
    "run-info": "visible {visPass}/{visN}{visTimeout} · held-out {heldPass}/{heldN}{heldTimeout} · base {base}",
    "review-verdict": "검토 결과: {verdict}",
    "pr-created": "PR: {url}",
    "error-prefix": "오류: "
  },
  "evidence": {
    "heading": "증거 타임라인",
    "description": "GET /v1/evidence/{id} · ObjectiveVersion→Task→Candidate→Gate→Review→PR→Outcome",
    "input-placeholder": "증거 / 명령 id",
    "fetch-button": "증거 가져오기",
    "loading": "로딩 중…",
    "error-prefix": "오류: ",
    "evidence-missing": "증거 부족",
    "event-label": "이벤트 {id}",
    "loading-event": "이벤트 로딩 중…",
    "stages": {
      "ObjectiveVersion": "목표 버전",
      "Task": "작업",
      "Candidate": "후보",
      "Gate": "게이트",
      "Review": "검토",
      "PR": "PR",
      "Outcome": "결과"
    }
  },
  "login": {
    "heading": "소유자 로그인",
    "username-label": "사용자명",
    "password-label": "비밀번호",
    "sign-in": "로그인",
    "signing-in": "로그인 중...",
    "error-invalid-credentials": "잘못된 자격 증명",
    "error-too-many-attempts": "로그인 시도 횟수가 너무 많습니다. 나중에 다시 시도하세요.",
    "error-login-failed": "로그인 실패. 다시 시도하세요."
  },
  "layout": {
    "title": "EvoForge — 미션 컨트롤",
    "description": "해커톤 인디 트랙 UI: generate → gate → review → PR → evidence.",
    "footer": "빌더: Muse Spark 1.3 (Meta Model API 사용) · 게이트: GH_INTEGRITY (oracle_ast + 임시 D-054) · 비용은 GET /v1/ledger에서 센트 단위의 provider_billed 실제 값; UNKNOWN 보류는 별도로 나열"
  },
  "errors": {
    "budget-exhausted": "예산 소진: 미션 단계가 402로 거부됨",
    "rate-limit": "속도 제한 초과. 잠시 후 다시 시도하세요.",
    "network-error": "네트워크 연결 오류. 연결을 확인하고 다시 시도하세요.",
    "unauthorized": "인증되지 않음. 로그인하세요.",
    "forbidden": "액세스 금지.",
    "not-found": "리소스를 찾을 수 없습니다.",
    "server-error": "서버 오류. 나중에 다시 시도하세요.",
    "unknown": "알 수 없는 오류가 발생했습니다.",
    "status-code": "HTTP {code}: {message}"
  }
}
```

### API Error Translation Mapping

**File: `lib/apiErrors.ts`**

```typescript
export function getErrorMessageKey(error: Error | unknown): string {
  if (error instanceof Error) {
    const message = error.message;
    
    // Check for status codes
    if (message.includes('401')) return 'errors.unauthorized';
    if (message.includes('402')) return 'errors.budget-exhausted';
    if (message.includes('403')) return 'errors.forbidden';
    if (message.includes('404')) return 'errors.not-found';
    if (message.includes('429')) return 'errors.rate-limit';
    if (message.includes('5')) return 'errors.server-error'; // 5xx errors
    
    // Network errors
    if (message.includes('fetch') || message.includes('network')) {
      return 'errors.network-error';
    }
  }
  
  return 'errors.unknown';
}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Acceptance Criteria Testing Prework

#### 1.1 THE I18n_System SHALL support Korean and English languages
  **Thoughts**: This is about infrastructure setup—testing that the i18n library is configured with two locales. We can verify by generating random page routes and checking that both `/ko/*` and `/en/*` variants load successfully with the correct locale context.
  **Classification**: PROPERTY
  **Test Strategy**: Generate random valid routes, verify both locale variants render with correct locale in context

#### 1.2 THE I18n_System SHALL provide translation functions accessible in all React components
  **Thoughts**: This tests that the translation hook is available throughout the component tree. We can test by rendering random components at various nesting levels and verifying the hook returns a valid translator function.
  **Classification**: PROPERTY
  **Test Strategy**: Generate random component hierarchies, verify useTranslations() works at all depths

#### 1.3 THE I18n_System SHALL load translation resources for the selected Language_Preference
  **Thoughts**: This is a round-trip property—for any locale selection, loading then retrieving translations should return messages for that locale. We can test with random locale switches and random translation keys.
  **Classification**: PROPERTY
  **Test Strategy**: Generate random locale switches and translation key accesses, verify correct message returned

#### 1.4 THE I18n_System SHALL support interpolation for dynamic values in translated strings
  **Thoughts**: For any translation with interpolation placeholders and any set of values, the output should contain those values. We can generate random interpolation patterns and values to test.
  **Classification**: PROPERTY
  **Test Strategy**: Generate random interpolation values, verify output contains those values

#### 2.1 WHEN a user selects a language, THE Storage_Service SHALL persist the Language_Preference
  **Thoughts**: This is a write-then-read property. For any locale selection, setting then getting should return the same locale.
  **Classification**: PROPERTY
  **Test Strategy**: Generate random locale selections, verify setStoredLanguage then getStoredLanguage returns same value

#### 2.2 WHEN the Web_Application loads, THE I18n_System SHALL retrieve the Language_Preference from the Storage_Service
  **Thoughts**: This tests initialization behavior. If we set a preference, then simulate app load, the locale should match stored preference.
  **Classification**: PROPERTY
  **Test Strategy**: Generate random stored preferences, verify app loads with correct locale

#### 2.3 WHEN the Language_Preference cannot be retrieved, THE I18n_System SHALL default to English
  **Thoughts**: This is an edge case—when localStorage is empty or returns invalid value, default should be 'en'.
  **Classification**: EDGE_CASE
  **Test Strategy**: Test with empty storage, invalid values, verify 'en' default

#### 3.1 THE language switcher SHALL display the current language selection
  **Thoughts**: For any current locale, the switcher UI should reflect that locale. We can test by setting random locales and verifying the UI state.
  **Classification**: PROPERTY
  **Test Strategy**: Generate random current locales, verify switcher displays correct value

#### 3.2 WHEN a user selects a language, THE I18n_System SHALL update the displayed language
  **Thoughts**: This is a state transition property. For any locale switch action, all displayed text should update to new locale.
  **Classification**: PROPERTY
  **Test Strategy**: Generate random locale switches, verify all translated text updates

#### 12.1 THE Button SHALL support disabled state with appropriate visual feedback
  **Thoughts**: For any button with disabled=true, it should have reduced opacity and not-allowed cursor. This is a property about all buttons.
  **Classification**: PROPERTY
  **Test Strategy**: Generate buttons with random props, verify disabled styling applied when disabled=true

#### 12.2 THE Button SHALL be keyboard accessible
  **Thoughts**: For any button, pressing Enter or Space should trigger onClick. This is universal button behavior.
  **Classification**: PROPERTY
  **Test Strategy**: Generate random buttons, simulate keyboard events, verify onClick called

#### 13.1 THE Input SHALL support error state with visual indicator
  **Thoughts**: For any input with error=true, it should display error styling and aria-invalid. This applies to all inputs.
  **Classification**: PROPERTY
  **Test Strategy**: Generate inputs with random props, verify error styling when error=true

#### 20.1 THE Web_Application SHALL support tab navigation through all interactive elements
  **Thoughts**: For any page, pressing Tab repeatedly should cycle through all interactive elements in order. This is a property of the page's DOM structure.
  **Classification**: PROPERTY
  **Test Strategy**: Generate random pages with random number of interactive elements, verify Tab cycles through all

#### 21.1 THE UI_Component SHALL include appropriate ARIA labels WHERE semantic HTML is insufficient
  **Thoughts**: For any component without semantic meaning, it should have aria-label or aria-labelledby. This is testable by checking components against a semantic HTML whitelist.
  **Classification**: PROPERTY
  **Test Strategy**: Generate random components, verify non-semantic ones have ARIA labels

#### 22.1 THE Theme_System SHALL ensure text-to-background contrast meets WCAG 2.1 AA standards
  **Thoughts**: For any text-background color pair in the theme, contrast ratio should be >= 4.5:1. We can compute contrast ratios for all theme combinations.
  **Classification**: PROPERTY
  **Test Strategy**: Generate all text/background pairs from theme, verify contrast >= 4.5:1

#### 29.1 THE migrated pages SHALL maintain functional equivalence to existing pages
  **Thoughts**: For any page, before and after migration snapshots should produce equivalent DOM structure and behavior. This is a migration invariant.
  **Classification**: PROPERTY
  **Test Strategy**: Generate page states before/after migration, verify equivalent behavior

### Prework Analysis Summary

After reviewing the prework, several properties can be combined or refined:

**Redundancies identified:**
- Properties 1.1, 1.2, and 1.3 all test i18n system availability—can be combined into "I18n system provides translations for all supported locales"
- Properties 3.1 and 3.2 both test language switcher behavior—can be combined into "Language switcher updates UI to match selection"
- Properties 2.1 and 2.2 both test storage persistence—can be combined into "Language preference persists across sessions"

**After consolidation, the unique properties are:**
1. I18n system availability and translation loading (combines 1.1-1.3)
2. Translation interpolation correctness (1.4)
3. Language preference persistence (combines 2.1-2.2)
4. Language switcher updates UI (combines 3.1-3.2)
5. Button accessibility and states (12.1-12.2)
6. Input error state styling (13.1)
7. Keyboard navigation completeness (20.1)
8. ARIA label presence (21.1)
9. Color contrast compliance (22.1)
10. Migration functional equivalence (29.1)

### Property 1: I18n system provides translations for all supported locales

*For any* supported locale (ko, en) and any valid translation key, the i18n system SHALL return a translated string in the requested locale.

**Validates: Requirements 1.1, 1.2, 1.3**

### Property 2: Translation interpolation preserves values

*For any* translation key with interpolation placeholders and any set of interpolation values, the rendered translation SHALL contain all provided values in the output string.

**Validates: Requirements 1.4**

### Property 3: Language preference persists across sessions

*For any* locale selection, storing the preference then retrieving it (either immediately or after simulated app restart) SHALL return the same locale value.

**Validates: Requirements 2.1, 2.2**

### Property 4: Language switcher reflects current locale

*For any* current locale state, the language switcher UI SHALL display the corresponding language name and allow switching to any other supported locale.

**Validates: Requirements 3.1, 3.2, 3.3**

### Property 5: Button disabled state prevents interaction

*For any* Button component with disabled=true or loading=true, clicking the button SHALL NOT trigger the onClick handler.

**Validates: Requirements 12.4, 12.5**

### Property 6: Button keyboard activation

*For any* non-disabled Button component with focus, pressing Enter or Space key SHALL trigger the onClick handler.

**Validates: Requirements 12.6, 20.3**

### Property 7: Input error state displays visual indicator

*For any* Input component with error=true, the component SHALL render with error border color and aria-invalid attribute.

**Validates: Requirements 13.6**

### Property 8: Tab navigation reaches all interactive elements

*For any* page in the application, repeatedly pressing Tab SHALL cycle focus through all interactive elements (buttons, inputs, links, custom controls) without skipping any.

**Validates: Requirements 20.1**

### Property 9: Non-semantic components have ARIA labels

*For any* UI component that does not use semantic HTML elements (button, input, nav, etc.), the component SHALL include aria-label, aria-labelledby, or role attributes.

**Validates: Requirements 21.2**

### Property 10: Theme color pairs meet contrast requirements

*For any* text color and background color pair used in the theme system, the color contrast ratio SHALL be at least 4.5:1.

**Validates: Requirements 22.1**

### Property 11: Migrated pages preserve behavior

*For any* page that existed before migration (Mission Control, Lab, Evidence, Login), the migrated version SHALL produce equivalent API calls, state updates, and user interactions as the original version for all valid user workflows.

**Validates: Requirements 29.6**

## Error Handling

### Error Boundaries

**Client-Side Error Boundary:**
- Wrap page components with React Error Boundary
- Display translated error message on unhandled errors
- Provide "Reload page" button
- Log error details to console for debugging

**API Error Handling:**
- HTTP 401: Redirect to login page, show "Unauthorized" message
- HTTP 402: Show "Budget exhausted" translated message
- HTTP 403: Show "Access forbidden" message
- HTTP 404: Show "Resource not found" message
- HTTP 429: Show "Rate limit exceeded" message with retry guidance
- HTTP 5xx: Show "Server error" message with retry guidance
- Network errors: Show "Connection error" message with connectivity check suggestion

### Translation Error Handling

**Missing Translation Keys:**
- Development: Log warning to console with missing key path
- Production: Fall back to English translation if key missing in current locale
- Ultimate fallback: Display the translation key itself (e.g., "mission-control.heading")

**Invalid Interpolation:**
- Missing interpolation values: Replace with empty string or placeholder
- Log warning in development mode
- Do not crash the application

### Component Error Handling

**Button:**
- If onClick throws error, catch and prevent propagation
- Log error to console
- Show error state on button (optional)

**Input:**
- Validate props on mount, log warnings for invalid combinations
- Handle onChange errors gracefully

**LanguageSwitcher:**
- If localStorage access fails, fall back to URL-only language switching
- If router navigation fails, reload page with new locale in URL

## Testing Strategy

### Unit Testing Approach

**Framework:** Vitest (already used in monorepo based on similar Next.js projects)

**Component Testing:**
- Render each UI component with React Testing Library
- Test each variant, size, and state
- Verify className, styles, and ARIA attributes
- Verify event handlers are called correctly
- Verify children render correctly

**Example Test Structure:**
```typescript
// components/ui/Button.test.tsx
describe('Button', () => {
  it('renders primary variant with correct styles', () => {
    const { getByRole } = render(<Button variant="primary">Click me</Button>);
    const button = getByRole('button');
    expect(button).toHaveClass('bg-blue-600');
  });
  
  it('disables interaction when disabled prop is true', () => {
    const onClick = vi.fn();
    const { getByRole } = render(<Button disabled onClick={onClick}>Click me</Button>);
    const button = getByRole('button');
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});
```

**I18n Testing:**
- Mock next-intl's useTranslations hook
- Verify correct translation keys are called
- Test interpolation with sample values
- Test locale switching logic

**API Error Translation Testing:**
- Mock API responses with various HTTP status codes
- Verify correct error message key returned
- Test error message rendering in Error component

### Property-Based Testing Approach

**Framework:** fast-check (TypeScript property-based testing library)

**Property Test Configuration:**
- Minimum 100 iterations per property test
- Each test tagged with comment referencing design property
- Tag format: `// Feature: web-ui-ux-korean-localization, Property {number}: {property text}`

**Property Test Examples:**

**Property 1: I18n system provides translations**
```typescript
// Feature: web-ui-ux-korean-localization, Property 1: I18n system provides translations for all supported locales
it('provides translations for all supported locales', () => {
  fc.assert(
    fc.property(
      fc.constantFrom('en', 'ko'),
      fc.oneof(
        fc.constant('common.app-name'),
        fc.constant('mission-control.heading'),
        fc.constant('lab.heading'),
        // ... all known translation keys
      ),
      (locale, key) => {
        const messages = locale === 'en' ? enMessages : koMessages;
        const value = getNestedValue(messages, key);
        expect(typeof value).toBe('string');
        expect(value.length).toBeGreaterThan(0);
      }
    ),
    { numRuns: 100 }
  );
});
```

**Property 3: Language preference persists**
```typescript
// Feature: web-ui-ux-korean-localization, Property 3: Language preference persists across sessions
it('persists language preference across sessions', () => {
  fc.assert(
    fc.property(
      fc.constantFrom<Locale>('en', 'ko'),
      (locale) => {
        // Simulate fresh session
        localStorage.clear();
        
        // Store preference
        setStoredLanguage(locale);
        
        // Retrieve preference (simulating new session)
        const retrieved = getStoredLanguage();
        
        expect(retrieved).toBe(locale);
      }
    ),
    { numRuns: 100 }
  );
});
```

**Property 5: Button disabled state prevents interaction**
```typescript
// Feature: web-ui-ux-korean-localization, Property 5: Button disabled state prevents interaction
it('prevents onClick when disabled or loading', () => {
  fc.assert(
    fc.property(
      fc.boolean(), // disabled
      fc.boolean(), // loading
      fc.oneof(fc.constant('primary'), fc.constant('secondary'), fc.constant('danger')),
      (disabled, loading, variant) => {
        const onClick = vi.fn();
        const { getByRole } = render(
          <Button disabled={disabled} loading={loading} variant={variant} onClick={onClick}>
            Test
          </Button>
        );
        
        const button = getByRole('button');
        fireEvent.click(button);
        
        if (disabled || loading) {
          expect(onClick).not.toHaveBeenCalled();
        } else {
          expect(onClick).toHaveBeenCalledTimes(1);
        }
      }
    ),
    { numRuns: 100 }
  );
});
```

**Property 10: Color contrast compliance**
```typescript
// Feature: web-ui-ux-korean-localization, Property 10: Theme color pairs meet contrast requirements
it('ensures all text/background pairs meet WCAG AA contrast', () => {
  const textColors = ['#e8edf5', '#8b96ad', '#cfe3ff', '#93c5fd'];
  const bgColors = ['#0b0e14', '#141b2d', '#111726', '#0f1524'];
  
  fc.assert(
    fc.property(
      fc.constantFrom(...textColors),
      fc.constantFrom(...bgColors),
      (textColor, bgColor) => {
        const contrastRatio = calculateContrastRatio(textColor, bgColor);
        expect(contrastRatio).toBeGreaterThanOrEqual(4.5);
      }
    ),
    { numRuns: 100 }
  );
});
```

### Integration Testing

**Page Integration Tests:**
- Test full page render with mocked API
- Test user workflows (e.g., run mission, create PR)
- Test language switching on each page
- Verify API calls are made with correct parameters

**E2E Testing (Optional):**
- Playwright or Cypress for critical user journeys
- Test language switching persistence across navigation
- Test full mission lifecycle in both languages

### Accessibility Testing

**Automated Tools:**
- jest-axe for automated WCAG compliance checks in unit tests
- Run on each component and page

**Manual Testing:**
- Keyboard navigation testing (Tab, Enter, Space, Escape)
- Screen reader testing (NVDA or VoiceOver)
- Color contrast verification with browser DevTools

**Test Coverage:**
- All interactive components tested for keyboard access
- All pages tested for semantic HTML structure
- All color combinations verified for contrast

### Migration Testing Strategy

**Pre-Migration:**
1. Capture screenshots of all pages in all states
2. Record API call sequences for each user workflow
3. Document expected behavior for edge cases

**During Migration:**
1. Migrate one page at a time
2. Run unit tests for each migrated component
3. Run integration tests for migrated page
4. Visual regression testing against pre-migration screenshots
5. Fix issues before moving to next page

**Post-Migration:**
1. Full regression test suite
2. Performance comparison (bundle size, render time)
3. Accessibility audit
4. Cross-browser testing

**Migration Order:**
1. Component library (Button, Input, Card, etc.)
2. LanguageSwitcher in Layout
3. Mission Control page (most critical)
4. Evidence page (simpler, good second step)
5. Lab page (most complex)
6. Login page (separate flow)

