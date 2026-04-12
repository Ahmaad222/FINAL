"""
API Routes Registration Hub for ZeinaGuard Pro
Imports and registers all modularized blueprints
"""

def register_blueprints(app):
    """
    Import and register all API blueprints
    Each module handles its own business logic and DB interaction
    """
    # Import specialized blueprints
    from routes_auth import auth_bp, users_bp
    from routes_threats import threats_bp
    from routes_sensors import sensors_bp
    from routes_alerts import alerts_bp
    from routes_analytics import analytics_bp
    from routes_dashboard import dashboard_bp
    from routes_topology import topology_bp
    from routes_incidents import incidents_bp
    from notification_routes import notifications_bp

    # Register blueprints with the app
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(threats_bp)
    app.register_blueprint(sensors_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(topology_bp)
    app.register_blueprint(incidents_bp)
    app.register_blueprint(notifications_bp)
    
    print(f"[API] ✓ Registered {len(app.blueprints)} blueprints")
