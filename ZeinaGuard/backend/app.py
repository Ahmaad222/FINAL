from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager

from auth import auth_bp, AuthService
from routes_sensors import sensors_bp
from routes_dashboard import dashboard_bp
from flask_cors import CORS
from models import db

app = Flask(__name__)
CORS(app)
# ---------------------------
# Database Config
# ---------------------------
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///zeinaguard.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = 'your_super_secret_key'

db.init_app(app)
AuthService(app)

# ---------------------------
# Register Blueprints
# ---------------------------
app.register_blueprint(auth_bp)
app.register_blueprint(sensors_bp)
app.register_blueprint(dashboard_bp)

# ---------------------------
# Create DB + Default Sensor
# ---------------------------
with app.app_context():

    db.create_all()

    from models import Sensor

    sensor = Sensor.query.filter_by(id="sensor1").first()

    if not sensor:
        sensor = Sensor(
            id="sensor1",
            name="Abuelatta Sensor",
            location="My Room",
            is_active=True
        )

        db.session.add(sensor)
        db.session.commit()

        print("✅ Sensor created")

    else:
        print("✅ Sensor already exists")

# ---------------------------
# Run Server
# ---------------------------
if __name__ == "__main__":

    import eventlet
    import eventlet.wsgi

    print("🚀 ZeinaGuard Backend Running...")

    eventlet.wsgi.server(
        eventlet.listen(("0.0.0.0", 5000)),
        app
    )
