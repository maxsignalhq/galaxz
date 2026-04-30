export const realisticTasks = {
  codeGenerationRequest: [
    'Create a small Python function named rotate_refresh_token.',
    'It should accept the current token id and a revoke callback.',
    'Return a dictionary with old_token_id, new_token_id, and revoked=true.',
    'Keep it framework-free and include basic input validation.',
  ].join('\n'),
  prReviewRequest: [
    'Review this pull request for production risk before merge.',
    'Context: OAuth2 refresh-token rotation was changed to revoke old refresh tokens.',
    'Focus on missing tests, race conditions, and backward compatibility.',
  ].join('\n'),
  debugTriageRequest: [
    'Triage a production incident: users intermittently receive 401 after token refresh.',
    'Recent change: auth middleware cache TTL moved from 5s to 60s.',
    'Return the most likely root cause and next diagnostics.',
  ].join('\n'),
};
