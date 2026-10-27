import React from 'react';

export interface CardProps {
  /**
   * Main content of the card
   */
  children: React.ReactNode;
  
  /**
   * Optional header content displayed above the main content
   */
  header?: React.ReactNode;
  
  /**
   * Optional footer content displayed below the main content
   */
  footer?: React.ReactNode;
  
  /**
   * Additional CSS classes to apply to the card container
   */
  className?: string;
}

/**
 * Card component for consistent content containers.
 * 
 * @example
 * ```tsx
 * <Card>
 *   <p>Card content</p>
 * </Card>
 * 
 * <Card
 *   header={<h3>Card Title</h3>}
 *   footer={<Button>Action</Button>}
 * >
 *   <p>Card content with header and footer</p>
 * </Card>
 * ```
 */
export function Card({ children, header, footer, className = '' }: CardProps) {
  return (
    <div
      className={`bg-background-secondary border border-border rounded-card p-3.5 ${className}`}
    >
      {header && (
        <div className="mb-3">
          {header}
        </div>
      )}
      <div>
        {children}
      </div>
      {footer && (
        <div className="mt-3">
          {footer}
        </div>
      )}
    </div>
  );
}
