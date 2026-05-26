from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(80), nullable=False)
    bot_session = db.Column(db.String(80), nullable=False, default="alestur_ventas")
    name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("phone_number", "bot_session", name="uq_user_phone_bot_session"),
    )

    sessions = db.relationship("Session", back_populates="user")


class Session(db.Model):
    __tablename__ = "sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    start_time = db.Column(db.DateTime, server_default=db.func.now())
    end_time = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    current_state_id = db.Column(db.Integer, db.ForeignKey("states.id"))
    last_message_time = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship("User", back_populates="sessions")
    messages = db.relationship("Message", back_populates="session", cascade="all, delete-orphan")
    context = db.relationship("SessionContext", back_populates="session", cascade="all, delete-orphan")


class State(db.Model):
    __tablename__ = "states"

    id = db.Column(db.Integer, primary_key=True)
    state_name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)

    sessions = db.relationship("Session", backref="state")


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"))
    direction = db.Column(db.String(10), nullable=False)  # 'in' o 'out'
    message_text = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), default="text")
    timestamp = db.Column(db.DateTime, server_default=db.func.now())

    session = db.relationship("Session", back_populates="messages")


class SessionContext(db.Model):
    __tablename__ = "session_context"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"))
    context_key = db.Column(db.String(50), nullable=False)
    context_value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    session = db.relationship("Session", back_populates="context")


class PolicyConsent(db.Model):
    __tablename__ = "policy_consents"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False)
    accepted = db.Column(db.Boolean, nullable=False)  # True = acepto, False = no acepto
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship("User", backref="policy_consents")
    session = db.relationship("Session", backref="policy_consents")
