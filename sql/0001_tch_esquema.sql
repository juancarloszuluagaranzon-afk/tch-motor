-- Producto "Estimador TCH" — esquema en el Supabase de Rio Map.
-- Tablas con prefijo tch_ para no chocar con las de Rio Map.
-- Aplicar en el SQL Editor de Supabase (DDL; no pasa por PostgREST).

-- Diccionario de variedades: código interno del ZQM (V##) → nombre Cenicaña.
create table if not exists tch_var_map (
  codigo text primary key,          -- V82
  nombre text not null              -- CC 01-1940
);

-- Aforo sintético: estadísticas históricas de tallos por variedad × soca.
-- soca = -1 representa el agregado de la variedad (respaldo cuando no hay
-- suficientes aforos de esa soca puntual).
create table if not exists tch_aforo_sintetico (
  variedad text not null,
  soca int not null default -1,
  poblacion numeric,                -- tallos/m
  peso numeric,                     -- kg/tallo
  diametro numeric,                 -- cm
  aforo_sint numeric,               -- TCH mediano calculado
  n int,                            -- nº de aforos que respaldan la fila
  actualizado_en timestamptz not null default now(),
  primary key (variedad, soca)
);

-- Estimados: una fila por (suerte, corrida). Histórico auditable de cómo
-- evolucionó el estimado de cada suerte mes a mes.
create table if not exists tch_estimado (
  id bigint generated always as identity primary key,
  sec_ste text not null,
  planta text not null,             -- riopaila | castilla
  fecha_corrida date not null,      -- cuándo se produjo el estimado
  fecha_corte_prevista date,
  edad_meses numeric,
  soca int,
  variedad text,                    -- nombre Cenicaña
  tch_estimado numeric not null,
  tch_std numeric,                  -- banda de incertidumbre (± entre árboles)
  ton_estimadas numeric,
  area_ha numeric,
  modo text,                        -- 'motor' (sin aforo) | 'fusion' (con aforo)
  factor_recal numeric,             -- factor de recalibración aplicado
  modelo_version text,
  creado_en timestamptz not null default now(),
  unique (sec_ste, fecha_corrida)   -- idempotente: re-correr un día no duplica
);
create index if not exists tch_estimado_fecha on tch_estimado (fecha_corrida);
create index if not exists tch_estimado_suerte on tch_estimado (sec_ste);

-- RLS: lectura abierta (datos internos, alimentan el tablero); la escritura
-- solo con service_role (el job del motor) — sin políticas de insert/update.
alter table tch_var_map enable row level security;
alter table tch_aforo_sintetico enable row level security;
alter table tch_estimado enable row level security;

create policy tch_var_map_sel on tch_var_map for select using (true);
create policy tch_aforo_sel on tch_aforo_sintetico for select using (true);
create policy tch_estimado_sel on tch_estimado for select using (true);
