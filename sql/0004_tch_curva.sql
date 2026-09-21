-- Curva de desarrollo por suerte: serie temporal de índices satelitales del ciclo
-- (lo que el modelo baja y hoy descarta). El tablero la usa para graficar, por
-- suerte, el TCH instantáneo (eje Y) vs edad (eje X): ver en qué mes sube/cae el
-- vigor y correlacionar con fertilización, maduración, riego.
-- Aplicar en el SQL Editor de Supabase (Rio Map).
--
-- tch_inst = TCH del ciclo · EVI(edad)/EVI_pico  → curva que sube y baja como el
-- vigor (interpretación A). Se guardan también los índices crudos por si se quiere
-- cambiar la métrica en el tablero.

create table if not exists tch_curva (
  sec_ste text not null,
  campana text not null,              -- año del ciclo (histórico) o corrida (activo)
  soca int,
  variedad text,
  fecha date not null,               -- fecha de la observación satelital
  edad_meses numeric not null,       -- meses desde el corte (eje X)
  ndvi numeric,
  ndmi numeric,
  evi numeric,
  tch_inst numeric,                  -- TCH instantáneo (eje Y), interpretación A
  tch_ciclo numeric,                 -- TCH del ciclo usado para anclar (real o estimado)
  fuente text default 'dataset',     -- dataset | satelite
  cargado_en timestamptz not null default now(),
  primary key (sec_ste, campana, fecha)
);
create index if not exists tch_curva_suerte on tch_curva (sec_ste, campana, edad_meses);

-- RLS: lectura abierta (la usa el tablero con anon); escritura solo service_role.
alter table tch_curva enable row level security;
create policy tch_curva_sel on tch_curva for select using (true);
