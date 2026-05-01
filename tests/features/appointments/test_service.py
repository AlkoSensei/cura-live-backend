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


@pytest.mark.asyncio
async def test_list_appointment_history_pagination_and_search(service: AppointmentService) -> None:
    await service.book_appointment(
        AppointmentCreate(
            patient_name="Alpha Patient",
            phone_number="9876543210",
            appointment_date=date(2026, 5, 5),
            appointment_time=time(10, 0),
        )
    )
    await service.book_appointment(
        AppointmentCreate(
            patient_name="Beta Patient",
            phone_number="9876543210",
            appointment_date=date(2026, 5, 7),
            appointment_time=time(15, 0),
        )
    )
    await service.book_appointment(
        AppointmentCreate(
            patient_name="Gamma Guest",
            phone_number="2222222222",
            appointment_date=date(2026, 5, 7),
            appointment_time=time(16, 30),
        )
    )

    page1 = await service.list_appointments_history(
        page=1,
        page_size=1,
        search=None,
        status=None,
    )
    assert page1.total == 3
    assert page1.page == 1
    assert page1.page_size == 1
    assert len(page1.items) == 1
    assert page1.items[0].patient_name == "Gamma Guest"

    beta_only = await service.list_appointments_history(
        page=1,
        page_size=20,
        search="Beta",
        status=None,
    )
    assert beta_only.total == 1
    assert beta_only.items[0].patient_name == "Beta Patient"

    by_phone_digits = await service.list_appointments_history(
        page=1,
        page_size=20,
        search="2222",
        status=None,
    )
    assert by_phone_digits.total == 1
    assert by_phone_digits.items[0].phone_number == "2222222222"

    booked_only = await service.list_appointments_history(
        page=1,
        page_size=20,
        search=None,
        status=AppointmentStatus.BOOKED,
    )
    assert booked_only.total == 3

    await service.cancel_appointment(AppointmentCancel(appointment_id=page1.items[0].id, phone_number="2222222222"))

    cancelled_filter = await service.list_appointments_history(
        page=1,
        page_size=20,
        search=None,
        status=AppointmentStatus.CANCELLED,
    )
    assert cancelled_filter.total == 1
