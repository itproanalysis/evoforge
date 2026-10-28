import React from 'react';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /**
   * Whether the input is in an error state
   */
  error?: boolean;
  
  /**
   * Error message to display below the input
   */
  errorMessage?: string;
  
  /**
   * Label text for the input
   */
  label?: string;
}

/**
 * Input component with support for labels, error states, and accessibility.
 * 
 * @example
 * ```tsx
 * <Input
 *   label="Username"
 *   placeholder="Enter username"
 *   value={username}
 *   onChange={(e) => setUsername(e.target.value)}
 * />
 * 
 * <Input
 *   label="Email"
 *   type="email"
 *   error={emailError}
 *   errorMessage="Please enter a valid email"
 * />
 * ```
 * 
 * Accessibility:
 * - Includes associated <label> when label prop is provided
 * - Sets aria-invalid when error is true
 * - Links error message via aria-describedby
 * - Keyboard accessible with focus-visible ring
 */
export function Input({
  error = false,
  errorMessage,
  label,
  className = '',
  id,
  ...props
}: InputProps) {
  const inputId = id || `input-${Math.random().toString(36).substr(2, 9)}`;
  const errorId = `${inputId}-error`;
  
  const baseClasses = 'w-full px-3 py-2 rounded-md bg-background-primary border transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-background-primary disabled:opacity-50 disabled:cursor-not-allowed';
  
  const stateClasses = error
    ? 'border-accent-red focus:border-accent-red focus:ring-accent-red'
    : 'border-border-secondary focus:border-accent-blue focus:ring-accent-blue';
  
  return (
    // Layout classes (flex-*, w-*, ml-*) size the wrapper; the input fills it. On the input itself a flex-basis
    // would size its height, because the wrapper is a flex column.
    <div className={`flex flex-col gap-1 min-w-0 ${className}`}>
      {label && (
        <label
          htmlFor={inputId}
          className="text-sm font-medium text-text-secondary"
        >
          {label}
        </label>
      )}
      <input
        id={inputId}
        className={`${baseClasses} ${stateClasses} text-text-primary`}
        aria-invalid={error}
        aria-describedby={error && errorMessage ? errorId : undefined}
        {...props}
      />
      {error && errorMessage && (
        <p
          id={errorId}
          className="text-sm text-accent-red"
          role="alert"
        >
          {errorMessage}
        </p>
      )}
    </div>
  );
}
