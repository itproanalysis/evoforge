import React from 'react';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /**
   * Visual variant of the button
   * - primary: Blue background for primary actions
   * - secondary: Cyan background for secondary actions
   * - danger: Red background for destructive actions
   * - ghost: Transparent with border for tertiary actions
   */
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  
  /**
   * Size of the button
   * - sm: Small (compact)
   * - md: Medium (default)
   * - lg: Large
   */
  size?: 'sm' | 'md' | 'lg';
  
  /**
   * Whether the button is in a loading state.
   * When true, displays a spinner and prevents interaction.
   */
  loading?: boolean;
  
  children: React.ReactNode;
}

/**
 * Button component with support for variants, sizes, and loading states.
 * 
 * @example
 * ```tsx
 * <Button variant="primary" onClick={handleClick}>
 *   Submit
 * </Button>
 * 
 * <Button variant="danger" size="sm" loading={isDeleting}>
 *   Delete
 * </Button>
 * ```
 * 
 * Accessibility:
 * - Uses semantic <button> element
 * - Includes aria-busy when loading
 * - Keyboard accessible with focus-visible ring
 */
export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled,
  children,
  className = '',
  ...props
}: ButtonProps) {
  const baseClasses = 'studio-button inline-flex items-center justify-center font-medium rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-blue focus-visible:ring-offset-2 focus-visible:ring-offset-background-primary disabled:opacity-50 disabled:cursor-not-allowed';
  
  const variantClasses = {
    primary: 'bg-accent-blue hover:bg-blue-700 text-white',
    secondary: 'bg-accent-cyan-dark hover:bg-cyan-700 text-white',
    danger: 'bg-accent-red hover:bg-red-700 text-white',
    ghost: 'border border-border-secondary hover:bg-background-secondary text-text-primary',
  };
  
  const sizeClasses = {
    sm: 'px-3 py-1.5 text-sm',
    md: 'px-4 py-2 text-base',
    lg: 'px-6 py-3 text-lg',
  };
  
  const isDisabled = disabled || loading;
  
  return (
    <button
      className={`${baseClasses} ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
      disabled={isDisabled}
      aria-busy={loading}
      {...props}
    >
      {loading && (
        <svg
          className="animate-spin -ml-1 mr-2 h-4 w-4"
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
      )}
      {children}
    </button>
  );
}
