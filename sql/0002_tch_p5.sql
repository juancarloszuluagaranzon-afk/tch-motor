-- P5 — auto-recalibración. Cierra el lazo: cortes reales cerrados → factor
-- aprendido por planta/campaña → lo lee el job mensual (reemplaza el 0.981/0.914
-- fijo) y alimenta el panel estimado-vs-real del tablero.
-- Aplicar en el SQL Editor de Supabase (Rio Map).

-- Cortes YA COSECHADOS de la campaña. Fuente: ZQM (columna TCH = TC-Total/área),
-- se refresca a medida que el ingenio cierra cortes. Una fila por suerte×campaña.
create table if not exists tch_real (
  sec_ste text not null,
  campana text not null,              -- año de cosecha, p.ej. '2026'
  planta text,                        -- riopaila | castilla
  corte int,                          -- número de soca cosechada
  variedad text,                      -- nombre Cenicaña al cosechar
  area_ha numeric,
  tc_total numeric,                   -- toneladas totales del corte
  tch_real numeric not null,          -- TC-Total / área (la etiqueta real)
  fecha_corte_real date,
  fuente text default 'zqm',
  cargado_en timestamptz not null default now(),
  primary key (sec_ste, campana)
);
create index if not exists tch_real_campana on tch_real (campana);

-- Factor de recalibración aprendido. Una fila por planta×campaña; el job de
-- estimados toma el más reciente por planta. Guarda también el diagnóstico para
-- que el tablero muestre qué tan bien vamos (sesgo crudo, MAPE residual).
create table if not exists tch_factor (
  id bigint generated always as identity primary key,
  planta text not null,               -- riopaila | castilla
  campana text not null,
  factor numeric not null,            -- k = Σ(real·área)/Σ(crudo·área)
  n_suertes int not null,             -- cortes cerrados que lo respaldan
  area_ha numeric,                    -- área cosechada base del factor
  tch_real_agg numeric,               -- toneladas reales agregadas
  tch_est_agg numeric,                -- toneladas estimadas (crudo) agregadas
  sesgo_pct numeric,                  -- (est_crudo/real - 1)·100  (+ = corre caliente)
  mape numeric,                       -- MAPE del estimado reportado vs real (%)
  vigente_desde date,                 -- corrida desde la que aplica
  modelo_version text,
  creado_en timestamptz not null default now(),
  unique (planta, campana)            -- idempotente: recalcular una campaña no duplica
);
create index if not exists tch_factor_planta on tch_factor (planta, campana);

-- RLS: lectura abierta (alimentan el tablero); escritura solo con service_role.
alter table tch_real enable row level security;
alter table tch_factor enable row level security;

create policy tch_real_sel on tch_real for select using (true);
create policy tch_factor_sel on tch_factor for select using (true);
