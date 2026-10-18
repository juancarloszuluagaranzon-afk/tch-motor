# Estimador TCH · aplicación de escritorio

El motor, el tablero y el ciclo del mes, empaquetados en un instalador de Windows
(`EstimadorTCH-Setup-<versión>.exe`). Quien lo instala no necesita Python, Git ni la consola.

## Qué hace

Una ventana con el ciclo del mes, en orden:

1. **Cargar las cosechas**: Riopaila desde la app de Turnos; Castilla pegando la lista del ingenio.
2. **Correr el motor**: completa la tabla del satélite (Earth Engine), reentrena y estima.
3. **Revisar** el tablero con la corrida nueva, dentro de la misma app.
4. **Publicar** el tablero en `estimador-tch.vercel.app` (API de Vercel, sin Git).
5. **Actualizar los aforos** de la app de Turnos con el estimado nuevo.

Un panel de estado avisa qué falta: insumos, cosechas del mes, imágenes nuevas del satélite, corrida
sin publicar. Cada tarea deja su registro en la carpeta de trabajo.

## Dónde guarda las cosas

| Qué | Dónde |
|---|---|
| Programa | `%LOCALAPPDATA%\Programs\Estimador TCH` (se instala sin permisos de administrador) |
| Configuración | `%APPDATA%\EstimadorTCH\config.json` |
| Llaves (Earth Engine, Turnos, Vercel) | `%APPDATA%\EstimadorTCH\llaves.dat`, cifradas con DPAPI: solo ese usuario de Windows en ese PC las lee |
| Carpeta de trabajo | la que se elija; conviene una compartida (OneDrive) para que otro PC continúe donde quedó este. Trae `Satelite\`, `Tablero\data\` (corridas e historial) y `Registros\` |
| Insumos | la carpeta «RIOPAILA AGRICOLA» con `01 Estimados y TCH` y `02 Cosecha y molienda` |

La primera vez, la carpeta de trabajo se siembra con la tabla del satélite y la última corrida que trae
el instalador. Desinstalar no borra ni la configuración ni la carpeta de trabajo.

## Cómo está hecho

- `app/principal.py`: sin argumentos abre la ventana (un servidor local en 127.0.0.1 con token por
  sesión + Microsoft Edge en modo aplicación); con `--tarea <tipo>` corre una tarea sin ventana.
- `app/tareas.py`: cada tarea corre en un proceso aparte que escribe su registro; la ventana lo lee.
  Las tareas llaman a los mismos programas de `scripts/` (`mensual.py`, `cosechas_desde_app.py`,
  `modelo_en_aforos.py`): no hay una segunda copia del motor.
- `app/config.py`: rutas y llaves; pasa al motor `TCH_DOCS`, `TCH_TABLERO`, `TCH_GEE_DIR`,
  `TCH_TABLONES`, `GEE_KEY_JSON`, `TCH_TURNOS_URL/KEY` (ver `tchmotor/rutas.py`).
- `app/publicar.py`: sube a Vercel solo los archivos que cambiaron (por SHA-1), crea el despliegue de
  producción, mueve el alias y comprueba que el sitio ya muestra la corrida nueva.
- `app/estado.py`: el panel de estado, sin correr nada pesado.
- `app/ui/`: la interfaz (HTML, CSS y JavaScript, mismo diseño del tablero).

## Armar una versión nueva

Una sola vez, el entorno de construcción (aparte de `.venv-gee`):

```powershell
python -m venv .venv-build
.venv-build\Scripts\python.exe -m pip install numpy==2.5.3 pandas==3.0.6 scikit-learn==1.9.1 openpyxl==3.1.5 earthengine-api==1.7.45 pyinstaller==6.22.3
```

e [Inno Setup 6](https://jrsoftware.org/isinfo.php). Después, cada versión:

1. Subir el número en `app/version.py`.
2. Desde la raíz de `tch-motor`: `powershell -ExecutionPolicy Bypass -File producto\construir.ps1`

Queda en `producto\dist\EstimadorTCH-Setup-<versión>.exe`. El instalador trae el código del tablero,
el mapa de suertes (de `agrocontrol-campo`), la copia del maestro y la última corrida de este PC, así
que conviene armarlo justo después de una corrida publicada.

## Probar desde el código

```powershell
cd producto
..\.venv-gee\Scripts\python.exe -m app.principal --datos C:\temp\estimador-prueba
```

`--datos` usa otra carpeta de configuración, para no tocar la real. `--sin-ventana --puerto 8765 --token x`
deja el servidor sin abrir Edge (para probar en otro navegador: `http://127.0.0.1:8765/?t=x`).
