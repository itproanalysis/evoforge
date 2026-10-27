import React, { useState } from 'react';

export interface ErrorProps {
  /**
   * Main translated error message to display
   */
  message: string;
  
  /**
   * Optional technical details for debugging
   */
  details?: string;
  
  /**
   * Whether the error can be dismissed by the user
   */
  dismissible?: boolean;
  
  /**
   * Callback when the error is dismissed
   */
  onDismiss?: () => void;
}

/**
 * Error component for displaying error messages with optional details.
 * 
 * @example
 * ```tsx
 * <Error message="Failed to load mission data" />
 * 
 * <Error
 *   message="Network error occurred"
 *   details="Failed to fetch: TypeError: Failed to fetch"
 *   dismissible
 *   onDismiss={() => setError(null)}
 * />
 * ```
 * 
 * Accessibility:
 * - Uses role="alert" for immediate screen reader announcement
 * - Uses aria-live="assertive" for critical errors
 * - Dismiss button includes aria-label
 */
export function Error({ message, details, dismissible = false, onDismiss }: ErrorProps) {
  const [showDetails, setShowDetails] = useState(false);
  
  return (
    <div
      className="bg-accent-red-dark bg-opacity-20 border border-accent-red rounded-md p-4"
      role="alert"
      aria-live="assertive"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <p className="text-accent-red font-medium">
            {message}
          </p>
          {details && (
            <div className="mt-2">
              <button
                onClick={() => setShowDetails(!showDetails)}
                className="text-sm text-text-secondary hover:text-text-primary underline focus:outline-none focus:ring-2 focus:ring-accent-red rounded"
              >
                {showDetails ? 'Hide details' : 'Show details'}
              </button>
              {showDetails && (
                <pre className="mt-2 text-xs text-text-secondary bg-background-primary p-2 rounded overflow-x-auto">
                  {details}
                </pre>
              )}
            </div>
          )}
        </div>
        {dismissible && onDismiss && (
          <button
            onClick={onDismiss}
            className="text-accent-red hover:text-red-600 focus:outline-none focus:ring-2 focus:ring-accent-red rounded p-1"
            aria-label="Dismiss error"
          >
            <svg
              className="h-5 w-5"
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fillRule="evenodd"
                d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                clipRule="evenodd"
              />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}
