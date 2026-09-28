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

- **Entradas locales:** ZQM histórico y 2026 (Excel), base de aforos (Excel, para el
  aforo sintético), maestros de suertes de Rio Map (JSON) y la tabla mensual de
  Earth Engine (`data/gee/mensual_<planta>.csv`, que la corrida actualiza).
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
