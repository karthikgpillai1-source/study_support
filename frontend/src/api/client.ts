/** Thin fetch wrapper: bearer auth, JSON handling, typed errors. */

const TOKEN_KEY = 'sie.token'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  get isAuthError(): boolean {
    return this.status === 401
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

type Query = Record<string, string | number | boolean | null | undefined>

function buildUrl(path: string, query?: Query): string {
  const base = import.meta.env.VITE_API_BASE ?? '/api'
  const fullPath = base.replace(/\/$/, '') + '/' + path.replace(/^\//, '')
  
  // If base is an absolute URL, this will work. If it's a relative path like '/api', 
  // window.location.origin is needed to build a valid URL object.
  const url = new URL(fullPath, window.location.origin)
  
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value))
    }
  }
  
  // Return absolute URL or just pathname + search if base was relative.
  // Actually returning the full URL is totally fine and works with fetch.
  return url.toString()
}

async function request<T>(
  method: string,
  path: string,
  options: { body?: unknown; query?: Query; form?: FormData } = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  let body: BodyInit | undefined
  if (options.form) {
    body = options.form
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }

  let response: Response
  try {
    response = await fetch(buildUrl(path, options.query), { method, headers, body })
  } catch {
    throw new ApiError(0, 'Cannot reach the API. Is the backend running on port 8000?')
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()
  const payload = text ? safeParse(text) : null

  if (!response.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : `Request failed (${response.status})`
    if (response.status === 401) setToken(null)
    throw new ApiError(response.status, detail)
  }

  return payload as T
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>('GET', path, { query }),
  post: <T>(path: string, body?: unknown, query?: Query) =>
    request<T>('POST', path, { body, query }),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, { body }),
  delete: <T>(path: string) => request<T>('DELETE', path),
  upload: <T>(path: string, form: FormData) => request<T>('POST', path, { form }),
}
