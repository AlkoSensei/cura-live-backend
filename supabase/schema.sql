create extension if not exists "pgcrypto";

create table if not exists public.appointments (
    id uuid primary key default gen_random_uuid(),
    patient_name text not null,
    phone_number text not null,
    appointment_date date not null,
    appointment_time time not null,
    status text not null default 'booked' check (status in ('booked', 'cancelled', 'completed')),
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists appointments_active_slot_unique
    on public.appointments (appointment_date, appointment_time)
    where status <> 'cancelled';

create index if not exists appointments_phone_idx
    on public.appointments (phone_number);

create table if not exists public.call_sessions (
    id uuid primary key default gen_random_uuid(),
    room_name text not null unique,
    participant_identity text not null,
    participant_name text,
    phone_number text,
    status text not null default 'active' check (status in ('active', 'ended', 'failed')),
    summary jsonb,
    started_at timestamptz not null default now(),
    ended_at timestamptz,
    created_at timestamptz not null default now()
);

create index if not exists call_sessions_phone_idx
    on public.call_sessions (phone_number);

create table if not exists public.conversation_events (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null references public.call_sessions(id) on delete cascade,
    event_type text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists conversation_events_session_created_idx
    on public.conversation_events (session_id, created_at);
