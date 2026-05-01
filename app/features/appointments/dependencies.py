from app.db.supabase import get_supabase
from app.features.appointments.repository import SupabaseAppointmentRepository
from app.features.appointments.service import AppointmentService


def get_appointment_service() -> AppointmentService:
    return AppointmentService(SupabaseAppointmentRepository(get_supabase()))
