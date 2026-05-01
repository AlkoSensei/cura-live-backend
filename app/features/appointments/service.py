import re
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from fastapi import status

from app.core.errors import AppError
from app.features.appointments.repository import AppointmentRepository
from app.features.appointments.schemas import (
    Appointment,
    AppointmentCancel,
    AppointmentCreate,
    AppointmentModify,
    AppointmentSlot,
    AppointmentStatus,
    ToolResult,
    UserIdentity,
)


def normalize_phone_number(phone_number: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", phone_number.strip())
    if cleaned.startswith("+"):
        prefix = "+"
        digits = re.sub(r"\D", "", cleaned)
        normalized = f"{prefix}{digits}"
    else:
        digits = re.sub(r"\D", "", cleaned)
        normalized = digits
    if len(digits) < 7:
        raise AppError("Please provide a valid phone number.")
    return normalized


class SlotProvider:
    clinic_slot_times: tuple[time, ...] = (
        time(hour=10),
        time(hour=11, minute=30),
        time(hour=15),
        time(hour=16, minute=30),
    )
    lookahead_days: int = 7

    def list_slots(self) -> list[AppointmentSlot]:
        today = datetime.now(UTC).date()
        slots: list[AppointmentSlot] = []
        for offset in range(0, self.lookahead_days + 1):
            slot_date = today + timedelta(days=offset)
            if slot_date.weekday() >= 5:
                continue
            for slot_time in self.clinic_slot_times:
                slots.append(
                    AppointmentSlot(
                        appointment_date=slot_date,
                        appointment_time=slot_time,
                        label=f"{slot_date.strftime('%A')}, {slot_date.isoformat()} at {slot_time.strftime('%I:%M %p')}",
                    )
                )
        return slots

    def is_supported_slot(self, appointment_date: date, appointment_time: time) -> bool:
        today = datetime.now(UTC).date()
        max_date = today + timedelta(days=self.lookahead_days)
        return (
            today <= appointment_date <= max_date
            and appointment_date.weekday() < 5
            and appointment_time.replace(second=0, microsecond=0) in self.clinic_slot_times
        )


class AppointmentService:
    def __init__(self, repository: AppointmentRepository, slot_provider: SlotProvider | None = None) -> None:
        self.repository = repository
        self.slot_provider = slot_provider or SlotProvider()

    def identify_user(self, phone_number: str) -> UserIdentity:
        return UserIdentity(phone_number=normalize_phone_number(phone_number))

    async def fetch_slots(self) -> list[AppointmentSlot]:
        available_slots: list[AppointmentSlot] = []
        for slot in self.slot_provider.list_slots():
            existing = await self.repository.get_active_by_slot(slot.appointment_date, slot.appointment_time)
            if existing is None:
                available_slots.append(slot)
        return available_slots

    async def book_appointment(self, payload: AppointmentCreate) -> Appointment:
        normalized_payload = payload.model_copy(update={"phone_number": normalize_phone_number(payload.phone_number)})
        self._ensure_bookable_slot(normalized_payload.appointment_date, normalized_payload.appointment_time)
        await self._ensure_slot_is_available(normalized_payload.appointment_date, normalized_payload.appointment_time)
        return await self.repository.create(normalized_payload)

    async def retrieve_appointments(self, phone_number: str) -> list[Appointment]:
        return await self.repository.list_by_phone(normalize_phone_number(phone_number))

    async def cancel_appointment(self, payload: AppointmentCancel) -> Appointment:
        appointment = await self._get_owned_appointment(payload.appointment_id, payload.phone_number)
        if appointment.status == AppointmentStatus.CANCELLED:
            raise AppError("This appointment is already cancelled.")
        return await self.repository.cancel(payload.appointment_id)

    async def modify_appointment(self, payload: AppointmentModify) -> Appointment:
        appointment = await self._get_owned_appointment(payload.appointment_id, payload.phone_number)
        if appointment.status == AppointmentStatus.CANCELLED:
            raise AppError("Cancelled appointments cannot be modified.")
        self._ensure_bookable_slot(payload.new_date, payload.new_time)
        existing = await self.repository.get_active_by_slot(payload.new_date, payload.new_time)
        if existing is not None and existing.id != payload.appointment_id:
            raise AppError("That slot is already booked. Please choose another available slot.")
        return await self.repository.modify(payload)

    async def end_conversation(self) -> ToolResult:
        return ToolResult(success=True, message="Thanks for calling. The conversation has ended.")

    async def _get_owned_appointment(self, appointment_id: UUID, phone_number: str) -> Appointment:
        appointment = await self.repository.get_by_id(appointment_id)
        if appointment is None:
            raise AppError("Appointment not found.", status.HTTP_404_NOT_FOUND)
        if appointment.phone_number != normalize_phone_number(phone_number):
            raise AppError("Appointment does not belong to this phone number.", status.HTTP_403_FORBIDDEN)
        return appointment

    def _ensure_bookable_slot(self, appointment_date: date, appointment_time: time) -> None:
        today = datetime.now(UTC).date()
        if appointment_date < today:
            raise AppError("Appointments cannot be booked for past dates.")
        if not self.slot_provider.is_supported_slot(appointment_date, appointment_time):
            raise AppError("That date and time is outside available clinic slots. Please choose from fetched slots.")

    async def _ensure_slot_is_available(self, appointment_date: date, appointment_time: time) -> None:
        existing = await self.repository.get_active_by_slot(appointment_date, appointment_time)
        if existing is not None:
            raise AppError("That slot is already booked. Please choose another available slot.")
