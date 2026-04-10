import requests


class APIClient:
    def __init__(self):

        # Backend URL
        self.backend_url = "http://192.168.201.131:8000"

        # Credentials
        self.username = "admin"
        self.password = "admin123"

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
            print(f"[API] Authenticating with {url} ...")

            response = requests.post(url, json=payload, timeout=5)

            if response.status_code != 200:
                print(f"[API] ❌ Auth Failed: {response.status_code}")
                print(response.text)
                return None

            data = response.json()

            self.token = data.get("access_token")

            if not self.token:
                print("[API] ❌ No token received")
                return None

            print("[API] ✅ Authentication Successful!")

            return self.token

        except requests.exceptions.RequestException as e:
            print(f"[API] ❌ Connection Error: {e}")
            return None

    def get_headers(self):

        if not self.token:
            return {}

        return {
            "Authorization": f"Bearer {self.token}"
        }