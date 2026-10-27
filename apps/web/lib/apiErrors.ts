/**
 * Maps error objects to translation keys for displaying localized error messages.
 * 
 * @param error - The error object to analyze
 * @returns Translation key for the error message
 * 
 * @example
 * ```ts
 * try {
 *   await apiCall();
 * } catch (error) {
 *   const messageKey = getErrorMessageKey(error);
 *   const message = t(messageKey);
 * }
 * ```
 */
export function getErrorMessageKey(error: Error | unknown): string {
  if (error instanceof Error) {
    const message = error.message;
    
    // Check for specific HTTP status codes
    if (message.includes('401')) return 'errors.unauthorized';
    if (message.includes('402')) return 'errors.budget-exhausted';
    if (message.includes('403')) return 'errors.forbidden';
    if (message.includes('404')) return 'errors.not-found';
    if (message.includes('429')) return 'errors.rate-limit';
    
    // Check for 5xx server errors
    if (/\b5\d{2}\b/.test(message)) return 'errors.server-error';
    
    // Check for network errors
    if (
      message.toLowerCase().includes('fetch') ||
      message.toLowerCase().includes('network') ||
      message.toLowerCase().includes('connection')
    ) {
      return 'errors.network-error';
    }
  }
  
  // Default to unknown error
  return 'errors.unknown';
}

/**
 * Extracts HTTP status code from error message if present.
 * 
 * @param error - The error object to analyze
 * @returns HTTP status code or null if not found
 */
export function getStatusCode(error: Error | unknown): number | null {
  if (error instanceof Error) {
    const match = error.message.match(/\b(\d{3})\b/);
    if (match) {
      const code = parseInt(match[1], 10);
      if (code >= 100 && code < 600) {
        return code;
      }
    }
  }
  return null;
}
