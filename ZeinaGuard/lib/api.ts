/**
 * API Client for ZeinaGuard Pro
 * Handles all HTTP requests to Flask backend
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';

// Token storage keys
const ACCESS_TOKEN_KEY = 'zeinaguard_access_token';
const USER_KEY = 'zeinaguard_user';

/**
 * API Response type
 */
interface ApiResponse<T = any> {
  data?: T;
  error?: string;
  message?: string;
  code?: string;
}

/**
 * User type from API
 */
export interface User {
  id: number;
  username: string;
  email: string;
  is_admin: boolean;
}

/**
 * Login response type
 */
export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

/**
 * Get stored access token
 */
export function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

/**
 * Store access token
 */
export function setAccessToken(token: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(ACCESS_TOKEN_KEY, token);
}

/**
 * Clear access token
 */
export function clearAccessToken(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/**
 * Get stored user data
 */
export function getStoredUser(): User | null {
  if (typeof window === 'undefined') return null;
  const userStr = localStorage.getItem(USER_KEY);
  if (!userStr) return null;
  try {
    return JSON.parse(userStr);
  } catch {
    return null;
  }
}

/**
 * Store user data
 */
export function setStoredUser(user: User): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

/**
 * Check if user is authenticated
 */
export function isAuthenticated(): boolean {
  return !!getAccessToken();
}

/**
 * Make API request with authentication
 */
async function apiRequest<T = any>(
  endpoint: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const url = `${API_URL}${endpoint}`;
  const token = getAccessToken();

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  try {
    const response = await fetch(url, {
      ...options,
      headers,
    });

    const data = await response.json();

    if (!response.ok) {
      // Handle 401 - token expired or invalid
      if (response.status === 401) {
        clearAccessToken();
      }

      return {
        error: data.error || 'Request failed',
        code: data.code,
      };
    }

    return { data };
  } catch (error) {
    return {
      error: error instanceof Error ? error.message : 'Network error',
    };
  }
}

/**
 * Authentication API calls
 */
export const authAPI = {
  /**
   * Login with username and password
   */
  async login(username: string, password: string): Promise<LoginResponse> {
    const response = await apiRequest<LoginResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });

    if (response.error) {
      throw new Error(response.error);
    }

    const loginResponse = response.data!;

    // Store tokens and user data
    setAccessToken(loginResponse.access_token);
    setStoredUser(loginResponse.user);

    return loginResponse;
  },

  /**
   * Logout user
   */
  async logout(): Promise<void> {
    await apiRequest('/api/auth/logout', {
      method: 'POST',
    });

    clearAccessToken();
  },

  /**
   * Refresh access token
   */
  async refresh(): Promise<LoginResponse> {
    const response = await apiRequest<LoginResponse>('/api/auth/refresh', {
      method: 'POST',
    });

    if (response.error) {
      clearAccessToken();
      throw new Error(response.error);
    }

    const loginResponse = response.data!;
    setAccessToken(loginResponse.access_token);
    setStoredUser(loginResponse.user);

    return loginResponse;
  },

  /**
   * Get current user
   */
  async getCurrentUser(): Promise<User> {
    const response = await apiRequest<User>('/api/auth/me');

    if (response.error) {
      throw new Error(response.error);
    }

    return response.data!;
  },
};

/**
 * Threats API calls
 */
export const threatsAPI = {
  /**
   * Get list of threats
   */
  async getThreats(params?: {
    limit?: number;
    offset?: number;
    severity?: string;
    resolved?: boolean;
  }) {
    const queryString = new URLSearchParams();
    if (params?.limit) queryString.append('limit', params.limit.toString());
    if (params?.offset) queryString.append('offset', params.offset.toString());
    if (params?.severity) queryString.append('severity', params.severity);
    if (params?.resolved !== undefined)
      queryString.append('resolved', params.resolved.toString());

    const response = await apiRequest(
      `/api/threats?${queryString.toString()}`
    );

    if (response.error) {
      throw new Error(response.error);
    }

    return response.data;
  },

  /**
   * Get threat details
   */
  async getThreat(threatId: number) {
    const response = await apiRequest(`/api/threats/${threatId}`);

    if (response.error) {
      throw new Error(response.error);
    }

    return response.data;
  },

  /**
   * Resolve threat
   */
  async resolveThreat(threatId: number) {
    const response = await apiRequest(
      `/api/threats/${threatId}/resolve`,
      {
        method: 'POST',
      }
    );

    if (response.error) {
      throw new Error(response.error);
    }

    return response.data;
  },
};

/**
 * Sensors API calls
 */
export const sensorsAPI = {
  /**
   * Get list of sensors
   */
  async getSensors() {
    const response = await apiRequest('/api/sensors');

    if (response.error) {
      throw new Error(response.error);
    }

    return response.data;
  },

  /**
   * Get sensor health metrics
   */
  async getSensorHealth(sensorId: number) {
    const response = await apiRequest(`/api/sensors/${sensorId}/health`);

    if (response.error) {
      throw new Error(response.error);
    }

    return response.data;
  },
};

/**
 * Alerts API calls
 */
export const alertsAPI = {
  /**
   * Get list of alerts
   */
  async getAlerts() {
    const response = await apiRequest('/api/alerts');

    if (response.error) {
      throw new Error(response.error);
    }

    return response.data;
  },

  /**
   * Acknowledge alert
   */
  async acknowledgeAlert(alertId: number) {
    const response = await apiRequest(
      `/api/alerts/${alertId}/acknowledge`,
      {
        method: 'POST',
      }
    );

    if (response.error) {
      throw new Error(response.error);
    }

    return response.data;
  },
};

/**
 * Analytics API calls
 */
export const analyticsAPI = {
  /**
   * Get threat statistics
   */
  async getThreatStats() {
    const response = await apiRequest('/api/analytics/threat-stats');

    if (response.error) {
      throw new Error(response.error);
    }

    return response.data;
  },

  /**
   * Get historical trends
   */
  async getTrends() {
    const response = await apiRequest('/api/analytics/trends');

    if (response.error) {
      throw new Error(response.error);
    }

    return response.data;
  },
};

/**
 * Users API calls
 */
export const usersAPI = {
  /**
   * Get user profile
   */
  async getProfile() {
    const response = await apiRequest('/api/users/profile');

    if (response.error) {
      throw new Error(response.error);
    }

    return response.data;
  },
};

/**
 * Unified API Client
 * Bundles all specialized APIs into a single exported object
 * to satisfy component imports.
 */
export const apiClient = {
  // Auth methods
  ...authAPI,
  
  // Threats methods
  ...threatsAPI,
  
  // Sensors methods
  ...sensorsAPI,
  
  // Alerts methods
  ...alertsAPI,
  
  // Analytics methods
  ...analyticsAPI,
  
  // Users methods
  ...usersAPI,
  
  // Generic request method (optional but useful)
  request: apiRequest
};

// Export default if needed
export default apiClient;