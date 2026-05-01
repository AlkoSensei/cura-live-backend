from datetime import date, datetime, time
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class AppointmentStatus(StrEnum):
    BOOKED = "booked"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class UserIdentity(BaseModel):
    phone_number: str


class AppointmentSlot(BaseModel):
    appointment_date: date
    appointment_time: time
    label: str
    available: bool = True


class AppointmentCreate(BaseModel):
    patient_name: str = Field(min_length=1, max_length=120)
    phone_number: str = Field(min_length=7, max_length=20)
    appointment_date: date
    appointment_time: time
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("phone_number")
    @classmethod
    def phone_has_digits(cls, value: str) -> str:
        if sum(char.isdigit() for char in value) < 7:
            raise ValueError("phone_number must include at least 7 digits")
        return value


class AppointmentModify(BaseModel):
    appointment_id: UUID
    phone_number: str = Field(min_length=7, max_length=20)
    new_date: date
    new_time: time
    notes: str | None = Field(default=None, max_length=500)


class AppointmentCancel(BaseModel):
    appointment_id: UUID
    phone_number: str = Field(min_length=7, max_length=20)


class Appointment(BaseModel):
    id: UUID
    patient_name: str
    phone_number: str
    appointment_date: date
    appointment_time: time
    status: AppointmentStatus
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AppointmentList(BaseModel):
    appointments: list[Appointment]


class PaginatedAppointments(BaseModel):
    """Paged list for appointment history UI."""

    items: list[Appointment]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class ToolResult(BaseModel):
    success: bool
    message: str
