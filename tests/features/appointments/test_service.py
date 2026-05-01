from datetime import UTC, date, datetime, time, timedelta

import pytest

from app.core.errors import AppError
from app.features.appointments.repository import InMemoryAppointmentRepository
from app.features.appointments.schemas import AppointmentCancel, AppointmentCreate, AppointmentModify, AppointmentStatus
from app.features.appointments.service import AppointmentService


@pytest.fixture
def service() -> AppointmentService:
    return AppointmentService(InMemoryAppointmentRepository())


@pytest.mark.asyncio
async def test_book_appointment(service: AppointmentService) -> None:
    appointment = await service.book_appointment(
        AppointmentCreate(
            patient_name="Asha Rao",
            phone_number="+91 98765 43210",
            appointment_date=date(2026, 5, 5),
            appointment_time=time(10, 0),
        )
    )

    assert appointment.patient_name == "Asha Rao"
    assert appointment.phone_number == "+919876543210"
    assert appointment.status == AppointmentStatus.BOOKED


@pytest.mark.asyncio
async def test_prevents_double_booking(service: AppointmentService) -> None:
    payload = AppointmentCreate(
        patient_name="Asha Rao",
        phone_number="9876543210",
        appointment_date=date(2026, 5, 5),
        appointment_time=time(10, 0),
    )
    await service.book_appointment(payload)

    with pytest.raises(AppError, match="already booked"):
        await service.book_appointment(payload.model_copy(update={"patient_name": "Ravi Kumar"}))


@pytest.mark.asyncio
async def test_rejects_past_appointment_date(service: AppointmentService) -> None:
    with pytest.raises(AppError, match="past dates"):
        await service.book_appointment(
            AppointmentCreate(
                patient_name="Asha Rao",
                phone_number="9876543210",
                appointment_date=datetime.now(UTC).date() - timedelta(days=1),
                appointment_time=time(10, 0),
            )
        )


@pytest.mark.asyncio
async def test_retrieve_cancel_and_modify(service: AppointmentService) -> None:
    appointment = await service.book_appointment(
        AppointmentCreate(
            patient_name="Asha Rao",
            phone_number="9876543210",
            appointment_date=date(2026, 5, 5),
            appointment_time=time(10, 0),
        )
    )

    modified = await service.modify_appointment(
        AppointmentModify(
            appointment_id=appointment.id,
            phone_number="9876543210",
            new_date=date(2026, 5, 6),
            new_time=time(11, 30),
        )
    )
    assert modified.appointment_date == date(2026, 5, 6)
    assert modified.appointment_time == time(11, 30)

    appointments = await service.retrieve_appointments("9876543210")
    assert len(appointments) == 1

    cancelled = await service.cancel_appointment(
        AppointmentCancel(appointment_id=appointment.id, phone_number="9876543210")
    )
    assert cancelled.status == AppointmentStatus.CANCELLED
