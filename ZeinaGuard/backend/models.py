from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String, Integer, Boolean, DateTime
from sqlalchemy.orm import relationship

db = SQLAlchemy()

# --------------------- Sensor ---------------------
class Sensor(db.Model):
    __tablename__ = 'sensors'
    
    id = db.Column(String(50), primary_key=True)
    name = db.Column(String(255), nullable=False)
    hostname = db.Column(String(255), unique=True)
    ip_address = db.Column(String(45))
    mac_address = db.Column(String(17))
    location = db.Column(String(255))
    is_active = db.Column(Boolean, default=True)
    firmware_version = db.Column(String(50))
    created_at = db.Column(DateTime, default=datetime.utcnow)
    updated_at = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # هنا نخلي العلاقة string reference بدون مشاكل ترتيب
    health_records = relationship('SensorHealth', back_populates='sensor', cascade='all, delete-orphan')


# --------------------- SensorHealth ---------------------
class SensorHealth(db.Model):
    __tablename__ = 'sensor_health'
    
    id = db.Column(Integer, primary_key=True)
    sensor_id = db.Column(String(50), db.ForeignKey('sensors.id', ondelete='CASCADE'), nullable=False)
    status = db.Column(String(50), default='online')
    signal_strength = db.Column(Integer)
    cpu_usage = db.Column(Integer)
    memory_usage = db.Column(Integer)
    uptime = db.Column(Integer)
    last_heartbeat = db.Column(DateTime)
    created_at = db.Column(DateTime, default=datetime.utcnow)

    sensor = relationship('Sensor', back_populates='health_records')
