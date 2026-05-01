from datetime import UTC, date, datetime, time
from pathlib import Path
from uuid import UUID

from livekit.agents import Agent, function_tool
from livekit.agents.voice import RunContext

from app.features.appointments.schemas import AppointmentCancel, AppointmentCreate, AppointmentModify
from app.features.appointments.service import AppointmentService
from app.features.conversations.schemas import ConversationEventCreate, ConversationEventType
from app.features.conversations.service import ConversationService

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "appointment_agent.md"


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


class AppointmentAgent(Agent):
    def __init__(
        self,
        appointment_service: AppointmentService,
        conversation_service: ConversationService,
        session_id: UUID,
    ) -> None:
        self.appointment_service = appointment_service
        self.conversation_service = conversation_service
        self.session_id = session_id
        super().__init__(instructions=load_system_prompt())

    async def _emit_tool_event(
        self,
        event_type: ConversationEventType,
        tool_name: str,
        message: str,
        data: dict[str, object] | None = None,
    ) -> None:
        await self.conversation_service.add_event(
            ConversationEventCreate(
                session_id=self.session_id,
                event_type=event_type,
                payload={"tool_name": tool_name, "message": message, "data": data or {}},
            )
        )

    async def _end_call(self, reason: str, ctx: RunContext | None = None) -> str:
        if ctx is not None:
            await ctx.wait_for_playout()
        result = await self.appointment_service.end_conversation()
        await self._emit_tool_event(
            ConversationEventType.TOOL_COMPLETED,
            "end_call",
            "Ending call",
            {"reason": reason},
        )
        await self.conversation_service.end_session(self.session_id, {"reason": reason})
        return result.message

    @function_tool
    async def get_today_date(self) -> str:
        """Return today's date so appointment dates can be validated against the current day."""
        today_date = datetime.now(UTC).date()
        today = today_date.isoformat()
        day_of_week = today_date.strftime("%A")
        await self._emit_tool_event(
            ConversationEventType.TOOL_COMPLETED,
            "get_today_date",
            "Fetched today's date",
            {"today": today, "day_of_week": day_of_week},
        )
        return f"Today is {day_of_week}, {today}. Do not book appointments before this date."

    @function_tool
    async def identify_user(self, phone_number: str) -> str:
        """Identify the caller using their phone number as the unique ID."""
        await self._emit_tool_event(ConversationEventType.TOOL_STARTED, "identify_user", "Identifying user")
        identity = self.appointment_service.identify_user(phone_number)
        await self.conversation_service.update_phone_number(self.session_id, identity.phone_number)
        await self._emit_tool_event(
            ConversationEventType.TOOL_COMPLETED,
            "identify_user",
            "User identified",
            identity.model_dump(),
        )
        return f"User identified with phone number {identity.phone_number}."

    @function_tool
    async def fetch_slots(self) -> str:
        """Fetch available appointment slots."""
        await self._emit_tool_event(ConversationEventType.TOOL_STARTED, "fetch_slots", "Fetching available slots")
        slots = await self.appointment_service.fetch_slots()
        data = {"slots": [slot.model_dump(mode="json") for slot in slots]}
        await self._emit_tool_event(ConversationEventType.TOOL_COMPLETED, "fetch_slots", "Available slots fetched", data)
        labels = ", ".join(slot.label for slot in slots)
        return f"Available slots are: {labels}."

    @function_tool
    async def book_appointment(
        self,
        patient_name: str,
        phone_number: str,
        appointment_date: date,
        appointment_time: time,
        notes: str | None = None,
    ) -> str:
        """Book an appointment after collecting name, phone number, date, and time."""
        await self._emit_tool_event(ConversationEventType.TOOL_STARTED, "book_appointment", "Booking appointment")
        appointment = await self.appointment_service.book_appointment(
            AppointmentCreate(
                patient_name=patient_name,
                phone_number=phone_number,
                appointment_date=appointment_date,
                appointment_time=appointment_time,
                notes=notes,
            )
        )
        await self.conversation_service.update_phone_number(self.session_id, appointment.phone_number)
        data = {"appointment": appointment.model_dump(mode="json")}
        await self._emit_tool_event(
            ConversationEventType.TOOL_COMPLETED,
            "book_appointment",
            "Appointment booked",
            data,
        )
        await self._emit_tool_event(
            ConversationEventType.APPOINTMENT_BOOKED,
            "book_appointment",
            "Appointment booked",
            data,
        )
        return f"Appointment confirmed for {appointment.patient_name} on {appointment.appointment_date} at {appointment.appointment_time}."

    @function_tool
    async def retrieve_appointments(self, phone_number: str) -> str:
        """Retrieve past and current appointments for a phone number."""
        await self._emit_tool_event(ConversationEventType.TOOL_STARTED, "retrieve_appointments", "Retrieving appointments")
        appointments = await self.appointment_service.retrieve_appointments(phone_number)
        data = {"appointments": [appointment.model_dump(mode="json") for appointment in appointments]}
        await self._emit_tool_event(ConversationEventType.TOOL_COMPLETED, "retrieve_appointments", "Appointments retrieved", data)
        if not appointments:
            return "I could not find any appointments for this phone number."
        return "Appointments: " + "; ".join(
            f"{appointment.id}: {appointment.appointment_date} at {appointment.appointment_time} ({appointment.status})"
            for appointment in appointments
        )

    @function_tool
    async def cancel_appointment(self, appointment_id: UUID, phone_number: str) -> str:
        """Cancel an existing appointment by appointment ID and phone number."""
        await self._emit_tool_event(ConversationEventType.TOOL_STARTED, "cancel_appointment", "Cancelling appointment")
        appointment = await self.appointment_service.cancel_appointment(
            AppointmentCancel(appointment_id=appointment_id, phone_number=phone_number)
        )
        await self._emit_tool_event(
            ConversationEventType.TOOL_COMPLETED,
            "cancel_appointment",
            "Appointment cancelled",
            {"appointment": appointment.model_dump(mode="json")},
        )
        return f"Appointment on {appointment.appointment_date} at {appointment.appointment_time} has been cancelled."

    @function_tool
    async def modify_appointment(
        self,
        appointment_id: UUID,
        phone_number: str,
        new_date: date,
        new_time: time,
        notes: str | None = None,
    ) -> str:
        """Modify an existing appointment date and time."""
        await self._emit_tool_event(ConversationEventType.TOOL_STARTED, "modify_appointment", "Modifying appointment")
        appointment = await self.appointment_service.modify_appointment(
            AppointmentModify(
                appointment_id=appointment_id,
                phone_number=phone_number,
                new_date=new_date,
                new_time=new_time,
                notes=notes,
            )
        )
        await self._emit_tool_event(
            ConversationEventType.TOOL_COMPLETED,
            "modify_appointment",
            "Appointment modified",
            {"appointment": appointment.model_dump(mode="json")},
        )
        return f"Appointment moved to {appointment.appointment_date} at {appointment.appointment_time}."

    @function_tool
    async def end_call(self, ctx: RunContext) -> str:
        """End the live call when the user is finished, abusive, repeatedly off-topic, or asks to disconnect."""
        return await self._end_call("user_requested_end", ctx)

    @function_tool
    async def end_conversation(self, ctx: RunContext) -> str:
        """Compatibility tool for ending the conversation when the user is done."""
        return await self._end_call("user_requested_end", ctx)
