import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import (create_engine, Column, Integer, String, Date, Time, ForeignKey,
                        UniqueConstraint)
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
from pydantic import BaseModel, Field, PositiveInt
from dotenv import load_dotenv
import datetime

# Load environment variables
load_dotenv()
DB_HOST = os.getenv("POSTGRES_HOST")
DB_PORT = os.getenv("POSTGRES_PORT")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_NAME = os.getenv("POSTGRES_DB")

if not all([DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME]):
    raise RuntimeError("Database environment variables are not fully configured.")

DB_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# SQLAlchemy setup
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# Database Models
class Station(Base):
    __tablename__ = "stations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    code = Column(String(8), nullable=False, unique=True)


class Train(Base):
    __tablename__ = "trains"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    number = Column(String(15), nullable=False, unique=True)
    source_station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    dest_station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    source_station = relationship("Station", foreign_keys=[source_station_id])
    dest_station = relationship("Station", foreign_keys=[dest_station_id])
    # Each train runs on several days (for simplicity assume daily by default)


class TrainSchedule(Base):
    __tablename__ = "train_schedules"
    id = Column(Integer, primary_key=True, index=True)
    train_id = Column(Integer, ForeignKey("trains.id"), nullable=False)
    date = Column(Date, nullable=False, index=True)
    available_seats = Column(Integer, nullable=False)
    total_seats = Column(Integer, nullable=False)
    departure_time = Column(Time, nullable=False)
    arrival_time = Column(Time, nullable=False)
    __table_args__ = (UniqueConstraint("train_id", "date", name="train_date_unique"),)
    train = relationship("Train")


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    train_schedule_id = Column(Integer, ForeignKey("train_schedules.id"), nullable=False)
    passenger_name = Column(String, nullable=False)
    passenger_age = Column(Integer, nullable=False)
    seats_booked = Column(Integer, nullable=False)
    booking_time = Column(Date, nullable=False)
    # Could add: booking status (Confirmed, Cancelled), payment info
    train_schedule = relationship("TrainSchedule")

# Create all tables (Comment out after first run in production!)
Base.metadata.create_all(bind=engine)

# Pydantic Schemas

class HealthResponse(BaseModel):
    status: str = Field(..., description="Service health status")


class StationOut(BaseModel):
    id: int
    name: str
    code: str

    class Config:
        orm_mode = True


class SearchTrainsRequest(BaseModel):
    source_code: str = Field(..., description="Source station code")
    dest_code: str = Field(..., description="Destination station code")
    date: datetime.date = Field(..., description="Travel date (YYYY-MM-DD)")


class TrainSearchResult(BaseModel):
    train_id: int
    train_number: str
    train_name: str
    source_station: str
    dest_station: str
    departure_time: str
    arrival_time: str
    available_seats: int

    class Config:
        orm_mode = True


class BookingRequest(BaseModel):
    train_schedule_id: int = Field(..., description="ID of the train schedule")
    passenger_name: str = Field(..., description="Passenger full name")
    passenger_age: PositiveInt = Field(..., description="Passenger age (years)")
    seats: PositiveInt = Field(..., description="Number of seats to book")


class BookingResponse(BaseModel):
    booking_id: int
    train_schedule_id: int
    passenger_name: str
    passenger_age: int
    seats_booked: int
    booking_time: datetime.date


class TrainScheduleDetail(BaseModel):
    schedule_id: int
    train_id: int
    train_name: str
    train_number: str
    date: datetime.date
    departure_time: str
    arrival_time: str
    available_seats: int
    total_seats: int

    class Config:
        orm_mode = True


# DB Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

openapi_tags = [
    {"name": "Health", "description": "Service health status route"},
    {"name": "Trains", "description": "Train search & details"},
    {"name": "Schedules", "description": "Train schedule and availability"},
    {"name": "Bookings", "description": "Ticket booking operations"},
    {"name": "Stations", "description": "Station information and look-up"}
]

app = FastAPI(
    title="Railway Ticket Booking API",
    description="Backend for train search and ticket booking, supporting scheduling, booking, and station look-ups.",
    version="1.0.0",
    openapi_tags=openapi_tags
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# PUBLIC_INTERFACE
@app.get("/", response_model=HealthResponse, tags=["Health"])
def health_check():
    """Health check endpoint."""
    return {"status": "Healthy"}


# PUBLIC_INTERFACE
@app.get("/stations", response_model=List[StationOut], tags=["Stations"], summary="List all stations")
def list_stations(db: Session = Depends(get_db)):
    """
    Retrieve a list of all train stations.
    """
    stations = db.query(Station).all()
    return stations


# PUBLIC_INTERFACE
@app.post("/trains/search", response_model=List[TrainSearchResult], tags=["Trains"],
    summary="Search for available trains between two stations")
def search_trains(request: SearchTrainsRequest, db: Session = Depends(get_db)):
    """
    Search for available trains between two stations on a given date.
    Verifies station codes exist and returns all trains available for the specified route and date.
    """
    src_station = db.query(Station).filter(Station.code == request.source_code.upper()).first()
    dest_station = db.query(Station).filter(Station.code == request.dest_code.upper()).first()
    if not src_station or not dest_station:
        raise HTTPException(status_code=404, detail="Invalid source or destination station code")
    # Find trains with route
    trains = db.query(Train).filter(
        Train.source_station_id == src_station.id,
        Train.dest_station_id == dest_station.id
    ).all()
    results = []
    for train in trains:
        schedule = db.query(TrainSchedule).filter(
            TrainSchedule.train_id == train.id,
            TrainSchedule.date == request.date
        ).first()
        if schedule:
            results.append(
                TrainSearchResult(
                    train_id=train.id,
                    train_number=train.number,
                    train_name=train.name,
                    source_station=src_station.code,
                    dest_station=dest_station.code,
                    departure_time=schedule.departure_time.strftime("%H:%M"),
                    arrival_time=schedule.arrival_time.strftime("%H:%M"),
                    available_seats=schedule.available_seats
                )
            )
    return results


# PUBLIC_INTERFACE
@app.get("/trains/{train_id}/schedules", response_model=List[TrainScheduleDetail], tags=["Schedules"],
    summary="View schedules for a given train")
def get_train_schedules(
    train_id: int,
    date: Optional[datetime.date] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    """
    View the list of schedules for a specific train.
    Optionally filter by travel date.
    """
    query = db.query(TrainSchedule).filter(TrainSchedule.train_id == train_id)
    if date:
        query = query.filter(TrainSchedule.date == date)
    schedules = query.all()
    results = [
        TrainScheduleDetail(
            schedule_id=s.id,
            train_id=train_id,
            train_name=s.train.name,
            train_number=s.train.number,
            date=s.date,
            departure_time=s.departure_time.strftime("%H:%M"),
            arrival_time=s.arrival_time.strftime("%H:%M"),
            available_seats=s.available_seats,
            total_seats=s.total_seats
        )
        for s in schedules
    ]
    return results


# PUBLIC_INTERFACE
@app.get("/schedules/{schedule_id}", response_model=TrainScheduleDetail, tags=["Schedules"],
    summary="View detail of a train schedule")
def get_schedule_detail(schedule_id: int, db: Session = Depends(get_db)):
    """
    Get detail about a specific train schedule by its ID.
    """
    schedule = db.query(TrainSchedule).filter(TrainSchedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Train schedule not found")
    return TrainScheduleDetail(
        schedule_id=schedule.id,
        train_id=schedule.train_id,
        train_name=schedule.train.name,
        train_number=schedule.train.number,
        date=schedule.date,
        departure_time=schedule.departure_time.strftime("%H:%M"),
        arrival_time=schedule.arrival_time.strftime("%H:%M"),
        available_seats=schedule.available_seats,
        total_seats=schedule.total_seats
    )


# PUBLIC_INTERFACE
@app.post("/bookings", response_model=BookingResponse, tags=["Bookings"],
    summary="Book railway tickets", status_code=status.HTTP_201_CREATED)
def book_ticket(req: BookingRequest, db: Session = Depends(get_db)):
    """
    Book tickets for a specified train schedule.
    Validates ticket availability; decrements seat count transactionally on booking.
    """
    schedule: TrainSchedule = db.query(TrainSchedule).filter(TrainSchedule.id == req.train_schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Train schedule not found")

    if req.seats > schedule.available_seats:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough available seats. Only {schedule.available_seats} available."
        )
    # Basic business validation for age (no infants or unreasonable ages)
    if req.passenger_age < 1 or req.passenger_age > 120:
        raise HTTPException(status_code=400, detail="Passenger age must be between 1 and 120 years.")

    # Transaction: Book and decrement available_seats
    try:
        # Could use a database-level transaction for concurrency safety
        schedule.available_seats -= req.seats
        booking = Booking(
            train_schedule_id=req.train_schedule_id,
            passenger_name=req.passenger_name,
            passenger_age=req.passenger_age,
            seats_booked=req.seats,
            booking_time=datetime.date.today()
        )
        db.add(booking)
        db.commit()
        db.refresh(booking)
        db.refresh(schedule)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Booking failed due to server error.")

    return BookingResponse(
        booking_id=booking.id,
        train_schedule_id=booking.train_schedule_id,
        passenger_name=booking.passenger_name,
        passenger_age=booking.passenger_age,
        seats_booked=booking.seats_booked,
        booking_time=booking.booking_time
    )


# PUBLIC_INTERFACE
@app.get("/bookings/{booking_id}", response_model=BookingResponse, tags=["Bookings"],
    summary="Retrieve a booking by booking ID")
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    """
    Retrieve details of a previously-created booking by its ID.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return BookingResponse(
        booking_id=booking.id,
        train_schedule_id=booking.train_schedule_id,
        passenger_name=booking.passenger_name,
        passenger_age=booking.passenger_age,
        seats_booked=booking.seats_booked,
        booking_time=booking.booking_time
    )
