# Requirements: User Authentication Service

## REQ-001: User Registration
Users must be able to register with an email address and password.
- Email must be unique across the system
- Password must be at least 8 characters, contain one uppercase letter and one number
- System must send a verification email after registration
- Unverified accounts cannot log in

## REQ-002: User Login
Registered and verified users must be able to log in.
- Login accepts email + password
- Failed login attempts must be tracked
- Account locks after 5 consecutive failed attempts for 15 minutes
- Successful login returns a JWT token with 24-hour expiry

## REQ-003: Password Reset
Users must be able to reset a forgotten password.
- Reset is triggered by submitting a registered email
- System sends a reset link valid for 1 hour
- Reset link can only be used once
- After reset, all existing sessions must be invalidated

## REQ-004: Session Management
The system must manage active user sessions.
- Users can view all active sessions
- Users can revoke any individual session
- All sessions are revoked on password change