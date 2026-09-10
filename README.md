# Motor de estimados de TCH — Riopaila

Núcleo reutilizable del estimador de **TCH** (toneladas de caña por hectárea) por
suerte, validado contra la cosecha real 2026: **±1,9 % en el agregado (Riopaila),
MAPE ~12 % por suerte**, y **nivel Nax (MAPE 10 %, ±20 % 86 %) cuando se fusiona
con el aforo en vivo**.

Esta es la **Fase P0** del pipeline: la lógica consolidada y con tests. La
extracción de curvas (endpoint CDSE `/api/sentinel-stats` ya desplegado en Rio
Map), la persistencia en Supabase, el job mensual y el tablero son fases
siguientes.

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
