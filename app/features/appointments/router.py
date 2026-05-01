from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.features.appointments.dependencies import get_appointment_service
from app.features.appointments.schemas import (
    Appointment,
    AppointmentCancel,
    AppointmentCreate,
    AppointmentList,
    AppointmentModify,
    AppointmentSlot,
    AppointmentStatus,
    PaginatedAppointments,
    UserIdentity,
)
from app.features.appointments.service import AppointmentService

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post("/identify", response_model=UserIdentity)
async def identify_user(phone_number: str, service: Annotated[AppointmentService, Depends(get_appointment_service)]) -> UserIdentity:
    return service.identify_user(phone_number)


@router.get("/slots", response_model=list[AppointmentSlot])
async def fetch_slots(service: Annotated[AppointmentService, Depends(get_appointment_service)]) -> list[AppointmentSlot]:
    return await service.fetch_slots()


@router.post("", response_model=Appointment)
async def book_appointment(
    payload: AppointmentCreate,
    service: Annotated[AppointmentService, Depends(get_appointment_service)],
) -> Appointment:
    return await service.book_appointment(payload)


@router.get("", response_model=AppointmentList)
async def retrieve_appointments(
    phone_number: str,
    service: Annotated[AppointmentService, Depends(get_appointment_service)],
) -> AppointmentList:
    return AppointmentList(appointments=await service.retrieve_appointments(phone_number))


@router.get("/history", response_model=PaginatedAppointments)
async def list_appointment_history(
    service: Annotated[AppointmentService, Depends(get_appointment_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(max_length=120)] = None,
    status: Annotated[AppointmentStatus | None, Query(description="Omit to include every status.")] = None,
) -> PaginatedAppointments:
    """Paginated appointments across all patients; filter by name or phone via `search`."""
    return await service.list_appointments_history(
        page=page,
        page_size=page_size,
        search=search,
        status=status,
    )


@router.delete("/{appointment_id}", response_model=Appointment)
async def cancel_appointment_by_id(
    appointment_id: UUID,
    phone_number: Annotated[str, Query(min_length=7, max_length=20)],
    service: Annotated[AppointmentService, Depends(get_appointment_service)],
) -> Appointment:
    """Cancel an appointment owned by this phone number (REST-friendly alias of POST /cancel)."""
    return await service.cancel_appointment(AppointmentCancel(appointment_id=appointment_id, phone_number=phone_number))


@router.post("/cancel", response_model=Appointment)
async def cancel_appointment(
    payload: AppointmentCancel,
    service: Annotated[AppointmentService, Depends(get_appointment_service)],
) -> Appointment:
    return await service.cancel_appointment(payload)


@router.post("/modify", response_model=Appointment)
async def modify_appointment(
    payload: AppointmentModify,
    service: Annotated[AppointmentService, Depends(get_appointment_service)],
) -> Appointment:
    return await service.modify_appointment(payload)
