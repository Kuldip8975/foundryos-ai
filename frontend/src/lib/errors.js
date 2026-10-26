/**
 * Turn an ApiError (see api/client.js) into user-facing text.
 * Never includes stack traces or raw server output; includes the request id
 * so a failure can be traced in the backend logs.
 */
const CODE_TITLES = {
  ai_not_configured: 'AI reports are not configured on the server',
  ai_timeout: 'The AI provider did not respond in time',
  ai_rate_limited: 'The AI provider is rate-limiting requests',
  ai_auth_failed: 'The AI provider rejected the server credentials',
  ai_request_rejected: 'The AI provider rejected the request',
  ai_unavailable: 'The AI provider is unavailable',
  ai_model_not_found: 'The configured AI model was not found',
  ai_provider_error: 'The AI provider had a server error',
  ai_network_error: 'The server could not connect to the AI provider',
  ai_bad_response: 'The AI provider returned an unusable response',
  ai_invalid_output: 'The AI output failed validation',
  report_in_progress: 'A report for this shift is already being generated',
  window_date_mismatch: 'The shift window does not match the production date',
  // Module 4: workflow assistant
  unauthorized: 'Sign-in required',
  forbidden: 'Your role does not allow this',
  self_approval_forbidden: 'Another supervisor must approve this',
  approval_mismatch: 'The approval does not match the proposed action',
  proposal_expired: 'This proposal has expired',
  proposal_not_pending: 'This proposal was already decided',
  idempotency_key_reused: 'This approval request was already used',
  integrity_check_failed: 'The stored action failed its integrity check',
  revalidation_failed: 'The action is no longer valid',
  execution_conflict: 'The action could not be executed',
  execution_unconfirmed: 'The result could not be confirmed',
  agent_step_limit: 'The assistant did not finish within its limits',
  workflow_timeout: 'The assistant ran out of time',
  // Module 5: sign-in and access
  invalid_credentials: 'Sign-in failed',
  too_many_attempts: 'Sign-in is paused',
  session_expired: 'Your session expired',
  session_revoked: 'Your session ended',
  password_change_required: 'Choose your own password first',
  invalid_current_password: 'The current password is not correct',
  weak_password: 'Choose a stronger password',
  machine_not_assigned: 'This machine is not assigned to you',
  machine_required: 'Choose one of your machines',
  username_taken: 'This username is already taken',
  email_taken: 'This email is already used',
  machines_not_applicable: 'Only operators have assigned machines',
  self_change_forbidden: 'You cannot do this to your own account',
  last_admin: 'At least one active admin is required',
};

export function describeApiError(error) {
  const requestId = error?.requestId ?? null;
  if (error?.kind === 'http' && CODE_TITLES[error.code]) {
    return {
      title: CODE_TITLES[error.code],
      message: error.message,
      requestId,
      validation: error.status === 409 || error.status === 422,
    };
  }
  switch (error?.kind) {
    case 'config':
      return { title: 'Frontend configuration error', message: error.message, requestId };
    case 'network':
      return {
        title: 'Cannot reach the FoundryOS API',
        message: 'Check that the backend is running and that VITE_API_BASE_URL and CORS settings match.',
        requestId,
      };
    case 'timeout':
      return { title: 'The API did not respond in time', message: 'Try again in a moment.', requestId };
    case 'parse':
      return { title: 'Unexpected response from the API', message: error.message, requestId };
    case 'http':
      if (error.status === 422) {
        return { title: 'The filters were rejected', message: error.message, requestId, validation: true };
      }
      if (error.status >= 500) {
        return { title: 'The server could not complete the request', message: error.message, requestId };
      }
      return { title: `Request failed (HTTP ${error.status})`, message: error.message, requestId };
    default:
      return { title: 'Something went wrong', message: error?.message ?? 'Unknown error', requestId };
  }
}