import React from 'react';

export interface LoadingProps {
  /**
   * Optional translated loading message to display
   */
  message?: string;
  
  /**
   * Size of the loading spinner
   * - sm: 16px
   * - md: 32px (default)
   * - lg: 48px
   */
  size?: 'sm' | 'md' | 'lg';
}

/**
 * Loading component with animated spinner and optional message.
 * 
 * @example
 * ```tsx
 * <Loading />
 * 
 * <Loading size="lg" message="Loading mission data..." />
 * ```
 * 
 * Accessibility:
 * - Includes role="status" for screen reader announcement
 * - Uses aria-live="polite" for dynamic updates
 * - Includes aria-label with loading message
 */
export function Loading({ message, size = 'md' }: LoadingProps) {
  const sizeClasses = {
    sm: 'h-4 w-4',
    md: 'h-8 w-8',
    lg: 'h-12 w-12',
  };
  
  return (
    <div
      className="flex flex-col items-center justify-center gap-3"
      role="status"
      aria-live="polite"
      aria-label={message || 'Loading'}
    >
      <svg
        className={`animate-spin text-accent-blue ${sizeClasses[size]}`}
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle
          className="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="4"
        />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        />
      </svg>
      {message && (
        <p className="text-sm text-text-secondary">
          {message}
        </p>
      )}
    </div>
  );
}
