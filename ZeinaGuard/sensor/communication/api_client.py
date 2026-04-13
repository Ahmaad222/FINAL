import requests

class APIClient:
    def __init__(self, backend_url=None):
        # التأكد من عدم وجود / في نهاية الرابط
        if backend_url:
            self.backend_url = backend_url.rstrip('/')
        else:
            self.backend_url = "http://localhost:5000" # الافتراضي بتاعنا

        # Credentials (تأكد أنها مطابقة للي في الداتا بيز)
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
            print(f"[API] Attempting login at: {url}")
            response = requests.post(url, json=payload, timeout=5)

            if response.status_code != 200:
                print(f"[API] ❌ Auth Failed (Status: {response.status_code})")
                print(f"[API] Response: {response.text}")
                return None

            data = response.json()
            # تأكد إن الـ key في الباك اند اسمه access_token فعلاً
            self.token = data.get("access_token") or data.get("token")

            if not self.token:
                print("[API] ❌ No token found in response JSON")
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
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }