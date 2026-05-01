from datetime import date, time
from typing import Protocol
from uuid import UUID, uuid4

from supabase import AsyncClient

from app.features.appointments.schemas import Appointment, AppointmentCreate, AppointmentModify, AppointmentStatus


class AppointmentRepository(Protocol):
    async def create(self, payload: AppointmentCreate) -> Appointment: ...

    async def get_active_by_slot(self, appointment_date: date, appointment_time: time) -> Appointment | None: ...

    async def get_by_id(self, appointment_id: UUID) -> Appointment | None: ...

    async def list_by_phone(self, phone_number: str) -> list[Appointment]: ...

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        status: AppointmentStatus | None,
    ) -> tuple[list[Appointment], int]: ...

    async def cancel(self, appointment_id: UUID) -> Appointment: ...

    async def modify(self, payload: AppointmentModify) -> Appointment: ...


class SupabaseAppointmentRepository:
    table_name = "appointments"

    def __init__(self, client: AsyncClient) -> None:
        self.client = client

    async def create(self, payload: AppointmentCreate) -> Appointment:
        response = await (
            self.client.table(self.table_name)
            .insert(
                {
                    "patient_name": payload.patient_name,
                    "phone_number": payload.phone_number,
                    "appointment_date": payload.appointment_date.isoformat(),
                    "appointment_time": payload.appointment_time.isoformat(),
                    "status": AppointmentStatus.BOOKED.value,
                    "notes": payload.notes,
                }
            )
            .execute()
        )
        return Appointment.model_validate(response.data[0])

    async def get_active_by_slot(self, appointment_date: date, appointment_time: time) -> Appointment | None:
        response = await (
            self.client.table(self.table_name)
            .select("*")
            .eq("appointment_date", appointment_date.isoformat())
            .eq("appointment_time", appointment_time.isoformat())
            .neq("status", AppointmentStatus.CANCELLED.value)
            .limit(1)
            .execute()
        )
        return Appointment.model_validate(response.data[0]) if response.data else None

    async def get_by_id(self, appointment_id: UUID) -> Appointment | None:
        response = await self.client.table(self.table_name).select("*").eq("id", str(appointment_id)).limit(1).execute()
        return Appointment.model_validate(response.data[0]) if response.data else None

    async def list_by_phone(self, phone_number: str) -> list[Appointment]:
        response = await (
            self.client.table(self.table_name)
            .select("*")
            .eq("phone_number", phone_number)
            .order("appointment_date")
            .order("appointment_time")
            .execute()
        )
        return [Appointment.model_validate(row) for row in response.data]

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        status: AppointmentStatus | None,
    ) -> tuple[list[Appointment], int]:
        offset = max(page - 1, 0) * page_size
        query = self.client.table(self.table_name).select("*", count="exact")
        if status is not None:
            query = query.eq("status", status.value)
        trimmed = search.strip() if search else ""
        # LIKE metacharacters stripped; search matches patient name or phone substring.
        safe = trimmed.replace("%", "").replace("_", "").replace(",", "").strip()
        if safe:
            pattern = f"%{safe}%"
            query = query.or_(f"patient_name.ilike.{pattern},phone_number.ilike.{pattern}")
        query = query.order("appointment_date", desc=True).order("appointment_time", desc=True)
        query = query.range(offset, offset + page_size - 1)
        response = await query.execute()
        rows = [Appointment.model_validate(row) for row in response.data]
        total = int(response.count) if response.count is not None else len(rows)
        return rows, total

    async def cancel(self, appointment_id: UUID) -> Appointment:
        response = await (
            self.client.table(self.table_name)
            .update({"status": AppointmentStatus.CANCELLED.value})
            .eq("id", str(appointment_id))
            .execute()
        )
        return Appointment.model_validate(response.data[0])

    async def modify(self, payload: AppointmentModify) -> Appointment:
        response = await (
            self.client.table(self.table_name)
            .update(
                {
                    "appointment_date": payload.new_date.isoformat(),
                    "appointment_time": payload.new_time.isoformat(),
                    "notes": payload.notes,
                    "status": AppointmentStatus.BOOKED.value,
                }
            )
            .eq("id", str(payload.appointment_id))
            .execute()
        )
        return Appointment.model_validate(response.data[0])


class InMemoryAppointmentRepository:
    def __init__(self) -> None:
        self.appointments: dict[UUID, Appointment] = {}

    async def create(self, payload: AppointmentCreate) -> Appointment:
        appointment = Appointment(
            id=uuid4(),
            patient_name=payload.patient_name,
            phone_number=payload.phone_number,
            appointment_date=payload.appointment_date,
            appointment_time=payload.appointment_time,
            status=AppointmentStatus.BOOKED,
            notes=payload.notes,
        )
        self.appointments[appointment.id] = appointment
        return appointment

    async def get_active_by_slot(self, appointment_date: date, appointment_time: time) -> Appointment | None:
        for appointment in self.appointments.values():
            if (
                appointment.appointment_date == appointment_date
                and appointment.appointment_time == appointment_time
                and appointment.status != AppointmentStatus.CANCELLED
            ):
                return appointment
        return None

    async def get_by_id(self, appointment_id: UUID) -> Appointment | None:
        return self.appointments.get(appointment_id)

    async def list_by_phone(self, phone_number: str) -> list[Appointment]:
        return sorted(
            [appointment for appointment in self.appointments.values() if appointment.phone_number == phone_number],
            key=lambda appointment: (appointment.appointment_date, appointment.appointment_time),
        )

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        status: AppointmentStatus | None,
    ) -> tuple[list[Appointment], int]:
        rows = list(self.appointments.values())
        if status is not None:
            rows = [appointment for appointment in rows if appointment.status == status]
        trimmed = search.strip() if search else ""
        if trimmed:
            q = trimmed.lower()
            rows = [
                appointment
                for appointment in rows
                if q in appointment.patient_name.lower() or q in appointment.phone_number.lower()
            ]
        rows.sort(key=lambda appointment: (appointment.appointment_date, appointment.appointment_time), reverse=True)
        total = len(rows)
        offset = max(page - 1, 0) * page_size
        page_rows = rows[offset : offset + page_size]
        return page_rows, total

    async def cancel(self, appointment_id: UUID) -> Appointment:
        appointment = self.appointments[appointment_id].model_copy(update={"status": AppointmentStatus.CANCELLED})
        self.appointments[appointment_id] = appointment
        return appointment

    async def modify(self, payload: AppointmentModify) -> Appointment:
        appointment = self.appointments[payload.appointment_id].model_copy(
            update={
                "appointment_date": payload.new_date,
                "appointment_time": payload.new_time,
                "notes": payload.notes,
                "status": AppointmentStatus.BOOKED,
            }
        )
        self.appointments[payload.appointment_id] = appointment
        return appointment
