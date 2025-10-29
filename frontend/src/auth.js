/**
 * Authentication utilities for the frontend
 */

const TOKEN_KEY = 'auth_token';

export function getAuthToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuthToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function removeAuthToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export async function isAuthenticated() {
  // Since we're using HTTP-only cookies, check authentication via API
  try {
    const response = await fetch('/api/me', {
      credentials: 'include', // Include cookies
    });
    return response.ok;
  } catch (err) {
    return false;
  }
}

export function getAuthHeaders() {
  const token = getAuthToken();
  if (!token) {
    return {};
  }
  return {
    'Authorization': `Bearer ${token}`,
  };
}

export function clearAuthCache() {
  removeAuthToken();
}

export async function authenticatedFetch(url, options = {}) {
  const headers = {
    ...getAuthHeaders(),
    ...options.headers,
  };

  const response = await fetch(url, {
    ...options,
    headers,
  });

  // If unauthorized, clear token and redirect to login
  if (response.status === 401) {
    removeAuthToken();
    if (typeof window !== 'undefined') {
      // Use pushState instead of location.href to avoid full page reload
      window.history.pushState({}, '', '/login');
      // Trigger popstate to notify App.svelte of route change
      window.dispatchEvent(new PopStateEvent('popstate'));
    }
  }

  return response;
}

