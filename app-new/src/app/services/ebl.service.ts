import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, BehaviorSubject } from 'rxjs';
import { tap } from 'rxjs/operators';
import { environment } from 'src/environments/environment';

export interface TokenInfo {
    scopes?: string[];
    permissions?: string[];
    exp?: number;
    iat?: number;
    sub?: string;
    aud?: string[];
    error?: string;
}

export interface EblStatus {
    configured: boolean;
    connected: boolean;
    api_url: string | null;
    error: string | null;
    auth_method?: 'oauth' | 'manual' | null;
    oauth_pending?: boolean;
    token_info?: TokenInfo | null;
}

export interface EblConfig {
    api_url: string;

    // Manual token (copied from browser after logging into eBL)
    access_token?: string;
}

// Structured validation error with line/column info
export interface ValidationError {
    line: number;      // 1-based line number
    column?: number;   // 1-based column number (if available)
    message: string;   // Error message
}

export interface ValidationResult {
    valid: boolean;
    errors: ValidationError[];       // Structured errors with position info
    error_strings?: string[];        // Legacy string errors (for backwards compatibility)
    warnings: string[];
    parsed_lines: number;
    // Indicates which validation method was used:
    // - 'ebl_api': Full eBL API validation with sign verification
    // - 'local_lark': Local Lark parser validation (syntax only, no sign verification)
    // - 'local_basic': Basic bracket checking fallback
    validation_source: 'ebl_api' | 'local_lark' | 'local_basic' | 'local';
}

export type ExportErrorCode =
    | 'VALIDATION_ERROR'
    | 'NO_PERMISSION'
    | 'TOKEN_EXPIRED'
    | 'NOT_FOUND'
    | 'API_ERROR'
    | 'NETWORK_ERROR'
    | 'UNKNOWN_ERROR';

export interface ExportResult {
    success: boolean;
    message: string;
    fragment_url: string | null;
    error_code?: ExportErrorCode | null;
    status_code?: number;
    help?: string;
    validation_errors?: string[];
}

export interface OAuthStatus {
    oauth_pending: boolean;
    oauth_error: string | null;
    authenticated: boolean;
    auth_method: string | null;
}

export interface EblFragment {
    museumNumber: string;
    accession?: string;
    cdliNumber?: string;
    // Content fields from eBL
    introduction?: string;      // Scholarly introduction
    transliteration?: string;   // ATF transliteration (mapped from 'atf' field)
    notes?: string;             // Editorial notes
}

@Injectable({
    providedIn: 'root'
})
export class EblService {
    private baseUrl = environment.apiUrl;
    private statusSubject = new BehaviorSubject<EblStatus | null>(null);

    status$ = this.statusSubject.asObservable();

    constructor(private http: HttpClient) {
        // Check status on service init
        this.checkStatus().subscribe({
            error: () => {
                // Silently fail if backend is not available
                this.statusSubject.next({ configured: false, connected: false, api_url: null, error: 'Backend not available' });
            }
        });
    }

    /**
     * Check if eBL API is configured and connected
     */
    checkStatus(): Observable<EblStatus> {
        return this.http.get<EblStatus>(`${this.baseUrl}/ebl/status`).pipe(
            tap(status => this.statusSubject.next(status))
        );
    }

    /**
     * Configure eBL API credentials
     */
    configure(config: EblConfig): Observable<{ success: boolean; message: string }> {
        return this.http.post<{ success: boolean; message: string }>(
            `${this.baseUrl}/ebl/configure`,
            config
        ).pipe(
            tap(() => this.checkStatus().subscribe())
        );
    }

    /**
     * Validate ATF text against eBL's parser
     */
    validateAtf(atfText: string, fragmentNumber?: string): Observable<ValidationResult> {
        return this.http.post<ValidationResult>(`${this.baseUrl}/ebl/validate`, {
            atf_text: atfText,
            fragment_number: fragmentNumber
        });
    }

    /**
     * Export transliteration to eBL
     */
    exportToEbl(fragmentNumber: string, atfText: string, notes?: string): Observable<ExportResult> {
        return this.http.post<ExportResult>(`${this.baseUrl}/ebl/export`, {
            fragment_number: fragmentNumber,
            atf_text: atfText,
            notes: notes
        });
    }

    /**
     * Get a fragment from eBL
     */
    getFragment(fragmentNumber: string): Observable<EblFragment> {
        return this.http.get<EblFragment>(
            `${this.baseUrl}/ebl/fragment/${encodeURIComponent(fragmentNumber)}`
        );
    }

    /**
     * Search for fragments in eBL
     */
    searchFragments(query: string, limit: number = 10): Observable<EblFragment[]> {
        return this.http.get<EblFragment[]>(`${this.baseUrl}/ebl/search`, {
            params: { query, limit: limit.toString() }
        });
    }

    /**
     * Start Auth0 PKCE OAuth login flow (opens system browser)
     */
    startOAuth(): Observable<{ status: string; message: string }> {
        return this.http.post<{ status: string; message: string }>(
            `${this.baseUrl}/ebl/oauth/start`, {}
        );
    }

    /**
     * Get OAuth flow status (for polling after starting OAuth)
     */
    getOAuthStatus(): Observable<OAuthStatus> {
        return this.http.get<OAuthStatus>(`${this.baseUrl}/ebl/oauth/status`);
    }

    /**
     * Log in with eBL email/password (Auth0 Password Grant)
     */
    login(username: string, password: string): Observable<{ success: boolean; message: string }> {
        return this.http.post<{ success: boolean; message: string }>(
            `${this.baseUrl}/ebl/auth/login`,
            { username, password }
        ).pipe(
            tap(() => this.checkStatus().subscribe())
        );
    }

    /**
     * Disconnect from eBL (clear all tokens)
     */
    disconnect(): Observable<{ success: boolean; message: string }> {
        return this.http.post<{ success: boolean; message: string }>(
            `${this.baseUrl}/ebl/disconnect`, {}
        ).pipe(
            tap(() => this.checkStatus().subscribe())
        );
    }

    /**
     * Get current status synchronously
     */
    get currentStatus(): EblStatus | null {
        return this.statusSubject.value;
    }

    /**
     * Check if eBL is configured
     */
    get isConfigured(): boolean {
        return this.statusSubject.value?.configured ?? false;
    }

    /**
     * Check if eBL is connected
     */
    get isConnected(): boolean {
        return this.statusSubject.value?.connected ?? false;
    }
}
