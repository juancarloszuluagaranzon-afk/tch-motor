-- Aforo en vivo (feed del modelo para la FUSIÓN). Tabla PROPIA del modelo en el
-- Supabase de Rio Map — NO se usa `aforo_records` del app de Turnos (esa exige
-- user_id y es data de la aplicación). Se carga desde el libro de aforos de
-- Agronomía con scripts/cargar_aforos.py.
-- Aplicar en el SQL Editor de Supabase (Rio Map).
--
-- `aforo_vivo.aforos_vigentes` lee de aquí, por suerte, el aforo más reciente
-- ANTERIOR a la corrida y devuelve el PROMEDIO de los métodos (diámetro + pesos),
-- validado como el mejor. Columnas nombradas suerte/date para calzar con esa
-- función sin cambios.

create table if not exists tch_aforo_vivo (
  suerte text not null,               -- sec_ste
  date date not null,                 -- fecha de EVALUACIÓN del aforo (disciplina temporal)
  tch_diametro numeric,               -- método diámetro
  tch_pesos numeric,                  -- método pesos
  variedad text,
  poblacion numeric,                  -- tallos/m
  diametro numeric,                   -- cm
  fuente text default 'agronomia_xlsx',
  cargado_en timestamptz not null default now(),
  primary key (suerte, date)          -- idempotente: recargar el libro no duplica
);
create index if not exists tch_aforo_vivo_suerte on tch_aforo_vivo (suerte, date desc);

-- RLS: lectura abierta (el modelo lee con anon); escritura solo con service_role.
alter table tch_aforo_vivo enable row level security;
create policy tch_aforo_vivo_sel on tch_aforo_vivo for select using (true);
