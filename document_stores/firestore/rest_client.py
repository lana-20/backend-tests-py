"""Call the Firestore emulator's REST API as a specific end user, so rules apply.

The Python server SDK (google-cloud-firestore) is an admin client: it bypasses security
rules entirely, in production and in the emulator. Rules only apply to end-user
requests, which carry a Firebase Auth ID token. The emulator accepts unsigned tokens,
the same trick Firebase's own @firebase/rules-unit-testing library uses.
"""

import base64
import json
import time
from typing import Any

import requests


def _b64(data: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def unsigned_id_token(project: str, uid: str) -> str:
    """A fake Firebase ID token for `uid`. Only an emulator accepts it."""
    now = int(time.time())
    header = {"alg": "none", "typ": "JWT"}
    payload = {
        "iss": f"https://securetoken.google.com/{project}",
        "aud": project,
        "iat": now,
        "exp": now + 3600,
        "auth_time": now,
        "sub": uid,
        "user_id": uid,
        "firebase": {"sign_in_provider": "custom", "identities": {}},
    }
    return f"{_b64(header)}.{_b64(payload)}."  # empty signature


class EmulatorRestClient:
    def __init__(self, emulator_host: str, project: str) -> None:
        self.base = f"http://{emulator_host}"
        self.project = project
        self.documents = f"{self.base}/v1/projects/{project}/databases/(default)/documents"

    def load_rules(self, rules: str) -> None:
        """Replace the security rules for this project (an emulator-only endpoint)."""
        response = requests.put(
            f"{self.base}/emulator/v1/projects/{self.project}:securityRules",
            json={"rules": {"files": [{"name": "firestore.rules", "content": rules}]}},
            timeout=10,
        )
        response.raise_for_status()

    def _headers(self, uid: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {unsigned_id_token(self.project, uid)}"} if uid else {}

    def get(self, path: str, uid: str | None) -> requests.Response:
        return requests.get(f"{self.documents}/{path}", headers=self._headers(uid), timeout=10)

    def create(self, collection: str, doc_id: str, fields: dict[str, str], uid: str | None) -> requests.Response:
        body = {"fields": {key: {"stringValue": value} for key, value in fields.items()}}
        return requests.post(
            f"{self.documents}/{collection}",
            params={"documentId": doc_id},
            json=body,
            headers=self._headers(uid),
            timeout=10,
        )
