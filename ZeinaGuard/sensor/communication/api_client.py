import requests
import os

class APIClient:
    def __init__(self, backend_url=None):

        # Backend URL - Use provided URL or fallback to internal default
        self.backend_url = backend_url or "http://flask-backend:5000"

        # Credentials from Environment Variables or Defaults
        self.username = os.getenv("SENSOR_USERNAME", "admin")
        self.password = os.getenv("SENSOR_PASSWORD", "admin123")

        if not self.username or not self.password:
            print("[API] ⚠️ Warning: Missing SENSOR_USERNAME or SENSOR_PASSWORD!")

        self.token = None

    def authenticate_sensor(self):
        """
        Authenticate with backend and receive JWT token
        """

        url = f"{self.backend_url}/api/auth/login"

        payload = {
            "username": self.username,
            "password": self.password
        }

        try:
            print(f"[API] 🔑 Attempting authentication with {url} ...")

            response = requests.post(url, json=payload, timeout=5)

            if response.status_code == 200:
                data = response.json()
                self.token = data.get("access_token")

                if self.token:
                    print(f"[API] ✅ Login Successful! Sensor authenticated as: {self.username}")
                    return self.token
                else:
                    print("[API] ❌ Auth Failed: No access token in response.")
                    return None
            
            elif response.status_code == 401:
                print(f"[API] ❌ Login Failed: Invalid credentials for user '{self.username}'")
                return None
            else:
                print(f"[API] ❌ Auth Error: Received status code {response.status_code}")
                print(f"[API] Response: {response.text}")
                return None

        except requests.exceptions.RequestException as e:
            print(f"[API] ❌ Connection Error while authenticating: {e}")
            return None

    def get_headers(self):

        if not self.token:
            return {}

        return {
            "Authorization": f"Bearer {self.token}"
        }