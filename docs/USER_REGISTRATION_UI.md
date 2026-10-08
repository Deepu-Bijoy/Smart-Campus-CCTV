# User Registration UI Documentation

## Overview

The Admin User Registration feature provides a secure, role-restricted frontend interface for system administrators to provision new accounts in the Smart Campus CCTV Surveillance System.

> [!IMPORTANT]
> **Public self-registration is intentionally not enabled. User creation is restricted to authenticated administrators.**

---

## 1. Page Location and Route

- **Component Path**: `frontend/src/pages/UserManagement/CreateUser.tsx`
- **Route**: `/users/create`
- **Layout Integration**: Nested within `<Layout />` in `frontend/src/App.tsx`, guarded by `<AdminRoute>` and `<ProtectedRoute>`.
- **Navigation**: Visible exclusively to administrators in `frontend/src/components/Sidebar.tsx` under:
  ```
  User Management
      └── Add User (/users/create)
  ```

---

## 2. Page & Form Specification

### Header & Subtitle
- **Page Title**: `Create New User`
- **Subtitle**: `Add a new authorized user to the Smart Campus Surveillance System.`
- **Navigation Controls**: "Back to Dashboard" navigation link.

### Form Fields & Inputs
1. **Full Name** (`fullName`):
   - Type: Text input (`maxLength={100}`)
   - Validation: Required, trimmed whitespace, maximum 100 characters.
2. **Email Address** (`email`):
   - Type: Email input
   - Validation: Required, standard RFC email format regex, normalized to lowercase on submission.
3. **Role** (`role`):
   - Type: Controlled dropdown select (`<select id="role">`)
   - Permitted Options:
     - `Operator` (`operator`): CCTV Surveillance & Monitoring access
     - `User` (`user`): Standard Campus Staff / Read-Only access
   - **Security Constraint**: Free-text entry is blocked. The `admin` role is intentionally **not exposed** in the dropdown to prevent unvetted administrative privilege escalation.
4. **Password** (`password`):
   - Type: Password with visibility toggle (`Eye` / `EyeOff` icons)
   - Validation: Required, minimum length 8 characters, maximum 100 characters.
5. **Confirm Password** (`confirmPassword`):
   - Type: Password with visibility toggle (`Eye` / `EyeOff` icons)
   - Validation: Required, must match `password` identically.

---

## 3. Backend API Integration

The frontend connects directly to the existing backend signup endpoint without altering backend authorization or data contracts:

- **Endpoint**: `POST /api/v1/auth/signup`
- **Client**: Existing Axios client (`frontend/src/services/api.ts`)
- **Headers**: Automatically populated with JWT bearer token via Axios request interceptor:
  ```
  Authorization: Bearer <ADMIN_JWT_TOKEN>
  ```
- **Request Payload**:
  ```json
  {
    "email": "operator.smith@campus.edu",
    "password": "SecurePassword@123",
    "full_name": "Officer Smith",
    "role": "operator",
    "is_active": true
  }
  ```
- **Backend Authorization**: Enforced by `backend/app/api/v1/auth.py` via `current_user: User = Depends(deps.require_admin)`.

---

## 4. Response & Error Handling Matrix

| HTTP Status | Condition | Frontend UI Behavior |
|:---|:---|:---|
| **201 Created** | User provisioned successfully | Displays emerald success banner: `"User created successfully."` with user details badge and role indicator. Form fields are reset. |
| **400 Bad Request** | Duplicate email / invalid input | Displays backend error cleanly: `"The user with this email already exists in the system."` |
| **401 Unauthorized** | Session expired / missing token | Displays `"Your session has expired. Please log in again."` and redirects to `/login`. |
| **403 Forbidden** | Non-admin caller attempting creation | Displays permission banner: `"You do not have permission to create users."` |
| **409 Conflict** | Resource conflict | Displays backend conflict detail message. |
| **422 Unprocessable** | Request schema validation failure | Displays formatted validation message without exposing internal stack traces. |
| **500 Server Error** | Unexpected backend exception | Displays sanitized alert: `"Unable to create user. Please try again."` Raw stack traces are never shown. |

---

## 5. Security & Access Control Architecture

1. **Multi-Layer Defense**:
   - **Frontend Route Guard (`AdminRoute`)**: Checks `useAuthStore.getState().user?.role === 'admin'`. Non-admin sessions navigating to `/users/create` are redirected to `/`.
   - **In-Component Guard**: `CreateUser.tsx` checks `isAdmin`. If an unauthorized session renders the view, an `"Access Restricted"` card is shown and form controls are completely suppressed.
   - **Backend Authoritative RBAC**: `deps.require_admin` enforces HTTP 403 at the server level.
2. **Credential Hygiene**:
   - Passwords are never logged to `console.log`.
   - Passwords are never stored in `localStorage` or persisted beyond form submission state.
   - Form fields and passwords are wiped immediately upon successful submission.
   - No JWT tokens or secrets are exposed in the DOM.

---

## 6. Empirical Verification & Test Results

### Automated Browser & CDP End-to-End Suite
Conducted via headless Chrome with DevTools Protocol against the running application:

| Test ID | Test Scenario | Expected Result | Actual Result | Status |
|:---|:---|:---|:---|:---|
| **TEST 1** | Unauthenticated navigation to `/users/create` | Redirect to `/login` | Redirected to `/login` | **PASS** |
| **TEST 2** | Operator login and sidebar inspection | "User Management" hidden | Sidebar link not rendered | **PASS** |
| **TEST 2B** | Operator navigation to `/users/create` | Access blocked / redirect | Redirected to `/` | **PASS** |
| **TEST 3** | Admin login (`admin@campus.edu`) | "User Management -> Add User" visible | Sidebar link rendered | **PASS** |
| **TEST 3B** | Admin access to `/users/create` | Form renders with title & role select | Page heading and form rendered | **PASS** |
| **TEST 3C** | Role dropdown inspection | Roles restricted to `operator`, `user` | Options: `['operator', 'user']` | **PASS** |
| **TEST 4** | Empty form submission | Client-side validation errors | 4 field error messages displayed | **PASS** |
| **TEST 4B** | Invalid email, short pwd, mismatch | Field-specific validation errors | 3 validation messages displayed | **PASS** |
| **TEST 5** | Duplicate email (`operator@campus.edu`) | Backend 400 error banner | Error banner: "already exists" | **PASS** |
| **TEST 6** | Valid user submission | HTTP 201, success notice, form cleared | Success banner displayed, form reset | **PASS** |
| **TEST 7** | Browser refresh on `/users/create` | Admin session and route preserved | Session intact at `/users/create` | **PASS** |

### API Contract & RBAC Regression
Executed via Python API verification and pytest:
- **`scratch/verify_signup_api.py`**:
  - Admin login: **PASS**
  - Admin `/auth/me` returns `role='admin'`: **PASS**
  - Unauthenticated `POST /auth/signup` returns HTTP 401: **PASS**
  - Operator `POST /auth/signup` returns HTTP 403: **PASS**
  - Ordinary user `POST /auth/signup` returns HTTP 403: **PASS**
  - Duplicate email returns HTTP 400: **PASS**
  - Valid admin user creation returns HTTP 201: **PASS**
  - Created user immediately authenticates: **PASS**
- **Locked Test Suites**:
  - Security suite: **48/48 PASS**
  - Resilience remediation suite: **15/15 PASS**
  - Resilience validation suite: **43/43 PASS**
  - FAIL-04 concurrency suite: **7/7 PASS**
  - API contract validation suite: **26/26 PASS**
