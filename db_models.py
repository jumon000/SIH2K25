from sqlalchemy import Column, Integer, String, ForeignKey, DateTime,Text,JSON, CheckConstraint, func
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from datetime import datetime

from database import Base



class User(Base):
    """SQLAlchemy User model"""
    __tablename__ = "users"
    
    user_id = Column(Integer, primary_key=True, index=True)
    user_name = Column(String(100), nullable=False)
    administration_id = Column(
        Integer, 
        ForeignKey("administrations.administration_id", ondelete="CASCADE"), 
        nullable=False,
        index=True
    )
    recent_alerts = Column(Text, nullable=True)
    emergency_contacts = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationship
    administration = relationship("Administration", back_populates="users")
    
    # Table constraints
    __table_args__ = (
        CheckConstraint(
            "JSON_LENGTH(emergency_contacts) <= 3 OR emergency_contacts IS NULL",
            name="check_emergency_contacts_limit"
        ),
    )

class Administration(Base):
    __tablename__ = "administrations"

    administration_id = Column(Integer, primary_key=True, index=True)
    administration_name = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    zones = relationship(
        "AdministrationZone",
        back_populates="administration",
        cascade="all, delete-orphan"
    )

    sweet_spots = relationship(
        "SweetSpot",
        back_populates="administration",
        cascade="all, delete-orphan"
    )

    users = relationship(
        "User",
        back_populates="administration",
        cascade="all, delete-orphan"
    )


class AdministrationZone(Base):
    __tablename__ = "administration_zones"

    id = Column(Integer, primary_key=True, index=True)
    administration_id = Column(
        Integer,
        ForeignKey("administrations.administration_id", ondelete="CASCADE"),
        nullable=False
    )

    boundary = Column(Geometry("POLYGON", srid=4326), nullable=True)
    danger_zone = Column(Geometry("MULTIPOLYGON", srid=4326), nullable=True)
    path_zone   = Column(Geometry("MULTILINESTRING", srid=4326), nullable=True) 

    created_at = Column(DateTime, default=datetime.utcnow)

    administration = relationship("Administration", back_populates="zones")


class SweetSpot(Base):
    __tablename__ = "sweet_spots"
    
    sweet_spot_id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(
        Integer, 
        ForeignKey("administrations.administration_id", ondelete="CASCADE"), 
        nullable=False
    )
    sweet_spot_name = Column(String(255), nullable=False)
    sweet_spot_zone = Column(Geometry("POLYGON", srid=4326), nullable=True)  
    created_at = Column(DateTime, default=datetime.utcnow)
    
    administration = relationship("Administration", back_populates="sweet_spots")