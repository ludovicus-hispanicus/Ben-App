"""
eBL (Electronic Babylonian Literature) API Handler

Handles all communication with the eBL API including:
- Auth0 PKCE OAuth login flow
- Manual access token configuration (fallback)
- Automatic token refresh
- ATF validation
- Fragment export/import
"""

import logging
import os
import json
import time
import secrets
import hashlib
import base64
import webbrowser
import httpx
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from urllib.parse import urlencode


class EblHandler:
    """Handler for eBL API integration."""

    # Configuration file path
    CONFIG_FILE = Path(__file__).parent.parent / "ebl_config.json"

    # Auth0 PKCE Configuration (from eBL production frontend)
    AUTH0_DOMAIN = "auth.ebl.lmu.de"
    AUTH0_CLIENT_ID = "X_GcKmRe_G8F-zM4NeE3rWJTdcCgFko7"
    AUTH0_AUDIENCE = "dictionary-api"
    AUTH0_SCOPES = "openid profile offline_access read:words read:fragments transliterate:fragments read:texts write:texts read:bibliography"

    def __init__(self):
        self.api_url: Optional[str] = None
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.auth_method: Optional[str] = None  # "oauth" or "manual"

        # PKCE flow state (in-memory, not persisted)
        self._pkce_state: Optional[str] = None
        self._pkce_code_verifier: Optional[str] = None
        self._pkce_redirect_uri: Optional[str] = None
        self._oauth_pending: bool = False
        self._oauth_error: Optional[str] = None

        # Load configuration from file or environment
        self._load_config()

    # ==========================================
    # Configuration persistence
    # ==========================================

    def _load_config(self):
        """Load configuration from file or environment variables."""
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    self.api_url = config.get('api_url')
                    self.access_token = config.get('access_token')
                    self.refresh_token = config.get('refresh_token')
                    self.auth_method = config.get('auth_method')
                    logging.info(f"eBL config loaded from file (auth_method={self.auth_method})")
                    return
            except Exception as e:
                logging.warning(f"Failed to load eBL config from file: {e}")

        # Fall back to environment variables
        self.api_url = os.getenv('EBL_API_URL', 'https://www.ebl.lmu.de/api')
        self.access_token = os.getenv('EBL_ACCESS_TOKEN')

    def _save_config(self):
        """Save configuration to file."""
        config = {
            'api_url': self.api_url,
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'auth_method': self.auth_method,
        }

        try:
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
            logging.info("eBL config saved to file")
        except Exception as e:
            logging.error(f"Failed to save eBL config: {e}")

    # ==========================================
    # Auth0 PKCE OAuth Flow
    # ==========================================

    def _generate_pkce_params(self) -> Tuple[str, str]:
        """Generate PKCE code_verifier and code_challenge."""
        code_verifier = secrets.token_urlsafe(32)
        digest = hashlib.sha256(code_verifier.encode('ascii')).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
        return code_verifier, code_challenge

    def start_oauth_flow(self, callback_port: int) -> Dict[str, Any]:
        """Start the Auth0 PKCE login flow by opening the system browser."""
        self._oauth_error = None
        self._oauth_pending = True

        code_verifier, code_challenge = self._generate_pkce_params()
        state = secrets.token_urlsafe(16)

        self._pkce_code_verifier = code_verifier
        self._pkce_state = state
        self._pkce_redirect_uri = f"http://localhost:{callback_port}/api/v1/ebl/oauth/callback"

        params = {
            "response_type": "code",
            "client_id": self.AUTH0_CLIENT_ID,
            "redirect_uri": self._pkce_redirect_uri,
            "audience": self.AUTH0_AUDIENCE,
            "scope": self.AUTH0_SCOPES,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }

        auth_url = f"https://{self.AUTH0_DOMAIN}/authorize?{urlencode(params)}"
        logging.info(f"Opening Auth0 login: {auth_url[:100]}...")

        try:
            webbrowser.open(auth_url)
            return {"status": "pending", "message": "Browser opened for eBL login"}
        except Exception as e:
            self._oauth_pending = False
            self._oauth_error = f"Failed to open browser: {str(e)}"
            return {"status": "error", "message": self._oauth_error}

    async def handle_oauth_callback(self, code: str, state: str) -> Dict[str, Any]:
        """Handle the Auth0 callback: validate state, exchange code for tokens."""
        if not self._oauth_pending:
            return {"success": False, "error": "No OAuth flow in progress"}

        if state != self._pkce_state:
            self._oauth_pending = False
            self._oauth_error = "Invalid state parameter (possible CSRF attack)"
            return {"success": False, "error": self._oauth_error}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"https://{self.AUTH0_DOMAIN}/oauth/token",
                    json={
                        "grant_type": "authorization_code",
                        "client_id": self.AUTH0_CLIENT_ID,
                        "code_verifier": self._pkce_code_verifier,
                        "code": code,
                        "redirect_uri": self._pkce_redirect_uri,
                    }
                )

            if response.status_code != 200:
                error_detail = response.text
                try:
                    error_detail = response.json().get("error_description", response.text)
                except Exception:
                    pass
                self._oauth_pending = False
                self._oauth_error = f"Token exchange failed: {error_detail}"
                logging.error(f"Auth0 token exchange failed ({response.status_code}): {error_detail}")
                return {"success": False, "error": self._oauth_error}

            token_data = response.json()
            self.access_token = token_data.get("access_token")
            self.refresh_token = token_data.get("refresh_token")
            self.auth_method = "oauth"
            self.api_url = self.api_url or "https://www.ebl.lmu.de/api"

            # Test the connection
            await self._test_connection()

            # Save config
            self._save_config()

            # Clear PKCE state
            self._pkce_code_verifier = None
            self._pkce_state = None
            self._pkce_redirect_uri = None
            self._oauth_pending = False
            self._oauth_error = None

            logging.info("Auth0 PKCE login successful")
            return {"success": True}

        except Exception as e:
            self._oauth_pending = False
            self._oauth_error = f"OAuth callback failed: {str(e)}"
            logging.error(f"OAuth callback error: {e}")
            return {"success": False, "error": self._oauth_error}

    def get_oauth_status(self) -> Dict[str, Any]:
        """Get the current OAuth flow status (for frontend polling)."""
        return {
            "oauth_pending": self._oauth_pending,
            "oauth_error": self._oauth_error,
            "authenticated": self.is_configured,
            "auth_method": self.auth_method,
        }

    # ==========================================
    # Password Grant (Resource Owner Password)
    # ==========================================

    async def login_with_credentials(self, username: str, password: str) -> Dict[str, Any]:
        """Log in to eBL using email/password via Auth0 Password Grant."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"https://{self.AUTH0_DOMAIN}/oauth/token",
                    json={
                        "grant_type": "password",
                        "client_id": self.AUTH0_CLIENT_ID,
                        "audience": self.AUTH0_AUDIENCE,
                        "scope": self.AUTH0_SCOPES,
                        "username": username,
                        "password": password,
                    }
                )

            if response.status_code != 200:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = error_json.get("error_description", error_json.get("error", response.text))
                except Exception:
                    pass
                logging.warning(f"Password grant failed ({response.status_code}): {error_detail}")
                return {"success": False, "error": error_detail}

            token_data = response.json()
            self.access_token = token_data.get("access_token")
            self.refresh_token = token_data.get("refresh_token")
            self.auth_method = "oauth"
            self.api_url = self.api_url or "https://www.ebl.lmu.de/api"

            self._save_config()
            logging.info("Password grant login successful")
            return {"success": True}

        except Exception as e:
            logging.error(f"Password grant error: {e}")
            return {"success": False, "error": str(e)}

    # ==========================================
    # Token management
    # ==========================================

    def is_token_expired(self) -> bool:
        """Check if the access token is expired or will expire within 60 seconds."""
        if not self.access_token:
            return True
        token_info = self.get_token_info()
        exp = token_info.get("exp")
        if not exp:
            return False  # Can't determine expiry, assume valid
        return time.time() >= (exp - 60)

    async def refresh_access_token(self) -> bool:
        """Use the refresh token to get a new access token."""
        if not self.refresh_token:
            return False

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"https://{self.AUTH0_DOMAIN}/oauth/token",
                    json={
                        "grant_type": "refresh_token",
                        "client_id": self.AUTH0_CLIENT_ID,
                        "refresh_token": self.refresh_token,
                    }
                )

            if response.status_code != 200:
                logging.warning(f"Token refresh failed ({response.status_code}): {response.text}")
                return False

            token_data = response.json()
            self.access_token = token_data.get("access_token", self.access_token)
            # Auth0 may rotate refresh tokens
            if token_data.get("refresh_token"):
                self.refresh_token = token_data["refresh_token"]
            self._save_config()
            logging.info("Access token refreshed successfully")
            return True

        except Exception as e:
            logging.error(f"Token refresh error: {e}")
            return False

    async def ensure_valid_token(self) -> bool:
        """Ensure the access token is valid, refreshing if needed. Returns True if valid."""
        if not self.is_token_expired():
            return True
        if self.auth_method == "oauth" and self.refresh_token:
            return await self.refresh_access_token()
        return False

    def disconnect(self):
        """Clear all tokens and reset connection state."""
        self.access_token = None
        self.refresh_token = None
        self.auth_method = None
        self._oauth_pending = False
        self._oauth_error = None
        self._save_config()
        logging.info("Disconnected from eBL")

    @property
    def is_configured(self) -> bool:
        """Check if eBL API is configured."""
        return bool(self.api_url and self.access_token)

    def get_token_info(self) -> Dict[str, Any]:
        """
        Decode the JWT token to show its claims (including scopes).
        This helps debug permission issues.
        """
        if not self.access_token:
            return {"error": "No token configured"}

        try:
            import base64

            # JWT has 3 parts: header.payload.signature
            parts = self.access_token.split('.')
            if len(parts) != 3:
                return {"error": "Invalid JWT format"}

            # Decode the payload (middle part)
            # Add padding if needed
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding

            decoded = base64.urlsafe_b64decode(payload)
            claims = json.loads(decoded)

            # Extract useful info
            return {
                "scopes": claims.get("scope", "").split() if claims.get("scope") else [],
                "permissions": claims.get("permissions", []),
                "exp": claims.get("exp"),
                "iat": claims.get("iat"),
                "sub": claims.get("sub"),
                "aud": claims.get("aud"),
            }
        except Exception as e:
            logging.warning(f"Failed to decode token: {e}")
            return {"error": f"Failed to decode token: {str(e)}"}

    async def configure(
        self,
        api_url: str,
        access_token: str,
    ):
        """Configure eBL API with manual access token."""
        self.api_url = api_url
        self.access_token = access_token
        self.auth_method = "manual"
        self.refresh_token = None

        # Test the token by making a simple request
        await self._test_connection()

        # Save if successful
        self._save_config()

    async def _test_connection(self):
        """Test the connection with the current token."""
        if not self.access_token:
            raise ValueError("No access token provided")

        # Try to access the API to verify the token works
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.api_url}/words/aklu I",
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json"
                    }
                )
                # 200 = success, 404 = word not found (but auth worked)
                if response.status_code in [200, 404]:
                    logging.info("eBL connection test successful")
                    return
                elif response.status_code == 401:
                    raise ValueError("Token is invalid or expired. Please get a fresh token from eBL.")
                else:
                    raise ValueError(f"eBL API returned status {response.status_code}")
        except httpx.RequestError as e:
            raise ValueError(f"Failed to connect to eBL API: {str(e)}")

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        require_auth: bool = True,
        _retry: bool = False
    ) -> Dict[str, Any]:
        """Make a request to the eBL API with automatic token refresh."""
        url = f"{self.api_url}{endpoint}"

        # Ensure token is valid before making the request
        if require_auth:
            await self.ensure_valid_token()
            if not self.access_token:
                raise ValueError("No access token configured")

        headers = {"Content-Type": "application/json"}
        if require_auth:
            headers["Authorization"] = f"Bearer {self.access_token}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            if method.upper() == "GET":
                response = await client.get(url, headers=headers, params=params)
            elif method.upper() == "POST":
                response = await client.post(url, headers=headers, json=data)
            elif method.upper() == "PATCH":
                response = await client.patch(url, headers=headers, json=data)
            elif method.upper() == "PUT":
                response = await client.put(url, headers=headers, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            # On 401, try one refresh + retry
            if response.status_code == 401 and not _retry:
                if self.auth_method == "oauth" and await self.refresh_access_token():
                    return await self._make_request(method, endpoint, data, params, require_auth, _retry=True)
                raise ValueError("Token expired or invalid. Please reconnect to eBL.")

            if response.status_code >= 400:
                error_msg = f"eBL API error ({response.status_code}): {response.text}"
                logging.error(error_msg)
                raise ValueError(error_msg)

            if response.text:
                return response.json()
            return {}

    async def get_status(self) -> Dict[str, Any]:
        """Get eBL connection status including token scopes."""
        result = {
            "configured": self.is_configured,
            "connected": False,
            "api_url": self.api_url,
            "error": None,
            "token_info": None,
            "auth_method": self.auth_method,
            "oauth_pending": self._oauth_pending,
        }

        if not self.is_configured:
            result["error"] = "eBL access token not configured"
            return result

        # Try to refresh if token is expired (for OAuth)
        if self.is_token_expired() and self.auth_method == "oauth" and self.refresh_token:
            await self.refresh_access_token()

        # Include token info (scopes, expiry, etc.)
        result["token_info"] = self.get_token_info()

        # If token is expired (and couldn't be refreshed), mark as not connected
        if self.is_token_expired():
            result["connected"] = False
            result["error"] = "Token has expired. Please reconnect."
            return result

        try:
            await self._test_connection()
            result["connected"] = True
        except Exception as e:
            result["error"] = str(e)

        return result

    async def validate_atf(
        self,
        atf_text: str,
        fragment_number: Optional[str] = None,
        allow_ebl_api: bool = False
    ) -> Dict[str, Any]:
        """
        Validate ATF text.

        CRITICAL: The eBL API POST endpoint validates AND SAVES in one operation!
        There is no read-only validation endpoint. Therefore:

        - allow_ebl_api=False (default): Use LOCAL validation only (safe for live validation)
        - allow_ebl_api=True: Use eBL API which will SAVE the text if valid
                              Only use this during actual export!

        Strategy when allow_ebl_api=True:
        1. If eBL is connected, use API validation (validates AND saves)
        2. If eBL is not connected, fall back to local validation

        Strategy when allow_ebl_api=False (default):
        - Always use local validation (safe, read-only)
        """
        logging.info(f"validate_atf called with fragment_number: '{fragment_number}', is_configured: {self.is_configured}, allow_ebl_api: {allow_ebl_api}")

        # Only try API validation if explicitly allowed (during export)
        # WARNING: The eBL API POST validates AND saves - it's NOT read-only!
        if allow_ebl_api and self.is_configured:
            try:
                api_result = await self._validate_via_api(atf_text, fragment_number)
                logging.info(f"API validation result: {api_result is not None}")
                if api_result is not None:
                    return api_result
            except Exception as e:
                logging.warning(f"API validation failed, falling back to local: {e}")

        # Use local validation (safe, read-only)
        return self._validate_locally(atf_text)

    async def _validate_via_api(
        self,
        atf_text: str,
        fragment_number: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Validate ATF text using eBL API.

        Sends to the edition endpoint and checks for 422 validation errors.
        Returns None if API is unavailable or fails unexpectedly.
        """
        if not fragment_number:
            # Without a fragment number, we can't use the edition endpoint for validation
            logging.info("No fragment_number provided, falling back to local validation")
            return None

        # Strip part suffix (e.g., "MS.2670-0" -> "MS.2670")
        # Part suffixes are added by BEn for multi-part tablets
        clean_fragment_number = fragment_number
        if '-' in fragment_number:
            # Check if the suffix after the last hyphen is a number (part index)
            parts = fragment_number.rsplit('-', 1)
            if len(parts) == 2 and parts[1].isdigit():
                clean_fragment_number = parts[0]
                logging.info(f"Stripped part suffix: '{fragment_number}' -> '{clean_fragment_number}'")

        try:
            endpoint = f"/fragments/{clean_fragment_number}/edition"
            logging.info(f"Calling eBL API: {self.api_url}{endpoint}")
            payload = {"transliteration": atf_text}

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.api_url}{endpoint}",
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json"
                    },
                    json=payload
                )

                logging.info(f"eBL API response status: {response.status_code}")

                if response.status_code == 200:
                    # Valid ATF
                    logging.info("eBL API validation successful")
                    return {
                        "valid": True,
                        "errors": [],
                        "error_strings": [],
                        "warnings": [],
                        "parsed_lines": len(atf_text.strip().split('\n')),
                        "validation_source": "ebl_api"
                    }
                elif response.status_code == 422:
                    # Validation error - parse the error response
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("description", str(error_data))
                        # Parse eBL error format into structured errors
                        errors, error_strings = self._parse_ebl_validation_errors(error_msg)
                        return {
                            "valid": False,
                            "errors": errors,
                            "error_strings": error_strings,
                            "warnings": [],
                            "parsed_lines": len(atf_text.strip().split('\n')),
                            "validation_source": "ebl_api"
                        }
                    except Exception:
                        return {
                            "valid": False,
                            "errors": [{"line": 1, "message": response.text}],
                            "error_strings": [response.text],
                            "warnings": [],
                            "parsed_lines": len(atf_text.strip().split('\n')),
                            "validation_source": "ebl_api"
                        }
                elif response.status_code == 401:
                    # Token expired, fall back to local
                    logging.warning("eBL token expired, falling back to local validation")
                    return None
                elif response.status_code == 403:
                    # No permission to edit this fragment - log details for debugging
                    try:
                        error_body = response.text
                        logging.info(f"403 Forbidden for fragment {clean_fragment_number}: {error_body}")
                    except:
                        pass
                    # Check if this is a scope issue vs fragment-specific permission
                    logging.info(f"No permission to edit fragment {clean_fragment_number}. "
                                 "This may be fragment-specific or require 'transliterate:fragments' scope. "
                                 "Using local validation.")
                    return None
                elif response.status_code == 404:
                    # Fragment not found - can still validate syntax locally
                    logging.info(f"Fragment {clean_fragment_number} not found in eBL, using local validation")
                    return None
                else:
                    # Other error, fall back to local
                    logging.warning(f"eBL API returned unexpected status {response.status_code}, using local validation")
                    return None

        except httpx.RequestError as e:
            logging.warning(f"eBL API request failed: {e}")
            return None

    def _parse_ebl_validation_errors(self, error_msg) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Parse eBL validation error message into structured errors.

        Returns:
            Tuple of (structured_errors, error_strings)
            structured_errors: List of {line, column, message} dicts
            error_strings: List of human-readable error strings
        """
        import re

        structured_errors = []
        error_strings = []

        def parse_single_error(err_text: str) -> Tuple[Dict[str, Any], str]:
            """Parse a single error string to extract line/column info."""
            # Try to match patterns like "Line 5, column 10: message" or "Line 5: message"
            line_col_match = re.match(r'^Line\s+(\d+),?\s*(?:col(?:umn)?\s*(\d+))?[:\s]+(.*)$', err_text, re.IGNORECASE)
            if line_col_match:
                line_num = int(line_col_match.group(1))
                col_num = int(line_col_match.group(2)) if line_col_match.group(2) else None
                message = line_col_match.group(3).strip()

                error = {"line": line_num, "message": message}
                if col_num is not None:
                    error["column"] = col_num
                    err_str = f"Line {line_num}, col {col_num}: {message}"
                else:
                    err_str = f"Line {line_num}: {message}"
                return error, err_str

            # Fallback: no line/column info
            return {"line": 1, "message": err_text}, err_text

        if isinstance(error_msg, dict):
            # Handle dict format
            if "description" in error_msg:
                err, err_str = parse_single_error(error_msg["description"])
                structured_errors.append(err)
                error_strings.append(err_str)
            elif "message" in error_msg:
                err, err_str = parse_single_error(error_msg["message"])
                structured_errors.append(err)
                error_strings.append(err_str)
            else:
                err, err_str = parse_single_error(str(error_msg))
                structured_errors.append(err)
                error_strings.append(err_str)
        elif isinstance(error_msg, list):
            for e in error_msg:
                err, err_str = parse_single_error(str(e))
                structured_errors.append(err)
                error_strings.append(err_str)
        elif isinstance(error_msg, str):
            # Split by newline if multiple errors
            for line in error_msg.split('\n'):
                line = line.strip()
                if line:
                    err, err_str = parse_single_error(line)
                    structured_errors.append(err)
                    error_strings.append(err_str)

        if not structured_errors:
            structured_errors = [{"line": 1, "message": "Validation failed"}]
            error_strings = ["Validation failed"]

        return structured_errors, error_strings

    def _validate_locally(self, atf_text: str) -> Dict[str, Any]:
        """
        Local validation for eBL-ATF syntax checking using Lark parser.

        This is a fallback when eBL API is not available.
        Uses the eBL-ATF Lark grammar for proper syntax validation.
        Note: Does NOT verify signs against the sign database.
        """
        try:
            from services.ebl_atf_parser import validate_atf
            return validate_atf(atf_text)
        except ImportError:
            logging.warning("ebl_atf_parser not available, using basic validation")
            return self._basic_validate_locally(atf_text)

    def _basic_validate_locally(self, atf_text: str) -> Dict[str, Any]:
        """
        Basic local validation without Lark parser.

        This is a last-resort fallback when neither the API nor the Lark parser
        is available. Only checks for unmatched brackets.
        """
        import re

        errors: List[Dict[str, Any]] = []
        error_strings: List[str] = []
        warnings = []
        parsed_lines = 0

        lines = atf_text.strip().split('\n')

        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue

            parsed_lines += 1

            # Basic eBL-ATF validation rules
            # Control lines
            if line.startswith('&'):
                # &-line: ATF identifier line
                if not line.startswith('&P') and not line.startswith('&X'):
                    warnings.append(f"Line {i}: Unusual &-line format")

            elif line.startswith('#'):
                # Comment or note line
                if line.startswith('#note:'):
                    pass  # Valid note
                elif line.startswith('#tr'):
                    pass  # Translation line
                elif line.startswith('# '):
                    pass  # Regular comment
                else:
                    warnings.append(f"Line {i}: Unknown #-line format")

            elif line.startswith('@'):
                # Structure line (@obverse, @reverse, etc.)
                valid_structures = [
                    '@tablet', '@envelope', '@prism', '@bulla',
                    '@obverse', '@reverse', '@left', '@right', '@top', '@bottom',
                    '@edge', '@face', '@surface', '@column',
                    '@m=', '@colophon', '@seal', '@date'
                ]
                if not any(line.startswith(s) or line.startswith(s.split('=')[0]) for s in valid_structures):
                    if not line.startswith('@'):
                        msg = f"Invalid @-line: {line}"
                        errors.append({"line": i, "message": msg})
                        error_strings.append(f"Line {i}: {msg}")

            elif line.startswith('$'):
                # State line ($-line)
                pass  # $-lines describe state, hard to validate without full grammar

            elif line.startswith('//'):
                # Parallel line
                pass

            else:
                # Text line - check for basic issues
                # Check for unmatched brackets
                bracket_pairs = [('[', ']'), ('(', ')'), ('<', '>'), ('{', '}')]
                for open_b, close_b in bracket_pairs:
                    if line.count(open_b) != line.count(close_b):
                        msg = f"Unmatched brackets '{open_b}' and '{close_b}'"
                        errors.append({"line": i, "message": msg})
                        error_strings.append(f"Line {i}: {msg}")

                # Check for line number format (should be like "1." or "1'.")
                if not re.match(r"^\d+'?\.\s", line) and not line.startswith('$') and not line.startswith('#'):
                    # Might be missing line number, but not always required
                    pass

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "error_strings": error_strings,
            "warnings": warnings,
            "parsed_lines": parsed_lines,
            "validation_source": "local_basic"
        }

    async def export_to_ebl(
        self,
        fragment_number: str,
        atf_text: str,
        notes: Optional[str] = None,
        introduction: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Export transliteration to eBL.

        This updates the fragment edition with the new ATF content.
        Uses the /fragments/{number}/edition endpoint.
        Required scope: transliterate:fragments
        """
        # Log export attempt with timestamp for debugging
        import datetime
        timestamp = datetime.datetime.now().isoformat()
        logging.info(f"[eBL EXPORT] {timestamp} - Starting export for fragment '{fragment_number}'")
        logging.info(f"[eBL EXPORT] ATF content length: {len(atf_text)} chars, {len(atf_text.splitlines())} lines")

        if not self.is_configured:
            raise ValueError("eBL API is not configured")

        # First validate the ATF
        validation = await self.validate_atf(atf_text, fragment_number)
        if not validation["valid"]:
            # Use error_strings (human-readable) not errors (dicts)
            error_messages = validation.get('error_strings', [str(e) for e in validation.get('errors', [])])
            return {
                "success": False,
                "message": f"ATF validation failed: {', '.join(error_messages)}",
                "fragment_url": None,
                "error_code": "VALIDATION_ERROR",
                "validation_errors": error_messages
            }

        # Strip part suffix for eBL API (e.g., "MS.2670-0" -> "MS.2670")
        clean_fragment_number = fragment_number
        if '-' in fragment_number:
            parts = fragment_number.rsplit('-', 1)
            if len(parts) == 2 and parts[1].isdigit():
                clean_fragment_number = parts[0]

        try:
            # eBL API endpoint for updating fragment edition
            # See: https://github.com/ElectronicBabylonianLiterature/ebl-api/blob/master/ebl/fragmentarium/web/edition.py
            endpoint = f"/fragments/{clean_fragment_number}/edition"

            # Prepare the payload - all fields are optional strings
            payload = {
                "transliteration": atf_text
            }
            if notes:
                payload["notes"] = notes
            if introduction:
                payload["introduction"] = introduction

            # Make the request - eBL will perform full validation including sign database
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.api_url}{endpoint}",
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json"
                    },
                    json=payload
                )

                if response.status_code == 200:
                    fragment_url = f"https://www.ebl.lmu.de/fragmentarium/{clean_fragment_number}"
                    logging.info(f"[eBL EXPORT] SUCCESS - Fragment '{clean_fragment_number}' exported at {datetime.datetime.now().isoformat()}")
                    logging.info(f"[eBL EXPORT] Fragment URL: {fragment_url}")
                    return {
                        "success": True,
                        "message": "Successfully exported to eBL",
                        "fragment_url": fragment_url,
                        "error_code": None
                    }

                elif response.status_code == 422:
                    # Validation error from eBL - this includes sign database errors
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("description", str(error_data))
                        errors, error_strings = self._parse_ebl_validation_errors(error_msg)
                        return {
                            "success": False,
                            "message": "eBL validation failed (sign database check)",
                            "validation_errors": error_strings,
                            "fragment_url": None,
                            "error_code": "VALIDATION_ERROR",
                            "status_code": 422
                        }
                    except Exception:
                        return {
                            "success": False,
                            "message": f"eBL validation failed: {response.text}",
                            "fragment_url": None,
                            "error_code": "VALIDATION_ERROR",
                            "status_code": 422
                        }

                elif response.status_code == 403:
                    # Try to get more details from the response
                    try:
                        error_body = response.json()
                        error_detail = error_body.get("description", error_body.get("title", response.text))
                    except:
                        error_detail = response.text

                    logging.info(f"Export 403 response: {error_detail}")
                    return {
                        "success": False,
                        "message": f"No write permission for fragment '{clean_fragment_number}'. {error_detail}",
                        "fragment_url": None,
                        "error_code": "NO_PERMISSION",
                        "status_code": 403,
                        "help": "Your account needs the 'transliterate:fragments' scope. Contact the eBL team if you believe you should have access.",
                        "debug_info": {
                            "fragment": clean_fragment_number,
                            "response": error_detail
                        }
                    }

                elif response.status_code == 401:
                    return {
                        "success": False,
                        "message": "Token expired or invalid. Please refresh your eBL token.",
                        "fragment_url": None,
                        "error_code": "TOKEN_EXPIRED",
                        "status_code": 401,
                        "help": "Copy a fresh token from your browser after logging into eBL."
                    }

                elif response.status_code == 404:
                    return {
                        "success": False,
                        "message": f"Fragment '{clean_fragment_number}' not found in eBL database.",
                        "fragment_url": None,
                        "error_code": "NOT_FOUND",
                        "status_code": 404,
                        "help": "Check if the fragment number is correct, or the fragment may not exist in eBL yet."
                    }

                else:
                    return {
                        "success": False,
                        "message": f"eBL API error: {response.text}",
                        "fragment_url": None,
                        "error_code": "API_ERROR",
                        "status_code": response.status_code
                    }

        except httpx.RequestError as e:
            return {
                "success": False,
                "message": f"Network error: Could not connect to eBL API",
                "fragment_url": None,
                "error_code": "NETWORK_ERROR",
                "help": "Check your internet connection and eBL API URL."
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Export failed: {str(e)}",
                "fragment_url": None,
                "error_code": "UNKNOWN_ERROR"
            }

    async def get_fragment(self, fragment_number: str) -> Dict[str, Any]:
        """Get a fragment from eBL."""
        if not self.is_configured:
            raise ValueError("eBL API is not configured")

        # Strip part suffix for eBL API (e.g., "MS.2225-0" -> "MS.2225")
        clean_fragment_number = fragment_number
        if '-' in fragment_number:
            parts = fragment_number.rsplit('-', 1)
            if len(parts) == 2 and parts[1].isdigit():
                clean_fragment_number = parts[0]
                logging.info(f"Stripped part suffix: '{fragment_number}' -> '{clean_fragment_number}'")

        endpoint = f"/fragments/{clean_fragment_number}"
        result = await self._make_request("GET", endpoint)

        # eBL API uses 'atf' field for transliteration, not 'transliteration'
        # Map it to 'transliteration' for our frontend interface
        if isinstance(result, dict):
            # The ATF content is in the 'atf' field
            if 'atf' in result and result['atf']:
                result['transliteration'] = result['atf']
                logging.info(f"Mapped 'atf' field to 'transliteration': {len(result['atf'])} chars")
            else:
                logging.info(f"Fragment has no ATF content")

            # Log other content fields
            if 'introduction' in result and result['introduction']:
                logging.info(f"Fragment has introduction: {len(result['introduction'])} chars")
            if 'notes' in result and result['notes']:
                logging.info(f"Fragment has notes: {len(result['notes'])} chars")

        return result

    async def search_fragments(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Search for fragments in eBL."""
        # eBL public API - may not require auth for search
        endpoint = "/fragments"
        params = {
            "query": query,
            "limit": limit
        }

        try:
            return await self._make_request("GET", endpoint, params=params, require_auth=False)
        except:
            # If public search fails, try with auth
            return await self._make_request("GET", endpoint, params=params, require_auth=True)
