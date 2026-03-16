import requests

class APIClient:
    def __init__(self):
        # ===============================
        # 🔐 Credentials (Matches backend/auth.py)
        # ===============================
        # ملاحظة: تأكد أن 192.168.201.130 هو فعلاً IP الـ VM الحالي
        self.backend_url = "http://192.168.201.130:8000" 

        self.sensor_id = "admin"
        self.secret_key = "admin123"
        self.token = None

    def authenticate_sensor(self):
        """ بيسجل السنسور في الـ Backend وياخد JWT Token """
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
                # لاحظ هنا في الـ auth.py الرد بيرجع جواه object اسمه 'access_token'
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
        """ بيجيب الشبكات الموثوقة من الـ Backend """
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