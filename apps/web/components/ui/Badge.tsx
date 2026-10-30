import React from 'react';

export type MissionState =
  | 'CREATED'
  | 'GENERATED'
  | 'REVIEWED'
  | 'RAN'
  | 'PR_OPENED'
  | 'CANCELLED'
  | 'FAILED';

export interface BadgeProps {
  /**
   * Mission state that determines the badge color
   */
  state: MissionState;
  
  /**
   * Translated state text to display
   */
  children: React.ReactNode;
}

/**
 * Badge component for displaying mission states with color coding.
 * 
 * Color coding:
 * - Green: PR_OPENED (success)
 * - Red: FAILED, CANCELLED (error)
 * - Blue: RAN, REVIEWED (in-progress)
 * - Amber: GENERATED, CREATED (pending)
 * 
 * @example
 * ```tsx
 * <Badge state="PR_OPENED">PR Opened</Badge>
 * <Badge state="FAILED">Failed</Badge>
 * ```
 * 
 * Accessibility:
 * - Includes aria-label with full state description
 * - Color is not the only indicator (text + color)
 */
export function Badge({ state, children }: BadgeProps) {
  const colorClasses: Record<MissionState, string> = {
    PR_OPENED: 'bg-accent-green',
    FAILED: 'bg-accent-red',
    CANCELLED: 'bg-accent-red',
    RAN: 'bg-accent-cyan',
    REVIEWED: 'bg-accent-cyan',
    GENERATED: 'bg-accent-amber',
    CREATED: 'bg-accent-amber',
  };
  
  return (
    <span
      className={`inline-block px-2.5 py-0.5 rounded-badge text-xs font-bold text-white ${colorClasses[state]}`}
      aria-label={`Mission state: ${children}`}
    >
      {children}
    </span>
  );
}
