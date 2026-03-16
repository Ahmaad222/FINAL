#api_client.py
import requests


class APIClient:

    def __init__(self):

        # ===============================
        # 🔐 Credentials (For Testing)
        # ===============================

        self.backend_url = "http://192.168.201.130:5000"  # عدل الـ IP هنا لو لازم

        self.sensor_id = "admin"
        self.secret_key = "admin123"

        self.token = None


    def authenticate_sensor(self):
        """
        بيسجل السنسور في الـ Backend وياخد JWT Token
        """

        url = f"{self.backend_url}/api/auth/login"

        payload = {
            "username": self.sensor_id,
            "password": self.secret_key
        }

        try:
            print(f"[API] Authenticating with {url} ...")

            response = requests.post(url, json=payload, timeout=5)

            if response.status_code == 200:

                data = response.json()
                self.token = data.get("access_token")

                if self.token:
                    print("[API] ✅ Authentication Successful!")
                    return self.token
                else:
                    print("[API] ❌ Token not found in response")
                    return None

            else:
                print(f"[API] ❌ Auth Failed - Status: {response.status_code}")
                print(f"[API] Response: {response.text}")
                return None

        except Exception as e:
            print(f"[API] ❌ Connection Error: {e}")
            return None


    def get_trusted_aps(self):
        """
        بيجيب الشبكات الموثوقة من الـ Backend
        """

        if not self.token:
            print("[API] ❌ No token available")
            return {}

        url = f"{self.backend_url}/api/sensors/trusted_aps"

        headers = {
            "Authorization": f"Bearer {self.token}"
        }

        try:
            response = requests.get(url, headers=headers, timeout=5)

            if response.status_code == 200:
                print("[API] ✅ Trusted APs fetched successfully")
                return response.json()

            else:
                print(f"[API] ❌ Failed to fetch trusted APs - {response.status_code}")
                return {}

        except Exception as e:
            print(f"[API] ❌ Error fetching trusted APs: {e}")
            return {}
