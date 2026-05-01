from typing import Annotated

from fastapi import APIRouter, Depends

from app.features.appointments.dependencies import get_appointment_service
from app.features.appointments.schemas import (
    Appointment,
    AppointmentCancel,
    AppointmentCreate,
    AppointmentList,
    AppointmentModify,
    AppointmentSlot,
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
