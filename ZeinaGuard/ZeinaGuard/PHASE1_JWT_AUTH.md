# Phase 1: JWT Authentication - Implementation Guide

## Overview

Phase 1 implements secure JWT (JSON Web Token) authentication between Flask backend and Next.js frontend. This is the critical foundation - Flask and Next.js must communicate securely before any other features can work.

## What Was Implemented

### Backend (Flask)

#### Authentication Module (`backend/auth.py`)
- **Password Hashing:** PBKDF2-SHA256 for secure password storage
- **JWT Token Generation:** Creates 24-hour access tokens with user identity
- **Token Validation:** Validates JWT tokens in protected endpoints
- **Mock User Store:** In-memory user database for development (will be replaced with PostgreSQL in Phase 3)

**Demo Users:**
```
Admin:    username: admin, password: admin123
Analyst:  username: analyst, password: analyst123
```

#### API Routes (`backend/routes.py`)
Implements REST API endpoints organized by resource:

**Authentication Routes:**
- `POST /api/auth/login` - User login (returns JWT token)
- `POST /api/auth/logout` - User logout
- `POST /api/auth/refresh` - Refresh expired tokens
- `GET /api/auth/me` - Get current user info

**Threats Routes:**
- `GET /api/threats` - List threats with filtering
- `GET /api/threats/<id>` - Get threat details
- `POST /api/threats/<id>/resolve` - Mark threat as resolved

**Sensors Routes:**
- `GET /api/sensors` - List sensors
- `GET /api/sensors/<id>/health` - Sensor health metrics

**Alerts Routes:**
- `GET /api/alerts` - List alerts
- `POST /api/alerts/<id>/acknowledge` - Acknowledge alert

**Analytics Routes:**
- `GET /api/analytics/threat-stats` - Threat statistics
- `GET /api/analytics/trends` - Historical trends

**Users Routes:**
- `GET /api/users/profile` - User profile

### Frontend (Next.js)

#### API Client (`lib/api.ts`)
- Centralized HTTP client for all API requests
- Automatic JWT token injection in headers
- Token storage and retrieval
- Error handling with 401 (expired token) detection
- Organized API methods by resource (authAPI, threatsAPI, etc.)

#### Authentication Hook (`hooks/use-auth.ts`)
- Zustand state management for authentication
- Global auth state accessible from any component
- Persistent storage of token and user data
- Methods: `login()`, `logout()`, `refreshToken()`, `clearError()`

#### Protected Route Wrapper (`components/auth/protected-route.tsx`)
- Guards routes from unauthenticated access
- Redirects to login if not authenticated
- Shows loading state while verifying auth

#### Login Form (`components/auth/login-form.tsx`)
- Simple, clean login UI
- Error handling and validation
- Demo credentials displayed for easy testing
- Submit button with loading state

#### Pages
- `/app/page.tsx` - Home page (redirects based on auth status)
- `/app/login/page.tsx` - Login page with form
- `/app/dashboard/page.tsx` - Protected dashboard (Phase 1 status)

## Running Phase 1

### Prerequisites
Ensure Docker services are running:
```bash
docker-compose up -d
```

### Start Flask Backend
```bash
# Terminal 1: Flask backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m flask run
```

The Flask server will run on `http://localhost:5000`

### Start Next.js Frontend
```bash
# Terminal 2: Next.js frontend
npm install
npm run dev
```

The Next.js app will run on `http://localhost:3000`

## Testing the Authentication

### 1. Access the Login Page
```
http://localhost:3000/login
```

### 2. Use Demo Credentials
- **Username:** admin
- **Password:** admin123

### 3. Verify Login
- Token stored in browser localStorage
- Redirected to `/dashboard`
- User info displayed in header

### 4. Test API Endpoints
```bash
# Get JWT token from login
# Then test protected endpoints:

curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:5000/api/threats

curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:5000/api/sensors

curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:5000/api/analytics/threat-stats
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│                 Next.js Frontend                     │
│  ┌──────────────────────────────────────────────┐   │
│  │ Pages: /login, /dashboard                    │   │
│  │ Hooks: useAuth (Zustand state)               │   │
│  │ Components: LoginForm, ProtectedRoute        │   │
│  │ Lib: api.ts (HTTP client)                    │   │
│  └──────────────────────────────────────────────┘   │
└──────────────────┬──────────────────────────────────┘
                   │
                   │ HTTP + JWT Token
                   │
┌──────────────────▼──────────────────────────────────┐
│                Flask Backend                        │
│  ┌──────────────────────────────────────────────┐   │
│  │ Routes:                                      │   │
│  │ - /api/auth/login (POST)                     │   │
│  │ - /api/auth/logout (POST)                    │   │
│  │ - /api/auth/refresh (POST)                   │   │
│  │ - /api/auth/me (GET)                         │   │
│  │ - /api/threats/* (GET, POST)                 │   │
│  │ - /api/sensors/* (GET)                       │   │
│  │ - /api/alerts/* (GET, POST)                  │   │
│  │ - /api/analytics/* (GET)                     │   │
│  │ - /api/users/* (GET)                         │   │
│  └──────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────┐   │
│  │ Auth Module:                                 │   │
│  │ - Password hashing                           │   │
│  │ - JWT token generation/validation            │   │
│  │ - User authentication                        │   │
│  └──────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────┐   │
│  │ Storage (Phase 3):                           │   │
│  │ - PostgreSQL + TimescaleDB                   │   │
│  │ - Currently: Mock in-memory user store       │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

## JWT Token Flow

```
1. User submits credentials (username, password)
   ↓
2. Flask: /api/auth/login
   - Verify password
   - Generate JWT token
   - Return token + user info
   ↓
3. Next.js Client:
   - Store token in localStorage
   - Store user info in Zustand store
   ↓
4. Future Requests:
   - Attach token to Authorization header: "Bearer {token}"
   - Backend validates token
   - Returns protected resource
   ↓
5. Token Expiration:
   - Token expires after 24 hours
   - Call /api/auth/refresh to get new token
   - Or redirect to /login
```

## Security Features Implemented

### Password Security
- Passwords hashed with PBKDF2-SHA256 (not plain text)
- Never transmitted or logged
- Demo passwords are for development only

### JWT Token Security
- Signed with JWT_SECRET_KEY
- Expires after 24 hours
- Contains user identity (id, username, email, is_admin)
- Stored in browser localStorage (secure for development)

### API Security
- CORS enabled only for localhost (restrict in production)
- All protected routes require valid JWT
- Token validation on every protected request
- Error handling for expired/invalid tokens

### Frontend Security
- Tokens cleared on logout
- Protected routes redirect unauthenticated users
- Error messages don't leak sensitive info

## Key Files

```
backend/
├── app.py              # Flask application entry point
├── auth.py             # JWT and password handling
├── routes.py           # API endpoint definitions
└── requirements.txt    # Python dependencies

app/
├── page.tsx            # Home page (redirect logic)
├── login/
│   └── page.tsx        # Login page
└── dashboard/
    └── page.tsx        # Protected dashboard

components/auth/
├── login-form.tsx      # Login form component
└── protected-route.tsx # Route protection wrapper

hooks/
└── use-auth.ts         # Zustand auth state management

lib/
└── api.ts              # HTTP client for API calls
```

## Environment Variables

See `.env.docker` for configuration:

```bash
# JWT Configuration
JWT_SECRET_KEY=your_jwt_secret_key_change_me

# API URLs (from Next.js perspective)
NEXT_PUBLIC_API_URL=http://localhost:5000
NEXT_PUBLIC_SOCKET_URL=http://localhost:5000

# Flask Configuration
FLASK_APP=app.py
FLASK_ENV=development
FLASK_DEBUG=1
```

## What's Next (Phase 2)

Phase 2 implements real-time WebSocket threat feeds:

1. **Redis Event Bus:** Flask pushes threat events to Redis
2. **Socket.io WebSocket:** Next.js subscribes to real-time updates
3. **Threat Feed UI:** Real-time threat list with auto-updates
4. **Heartbeat Monitoring:** Sensor status with signal strength
5. **Red Screen Alerts:** Critical threat visual feedback

## Testing Checklist

- [ ] Flask backend starts without errors
- [ ] Next.js frontend starts without errors
- [ ] Can access login page at http://localhost:3000/login
- [ ] Can login with demo credentials (admin / admin123)
- [ ] Token stored in localStorage after successful login
- [ ] Dashboard displays user info
- [ ] Can access other demo user (analyst / analyst123)
- [ ] Logout clears token and redirects to login
- [ ] Protected routes redirect to login when not authenticated
- [ ] API endpoints return mock data with auth token
- [ ] Invalid credentials show error message
- [ ] Token refresh endpoint works

## Troubleshooting

### "Cannot POST /api/auth/login" Error
- Flask backend not running
- Check Flask is on http://localhost:5000
- Check CORS configuration allows localhost:3000

### "Authorization header missing" Error
- Token not being stored in localStorage
- Check browser DevTools → Application → Local Storage
- Look for "zeinaguard_access_token" key

### "Invalid token" Error
- JWT_SECRET_KEY doesn't match between Flask and Next.js
- Token expired (24 hour lifetime)
- Try logging out and logging back in

### CORS Errors
- Flask CORS configuration might be too restrictive
- Check docker-compose.yml for port mappings
- Ensure Next.js frontend can reach Flask backend

## Production Considerations

Before deploying to production:

1. **Change all demo passwords**
2. **Generate strong JWT_SECRET_KEY** (min 32 chars)
3. **Use environment variables** for sensitive config
4. **Enable HTTPS/TLS** for all communications
5. **Store tokens securely** (consider HTTP-only cookies)
6. **Implement refresh token rotation**
7. **Add rate limiting** on login endpoint
8. **Log authentication attempts**
9. **Implement 2FA** for admin accounts
10. **Use managed identity providers** (OAuth2, SAML)

## References

- Flask-JWT-Extended: https://flask-jwt-extended.readthedocs.io/
- Zustand: https://github.com/pmndrs/zustand
- JWT Best Practices: https://tools.ietf.org/html/rfc8725
- OWASP Authentication: https://owasp.org/www-project-authentication-cheat-sheet/
