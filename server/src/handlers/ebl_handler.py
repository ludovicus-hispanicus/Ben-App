"""
eBL (Electronic Babylonian Literature) API Handler

Handles all communication with the eBL API including:
- Auth0 authentication
- ATF validation
- Fragment export/import
"""

import logging
import os
import json
import httpx
from typing import Optional, Dict, Any
from pathlib import Path


class EblHandler:
    """Handler for eBL API integration."""

    # Configuration file path
    CONFIG_FILE = Path(__file__).parent.parent / "ebl_config.json"

    def __init__(self):
        self.api_url: Optional[str] = None
        self.auth0_domain: Optional[str] = None
        self.auth0_client_id: Optional[str] = None
        self.auth0_client_secret: Optional[str] = None
        self.auth0_audience: Optional[str] = None
        self.access_token: Optional[str] = None
        self.token_expires_at: float = 0

        # Load configuration from file or environment
        self._load_config()

    def _load_config(self):
        """Load configuration from file or environment variables."""
        # Try loading from config file first
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    self.api_url = config.get('api_url')
                    self.auth0_domain = config.get('auth0_domain')
                    self.auth0_client_id = config.get('auth0_client_id')
                    self.auth0_client_secret = config.get('auth0_client_secret')
                    self.auth0_audience = config.get('auth0_audience')
                    logging.info("eBL config loaded from file")
                    return
            except Exception as e:
                logging.warning(f"Failed to load eBL config from file: {e}")

        # Fall back to environment variables
        self.api_url = os.getenv('EBL_API_URL', 'https://www.ebl.lmu.de/api')
        self.auth0_domain = os.getenv('EBL_AUTH0_DOMAIN')
        self.auth0_client_id = os.getenv('EBL_AUTH0_CLIENT_ID')
        self.auth0_client_secret = os.getenv('EBL_AUTH0_CLIENT_SECRET')
        self.auth0_audience = os.getenv('EBL_AUTH0_AUDIENCE')

    def _save_config(self):
        """Save configuration to file."""
        config = {
            'api_url': self.api_url,
            'auth0_domain': self.auth0_domain,
            'auth0_client_id': self.auth0_client_id,
            'auth0_client_secret': self.auth0_client_secret,
            'auth0_audience': self.auth0_audience
        }
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
            logging.info("eBL config saved to file")
        except Exception as e:
            logging.error(f"Failed to save eBL config: {e}")

    @property
    def is_configured(self) -> bool:
        """Check if eBL API is configured."""
        return bool(
            self.api_url and
            self.auth0_domain and
            self.auth0_client_id and
            self.auth0_client_secret and
            self.auth0_audience
        )

    async def configure(
        self,
        api_url: str,
        auth0_domain: str,
        auth0_client_id: str,
        auth0_client_secret: str,
        auth0_audience: str
    ):
        """Configure eBL API credentials."""
        self.api_url = api_url
        self.auth0_domain = auth0_domain
        self.auth0_client_id = auth0_client_id
        self.auth0_client_secret = auth0_client_secret
        self.auth0_audience = auth0_audience
        self.access_token = None  # Clear cached token
        self.token_expires_at = 0

        # Test the configuration
        await self._get_access_token()

        # Save if successful
        self._save_config()

    async def _get_access_token(self) -> str:
        """Get an access token from Auth0."""
        import time

        # Return cached token if still valid
        if self.access_token and time.time() < self.token_expires_at - 60:
            return self.access_token

        if not self.is_configured:
            raise ValueError("eBL API is not configured. Please configure credentials first.")

        token_url = f"https://{self.auth0_domain}/oauth/token"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                json={
                    "client_id": self.auth0_client_id,
                    "client_secret": self.auth0_client_secret,
                    "audience": self.auth0_audience,
                    "grant_type": "client_credentials"
                },
                headers={"Content-Type": "application/json"}
            )

            if response.status_code != 200:
                error_msg = f"Auth0 authentication failed: {response.text}"
                logging.error(error_msg)
                raise ValueError(error_msg)

            data = response.json()
            self.access_token = data["access_token"]
            self.token_expires_at = time.time() + data.get("expires_in", 86400)

            return self.access_token

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        require_auth: bool = True
    ) -> Dict[str, Any]:
        """Make a request to the eBL API."""
        url = f"{self.api_url}{endpoint}"

        headers = {"Content-Type": "application/json"}
        if require_auth:
            token = await self._get_access_token()
            headers["Authorization"] = f"Bearer {token}"

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

            if response.status_code >= 400:
                error_msg = f"eBL API error ({response.status_code}): {response.text}"
                logging.error(error_msg)
                raise ValueError(error_msg)

            if response.text:
                return response.json()
            return {}

    async def get_status(self) -> Dict[str, Any]:
        """Get eBL connection status."""
        result = {
            "configured": self.is_configured,
            "connected": False,
            "api_url": self.api_url,
            "error": None
        }

        if not self.is_configured:
            result["error"] = "eBL API credentials not configured"
            return result

        try:
            # Try to get a token to verify connection
            await self._get_access_token()
            result["connected"] = True
        except Exception as e:
            result["error"] = str(e)

        return result

    async def validate_atf(
        self,
        atf_text: str,
        fragment_number: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validate ATF text against eBL's parser.

        Note: This is a local validation that mimics eBL's validation.
        For full validation, the text would need to be sent to eBL.
        """
        errors = []
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
                        errors.append(f"Line {i}: Invalid @-line: {line}")

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
                        errors.append(f"Line {i}: Unmatched brackets '{open_b}' and '{close_b}'")

                # Check for line number format (should be like "1." or "1'.")
                import re
                if not re.match(r"^\d+'?\.\s", line) and not line.startswith('$') and not line.startswith('#'):
                    # Might be missing line number, but not always required
                    pass

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "parsed_lines": parsed_lines
        }

    async def export_to_ebl(
        self,
        fragment_number: str,
        atf_text: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Export transliteration to eBL.

        This updates the fragment with the new ATF content.
        """
        if not self.is_configured:
            raise ValueError("eBL API is not configured")

        # First validate the ATF
        validation = await self.validate_atf(atf_text, fragment_number)
        if not validation["valid"]:
            return {
                "success": False,
                "message": f"ATF validation failed: {', '.join(validation['errors'])}",
                "fragment_url": None
            }

        try:
            # eBL API endpoint for updating fragment transliteration
            # The exact endpoint may vary - this is based on typical REST patterns
            endpoint = f"/fragments/{fragment_number}/transliteration"

            # Prepare the payload
            payload = {
                "transliteration": atf_text
            }
            if notes:
                payload["notes"] = notes

            await self._make_request("POST", endpoint, data=payload)

            fragment_url = f"https://www.ebl.lmu.de/fragmentarium/{fragment_number}"

            return {
                "success": True,
                "message": f"Successfully exported to eBL",
                "fragment_url": fragment_url
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Export failed: {str(e)}",
                "fragment_url": None
            }

    async def get_fragment(self, fragment_number: str) -> Dict[str, Any]:
        """Get a fragment from eBL."""
        if not self.is_configured:
            raise ValueError("eBL API is not configured")

        endpoint = f"/fragments/{fragment_number}"
        return await self._make_request("GET", endpoint)

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
