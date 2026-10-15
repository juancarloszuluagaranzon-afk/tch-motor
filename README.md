# Motor de estimados de TCH — Riopaila

Núcleo reutilizable del estimador de **TCH** (toneladas de caña por hectárea) por
suerte.

## Corrida mensual (modelo `ee-1.0`, sin base de datos)

Desde sep-2026 el motor corre con **Google Earth Engine** y **archivos**: no depende
de Supabase ni de la cuota de Copernicus.

```powershell
.venv-gee\Scripts\python.exe scripts\mensual.py          # corrida completa (~4 min)
.venv-gee\Scripts\python.exe scripts\mensual.py --sin-gee  # sin actualizar el satélite
powershell -File scripts\mensual.ps1 -Publicar             # corrida + commit/push del tablero
```

- **Entradas locales:** ZQM histórico y 2026, `cosechas_recientes.xlsx` (cosechas que el
  ZQM aún no trae) y la base de aforos (para el aforo sintético), en
  `Documentos/RIOPAILA AGRICOLA/`; el maestro oficial (`maestro-riopaila`) y la tabla
  mensual de Earth Engine (`data/gee/mensual_<planta>.csv.gz`, que la corrida actualiza
  y va en git comprimida). Todas las rutas están en `tchmotor/rutas.py`.
- **Modelo:** Random Forest entrenado con las campañas completas anteriores
  (8.330 ciclos 2019-2026), con curvas de Sentinel-2 por suerte, historia propia de
  la suerte y agronomía, a varias edades de observación para estimar caña joven.
- **Factor de la campaña:** sale de las cosechas ya cerradas del año (ZQM) y corrige
  el corrimiento del año que la historia no enseña.
- **Salida:** JSON en `~/tch-dashboard/data` (estimados, reales, factores, curvas, meta).
- **Validación** (`scripts/entrenar_gee.py`, informe en `data/gee/validacion_gee.txt`):
  frente al modelo anterior, en las mismas suertes, MAPE 2026 15,0 % → 13,3 %
  (±20 %: 72 % → 81 %); con el factor mensual de la campaña, Riopaila 9,7 % y
  Castilla 11,4 %.
- Credenciales de Earth Engine en `.env.local` (`GEE_PROJECT`, `GEE_KEY_FILE`); el
  entorno aislado es `.venv-gee` (no instalar `earthengine-api` en el Python global).

## Programas del mes

| Programa | Qué hace |
|---|---|
| `scripts/cosechas_desde_app.py --mes 2026-10` | Agrega a `cosechas_recientes.xlsx` las cosechas de Riopaila terminadas en el mes (app de Turnos). Castilla se pega a mano. Correrlo **antes** de la corrida mensual. |
| `scripts/mensual.py` | Corrida mensual del motor (Earth Engine + Excel → JSON del tablero). `--sin-gee` reutiliza la tabla del satélite. |
| `scripts/presupuesto_cosecha.py --anio 2027 --planta riopaila --meses-ciclo 12 --ajuste -0.15` | Presupuesto de cosecha por suerte y mes, en Excel con fórmulas. La hoja «Supuestos» trae la prueba del año anterior para decidir el ajuste. |
| `scripts/comparar_real_motor_aforo.py --desde 2026-09-01 --hasta 2026-10-31` | TCH real (app de Cosecha) frente al motor y al aforo de Agronomía, por plantilla, soca, variedad y suerte, en Excel. |
| `scripts/gee_mensual.py` / `scripts/gee_clima.py` | Rehacen las tablas de satélite y clima desde cero (solo si se pierden). |
| `scripts/entrenar_gee.py` | Reentreno y validación fuera de muestra (informe en `data/gee/validacion_gee.txt`). |

Los Excel salen por defecto en `Documentos/RIOPAILA AGRICOLA/01 Estimados y TCH/` (`--salida` para otra ruta).

## Correr en otro PC

1. **Instalar** Python 3.11 o más nuevo (producción usa 3.14) y Git.
2. **Clonar** este repositorio y, al lado, en la carpeta del usuario:
   - `tch-dashboard` (ahí escribe la corrida mensual sus JSON),
   - `agrocontrol-campo` (solo se usan `public/data/tablones_<planta>.geojson`, para actualizar el satélite),
   - `maestro-riopaila` (opcional: respaldo del maestro si no hay internet; normalmente se lee de GitHub Pages).
3. **Entorno:**
   ```powershell
   python -m venv .venv-gee
   .venv-gee\Scripts\python.exe -m pip install -r requirements.txt
   .venv-gee\Scripts\python.exe -m pytest -q
   ```
4. **`.env.local`** en la raíz del repo (NO va en git):
   ```
   GEE_PROJECT=riopaila-estimador-tch
   GEE_KEY_FILE=C:\ruta\a\la\llave-de-la-cuenta-de-servicio.json
   ```
   La llave JSON de Earth Engine se copia por un medio seguro (nunca por git ni por chat).
   Si las carpetas están en otra parte, se agregan aquí `TCH_DOCS`, `TCH_TABLONES`, `TCH_TABLERO`,
   `TCH_MAESTRO_LOCAL`, `TCH_TURNOS_ENV`, `TCH_AFOROS_DIAMETRO` o `TCH_PPTO_REFERENCIA` (ver `tchmotor/rutas.py`).
5. **Excel de entrada** (NO van en git: el ZQM trae la liquidación en $). Misma estructura de carpetas:
   - `Documentos/RIOPAILA AGRICOLA/02 Cosecha y molienda/`: `historico zqm.xlsx`, `zqm 26.xlsx`, `cosechas_recientes.xlsx`
   - `Documentos/RIOPAILA AGRICOLA/01 Estimados y TCH/`: `Base de aforos completa 2026.xlsx`
   - Para `cosechas_desde_app.py` y el comparativo: el `.env.local` de la app de Turnos
     (`~/turnos-jornales/.env.local`) y el libro «Aforos con Diámetro 2026» de Agronomía (OneDrive).
6. **Probar** sin tocar el satélite: `.venv-gee\Scripts\python.exe scripts\mensual.py --sin-gee --salida C:\temp\prueba`.

La tarea programada (día 2 de cada mes) se registra con `scripts\registrar_tarea.ps1`; corre
`scripts\mensual.ps1 -Publicar`, que publica el tablero en Vercel.

## Fase P0 (modelo anterior, Copernicus + Supabase)

Validado contra la cosecha real 2026: **±1,9 % en el agregado (Riopaila),
MAPE ~12 % por suerte**, y **nivel Nax (MAPE 10 %, ±20 % 86 %) cuando se fusiona
con el aforo en vivo**. Los módulos de Supabase (`persistencia`, `pipeline`,
`autocorreccion`) y el servicio de Render quedan de referencia; la corrida mensual
ya no los usa.

## Qué hay aquí

| Módulo | Rol |
|---|---|
| `tchmotor/aforo.py` | Aforo **físico** (fórmula de campo) y **sintético** (mediana histórica de tallos por variedad×soca) |
| `tchmotor/agronomia.py` | Zona agroecológica Cenicaña (`6H1`→suelo/humedad) y diccionario de variedades `V##`→`CC ##-####` |
| `tchmotor/curva.py` | Features de la curva satelital (pico, vigor, AUC…), con truncado por edad para proyectar caña joven |
| `tchmotor/features.py` | Ensambla el vector de features de una suerte (curva + agronomía + aforo sintético + aforo en vivo) |
| `tchmotor/modelo.py` | `MotorTCH`: Random Forest con one-hot de variedad y banda de incertidumbre |
| `tchmotor/recalibracion.py` | Factor por planta/campaña (real/estimado ponderado por área) |
| `data/var_map.json` | Diccionario de variedades (112 entradas) |

## Los dos modos de estimación

- **Con aforo en vivo** (de Turnos & Jornales): se fusiona → **nivel Nax**.
- **Sin aforo**: motor + **aforo sintético** (siempre disponible) → MAPE ~13,6 %.

## Uso

```bash
pip install -e .
pytest            # lógica pura verificada
```

```python
from tchmotor import cargar_var_map, AforoSintetico, build_features, MotorTCH, factor

vm = cargar_var_map()
sint = AforoSintetico(registros_de_aforos)       # historia de tallos
feats = build_features(registro_de_suerte, sint, vm, aforo_vivo=None, max_age=None)
# entrenar con el histórico y predecir; recalibrar con las cosechas cerradas
```

## Notas
- El ZQM trae columnas de **$/liquidación**: sólo se usan las agronómicas.
- El factor de recalibración se **re-deriva cada campaña y por planta**
  (Riopaila y Castilla corren distinto).
