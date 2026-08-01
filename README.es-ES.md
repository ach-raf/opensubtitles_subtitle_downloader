

# Descargador de subtítulos

Una aplicación de Python para buscar, comparar y descargar subtítulos desde
[OpenSubtitles](https://www.opensubtitles.com/),
[SubDL](https://subdl.com/), y [SubSource](https://subsource.net/).
Acepta archivos de video individuales o carpetas, abre una interfaz de terminal
controlada por teclado de forma predeterminada y puede limpiar, normalizar y
sincronizar los subtítulos descargados.

![Resultados de búsqueda del Descargador de subtítulos](screenshots/readme-search.png)

## Qué hace

- Busca en un proveedor o en todos los disponibles mediante el modo Todos los proveedores.
- Combina coincidencias de hash y nombre de archivo de OpenSubtitles.
- Filtra por idioma, estado de discapacidad auditiva y estado de traducción por IA.
- Maneja videos individuales, múltiples rutas y carpetas.
- Descarga el subtítulo seleccionado junto a su video o en un directorio de salida configurado.
- Convierte el texto del subtítulo a UTF-8 cuando está configurado.
- Elimina líneas publicitarias conocidas después de la descarga cuando la limpieza está habilitada.
- Sincroniza el temporizado de los subtítulos con el audio del video mediante
  [ffsubsync](https://github.com/smacke/ffsubsync).
- Incluye una interfaz Textual a pantalla completa y una CLI sin TUI para flujos de trabajo por lotes y de compatibilidad.

## Recorrido por la interfaz

La vista Cola mantiene visible el idioma, modo de proveedor, progreso y errores de cada archivo multimedia durante un proceso por lotes:

![Cola por lotes del Descargador de subtítulos](screenshots/readme-queue.png)

Presiona `Ctrl+K` para buscar en la paleta de comandos acciones de navegación, búsqueda, proveedor y aplicación:

![Paleta de comandos del Descargador de subtítulos filtrada por acciones de motor](screenshots/readme-command-palette.png)

## Requisitos

- Python 3.10 o superior
- Credenciales para al menos un proveedor de subtítulos
- `ffmpeg` si deseas sincronización de audio
- Git si vas a clonar el repositorio

## Instalación

Clona el repositorio y entra en su directorio:

```bash
git clone https://github.com/ach-raf/opensubtitles_subtitle_downloader.git
cd opensubtitles_subtitle_downloader
```

Usando [uv](https://docs.astral.sh/uv/) (recomendado):

```bash
uv sync
```

Esto crea `.venv` e instala las dependencias de ejecución bloqueadas. No necesitas activar el entorno; antepone `uv run` a los comandos, por ejemplo:

```bash
uv run python download_subs.py "path/to/movie.mkv"
```

Los colaboradores pueden incluir las herramientas de formateo, linting y pruebas con:

```bash
uv sync --group dev
```

O usa la biblioteca estándar y `pip`:

```bash
python -m venv .venv
```

Activa el entorno:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux y macOS
source .venv/bin/activate
```

Luego instala las dependencias:

```bash
python -m pip install -r requirements.txt
```

Copia la configuración de ejemplo:

```powershell
# Windows PowerShell
Copy-Item config.yaml.sample config.yaml
```

```bash
# Linux y macOS
cp config.yaml.sample config.yaml
```

Abre `config.yaml` y reemplaza las credenciales de marcador de posición para los proveedores que pretendas usar.

## Credenciales de los proveedores

Solo necesitas configurar los proveedores que uses.

### OpenSubtitles

Crea un consumidor de API en la
[página de API de OpenSubtitles](https://www.opensubtitles.com/en/consumers). Agrega el
nombre de usuario, contraseña, clave de API y user agent de la cuenta a la sección `opensubtitles`
de `config.yaml`.

### SubDL

Crea o copia una clave de API desde tu [cuenta de SubDL](https://subdl.com/) y agréga
la a la sección `subdl`.

### SubSource

Copia la clave de API `sk_...` desde tu perfil de [SubSource](https://subsource.net/) y
agréga la a la sección `subsource`.

## Configuración

`config.yaml.sample` es el mejor punto de partida. Un ejemplo abreviado:

```yaml
general: # Las opciones explícitas de CLI anulan estos ajustes para una ejecución.
  preferred_backend: ask # Opciones: opensubtitles, subdl, subsource, auto, all-providers, ask
  default_language: "" # Código ISO. Establece esto explícitamente para ejecuciones no atendidas predecibles.
  recursive_search: false # Descubre recursivamente archivos de video en las entradas de carpetas.
  subtitle_output_directory: "" # Vacío guarda junto a cada video. Las rutas relativas se resuelven desde este archivo de configuración.
  skip_interactive_menu: false # Opciones: true, false
  sync_audio_to_subs: ask # Opciones: true, false, ask
  auto_selection: false
  opt_force_utf8: true
  no_tui: false # Opciones: true, false. Establece true para omitir la interfaz Textual. Anula por ejecución con --tui / --no-tui.
  hearing_impaired: include # Opciones: include, exclude, only
  show_ai_translated: true
  media_extensions: # Extiende o reduce la lista integrada de extensiones de video.
    include: [] # Ejemplo: [custom]
    exclude: [] # Ejemplo: [wmv, .ts]. Las exclusiones tienen prioridad sobre las inclusiones.

opensubtitles:
  username: opensubtitles_username
  password: opensubtitles_password
  api_key: opensubtitles_api_key
  user_agent: opensubtitles_user_agent
  languages:
    English: en
    Arabic: ar
    French: fr
    Japanese: ja

subdl:
  api_key: subdl_api_key
  languages:
    English: en
    Arabic: ar
    French: fr
    Japanese: ja

subsource:
  api_key: subsource_api_key # sk_... desde tu página de perfil de SubSource
  languages:
    English: en
    Arabic: ar
    French: fr
    Japanese: ja

cleaning_subtitles:
  enabled: true
  supported_media:
    - srt
    - ass
    - ssa
    - sub
    - smi
    - vtt
    - ttml
    - dfxp
    - mpl2
    - lrc
    - sbv
    - rt
    - txt
  ads:
    separator: ","
    file_path: ""
    #file_path: "C:\\clean_subtitles\\ads.txt" ejemplo
```

Ajustes importantes:

| Ajuste                      | Valores                                                                | Significado                                                                                |
| --------------------------- | --------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `preferred_backend`         | `opensubtitles`, `subdl`, `subsource`, `auto`, `all-providers`, `ask` | Selecciona el comportamiento del proveedor.                                                         |
| `default_language`          | Código ISO de idioma o cadena vacía                                   | Establece el idioma de la ejecución; vacío recurre al primer idioma relevante configurado.   |
| `recursive_search`          | `true`, `false`                                                       | Descubre recursivamente videos debajo de las entradas de carpetas.                                      |
| `subtitle_output_directory` | ruta o cadena vacía                                                  | Guarda subtítulos en un directorio escribible único; vacío guarda junto a cada video.              |
| `skip_interactive_menu`     | `true`, `false`                                                       | Omite la confirmación inicial de idioma de la TUI; `preferred_backend: ask` sigue abriendo el selector de proveedor. |
| `sync_audio_to_subs`        | `true`, `false`, `ask`                                                | Sincroniza siempre o nunca; `ask` solicita en la TUI y omite la sincronización en modo sin TUI.   |
| `auto_selection`            | `true`, `false`                                                       | Descarga automáticamente el primer resultado de la TUI; el modo sin TUI siempre selecciona el primer resultado. |
| `opt_force_utf8`            | `true`, `false`                                                       | Normaliza el texto del subtítulo descargado a UTF-8.                                          |
| `no_tui`                    | `true`, `false`                                                       | Omite la interfaz Textual de forma predeterminada cuando se establece en `true`.                             |
| `hearing_impaired`          | `include`, `exclude`, `only`                                          | Controla los resultados de subtítulos para personas con discapacidad auditiva.                                            |
| `show_ai_translated`        | `true`, `false`                                                       | Incluye u oculta subtítulos marcados como traducidos por IA.                                   |
| `media_extensions.include`  | lista de extensiones                                                  | Agrega extensiones de video a la lista integrada de descubrimiento.                                  |
| `media_extensions.exclude`  | lista de extensiones                                                  | Elimina extensiones de video; las exclusiones tienen prioridad sobre las adiciones.                   |

Cada proveedor tiene su propia asignación `languages`. El nombre de visualización se muestra en la
interfaz; el valor es el código de idioma del proveedor.

El descubrimiento de multimedia usa una lista integrada para archivos directos, carpetas y carpetas recursivas: `3g2`, `3gp`, `asf`, `avi`, `av1`, `divx`, `f4v`, `flv`, `h264`,
`h265`, `hevc`, `m2ts`, `m2v`, `m4v`, `mkv`, `mov`, `mp4`, `mpeg`, `mpg`,
`mts`, `mxf`, `ogm`, `ogv`, `rm`, `rmvb`, `ts`, `vob`, `webm` y `wmv`.
Los valores configurados no distinguen mayúsculas de minúsculas y pueden incluir un punto inicial.
`cleaning_subtitles.supported_media` son metadatos separados de formato de subtítulo; no
controla el descubrimiento de video.

`hearing_impaired` y `show_ai_translated` usan metadatos proporcionados por cada
proveedor. OpenSubtitles proporciona ambos marcadores, SubSource proporciona marcadores de HI y producción por máquina, y SubDL actualmente proporciona HI pero ningún marcador fiable de traducción por IA. El filtrado por IA es, por lo tanto, de mejor esfuerzo para SubDL.

`auto` intenta los proveedores configurados uno a la vez y se detiene en el primero con
candidatos. Su orden de respaldo base es SubSource, OpenSubtitles y luego SubDL;
los proveedores marcados como accesibles por un diagnóstico de actualización manual se prueban primero.
`all-providers` busca en cada proveedor configurado de forma concurrente y usa un
ranking compartido.

Para eliminar líneas publicitarias adicionales, apunta
`cleaning_subtitles.ads.file_path` a un archivo de texto que contenga entradas separadas
por `cleaning_subtitles.ads.separator`. Cuando no se establece una ruta, se usa la lista integrada.

## Uso

Los ejemplos a continuación usan `python`. Si instalaste con uv, ejecútalos como
`uv run python ...` en su lugar; uv mantiene sincronizado automáticamente
el entorno del proyecto.

Abre la TUI para un video:

```bash
python download_subs.py "path/to/movie.mkv"
```

Pasa varios archivos o carpetas:

```bash
python download_subs.py "path/to/movie.mkv" "path/to/show/season 01"
```

Escanea recursivamente un archivo de películas:

```bash
python download_subs.py --recursive "path/to/movies"
```

Guarda subtítulos fuera de una biblioteca multimedia de solo lectura:

```bash
python download_subs.py --output-dir "path/to/subtitles" "path/to/movies"
```

La línea de comandos anula `config.yaml` para una ejecución. Usa `--no-recursive` para
desactivar la recursión configurada, o `--output-next-to-media` para ignorar un
directorio de salida de subtítulos configurado. Las rutas relativas en `config.yaml` se resuelven desde el
directorio del archivo de configuración; las rutas relativas de `--output-dir` se resuelven desde el
directorio de trabajo actual.

La salida personalizada usa un directorio plano. Los archivos de subtítulos existentes no se sobrescriben
en silencio, y la CLI sin cabeza rechaza cualquier lote en el que varios videos
producirían el mismo nombre de archivo de salida.

Inicia la TUI con un idioma y proveedor seleccionados:

```bash
python download_subs.py --lang en --backend subdl "path/to/movie.mkv"
```

Busca en todos los proveedores configurados en la TUI:

```bash
python download_subs.py --backend all-providers "movie.mkv"
```

Las opciones explícitas `--lang` y `--backend` anulan `config.yaml` para una ejecución. Si
ni `--lang` ni `general.default_language` están establecidos, un proveedor concreto usa
el primer idioma en su asignación; `all-providers` verifica las asignaciones de OpenSubtitles,
SubDL y luego SubSource; y `auto` o `ask` recurre al primer
idioma de OpenSubtitles. Establece un idioma explícito para ejecuciones no atendidas
predecibles. El modo sin TUI aplica el idioma resuelto sin un prompt de idioma.

Ejecuta sin la interfaz Textual:

```bash
python download_subs.py --no-tui "path/to/movie.mkv"
```

Para una ejecución totalmente no atendida, selecciona un proveedor concreto, `auto` o
`all-providers` con `--backend` o `general.preferred_backend`. El valor
`ask` sigue abriendo el prompt de proveedor de la CLI. En modo sin TUI,
`sync_audio_to_subs: ask` omite la sincronización e imprime un aviso.

Aplica un idioma automáticamente en un lote sin TUI:

```bash
python download_subs.py --no-tui --lang ar "path/to/season"
```

Busca en cada proveedor configurado en un lote sin TUI:

```bash
python download_subs.py --no-tui --backend all-providers "season"
```

En la TUI, `auto_selection` controla si el resultado con mayor ranking se
descarga automáticamente o se muestra para selección. Sin TUI siempre descarga el
resultado con mayor ranking para el modo de búsqueda seleccionado, independientemente de
`auto_selection`. Los fallos de proveedor o archivo se reportan sin detener archivos posteriores
en el lote. Los archivos de subtítulos existentes se omiten en modo sin TUI en lugar
de sobrescribirse.

### Automatización por lotes no atendida

Para ejecuciones repetibles sin preguntas de inicio, idioma, selección de resultados o sincronización, configura valores predeterminados concretos:

```yaml
general:
  preferred_backend: subdl
  default_language: ar
  recursive_search: true
  skip_interactive_menu: true
  sync_audio_to_subs: false
  auto_selection: true
  no_tui: true
```

`preferred_backend: auto` es adecuado cuando una ejecución no atendida debe detenerse en el
primer proveedor del orden de respaldo que devuelva candidatos. Usa `preferred_backend:
all-providers` para consultar cada proveedor configurado y elegir desde su ranking
compartido. Evita `preferred_backend: ask` para automatización porque requiere una
elección de proveedor. Establece `default_language` explícitamente para ejecuciones no atendidas en lugar
de depender del respaldo específico del modo de idioma descrito anteriormente.

Las opciones de línea de comandos tienen prioridad sobre estos ajustes para la ejecución actual:

```bash
python download_subs.py \
  --no-tui \
  --backend subdl \
  --lang ar \
  --recursive \
  "path/to/library"
```

En Windows PowerShell, usa el mismo comando en una sola línea:

```powershell
python download_subs.py --no-tui --backend subdl --lang ar --recursive "D:\Shows"
```

Fuerza la TUI cuando `general.no_tui` está habilitado:

```bash
python download_subs.py --tui "path/to/movie.mkv"
```

Consulta la ayuda completa de la línea de comandos:

```bash
python download_subs.py --help
```

## Controles de la TUI

Después de cualquier selección de proveedor o idioma al inicio, la interfaz usa la vista
Búsqueda. Las teclas más útiles son:

| Tecla                      | Acción                                                        |
| -------------------------- | ------------------------------------------------------------- |
| `j`, `k` o teclas de flecha | Moverse por los resultados                                          |
| `Enter`                | Descargar el resultado seleccionado                                  |
| `/`                    | Editar la consulta; presiona `Enter` para buscar                       |
| `Esc`                  | Devolver el foco al espacio de trabajo activo                          |
| `L` o `l`             | Seleccionar un idioma                                             |
| `E` o `e`             | Seleccionar un proveedor, respaldo automático o búsqueda en todos los proveedores |
| `m`                    | Alternar el modo Todos los proveedores                                     |
| `r`                    | Actualizar diagnóstico de disponibilidad y latencia de proveedores         |
| `p`                    | Mostrar detalles para el candidato seleccionado                       |
| `y`                    | Copiar la URL pública del candidato, cuando esté disponible               |
| `F1`–`F4`              | Abrir Búsqueda, Cola, Historial o Configuración                        |
| `Ctrl+PgDn` / `Ctrl+PgUp` | Alternar hacia adelante o atrás entre las vistas                |
| `Ctrl+K`               | Abrir la paleta de comandos                                      |
| `Ctrl+S`               | Revisar y guardar cambios desde la vista Configuración                  |
| `?`                    | Mostrar el recordatorio de accesos directos                                    |
| `q`                    | Salir; el trabajo inacabado o los ajustes sin guardar requieren confirmación |

Cuando `sync_audio_to_subs` es `ask`, la aplicación pregunta si sincronizar
después de una descarga exitosa. Cuando es `true` o `false`, esa elección se
aplica sin solicitar. La limpieza de subtítulos sigue
`cleaning_subtitles.enabled`.

## Windows Enviar a

El `1_download_subs.bat` incluido está configurado para la ruta local original
de este repositorio. Edita sus rutas antes de usarlo en otro lugar.

Para agregarlo al menú Enviar a de Windows:

1. Presiona `Win+R`.
2. Introduce `shell:sendto`.
3. Coloca un acceso directo al archivo por lotes editado en esa carpeta.

Luego puedes hacer clic derecho en un video o carpeta y enviarlo al descargador. Establece
`general.no_tui: true` si prefieres la CLI sin TUI para este flujo de trabajo. También establece
un backend distinto de `ask` para uso no atendido.

## Linux y macOS (ejecutar desde cualquier lugar)

Crea un script envoltorio para que `download_subs` funcione desde cualquier directorio.

1. Asegúrate de que `$HOME/bin` esté en tu `PATH`. Agrega esto a `~/.bashrc` o
   `~/.bash_profile`:

   ```bash
   export PATH="$PATH:$HOME/bin"
   ```

2. Crea `$HOME/bin/download_subs.sh` apuntando a este repositorio:

   ```bash
   #!/bin/bash

   # Activa el virtualenv del proyecto, ejecuta el script y luego desactívalo.
   source /path/to/new_opensubtitles/.venv/bin/activate \
     && python /path/to/new_opensubtitles/download_subs.py "$@" \
     && deactivate
   ```

   Reemplaza `/path/to/new_opensubtitles` con la ruta real a este repositorio.

3. Hazlo ejecutable:

   ```bash
   chmod +x "$HOME/bin/download_subs.sh"
   ```

Después de la configuración, llámalo desde cualquier lugar:

```bash
download_subs.sh "path/to/movie.mkv"
download_subs.sh "path/to/season 01"
```

Establece `general.no_tui: true` si prefieres la CLI sin TUI para este flujo de trabajo. También
establece un backend distinto de `ask` para uso no atendido.

## Solución de problemas

### Un proveedor no devuelve resultados

Verifica que sus credenciales requeridas y asignación de idioma estén presentes en
`config.yaml`. En la TUI, presiona `r` para verificar la disponibilidad del proveedor, luego prueba con un
proveedor diferente o el modo Todos los proveedores.

### La sincronización falla

Confirma que `ffmpeg` esté instalado y disponible en `PATH`. La sincronización es
opcional; establece `sync_audio_to_subs: false` para mantener el temporizado descargado.

### SubSource no puede extraer un archivo RAR

Los requisitos incluyen soporte RAR para Python. Un ejecutable `7z` en `PATH` es el
respaldo cuando ese paquete no está disponible.

### La TUI no puede ejecutarse en el terminal actual

Usa `--no-tui` o establece `general.no_tui: true` en `config.yaml`.

### Un subtítulo existente no se reemplaza

La TUI pregunta antes de reemplazar un subtítulo existente. Confirma el reemplazo
cuando se solicite. El modo sin TUI reporta el conflicto y omite ese archivo; nunca
lo sobrescribe automáticamente.

Reporta problemas reproducibles en el
[rastreador de problemas de GitHub](https://github.com/ach-raf/opensubtitles_subtitle_downloader/issues).

## Servicios y bibliotecas

- [API de OpenSubtitles](https://opensubtitles.stoplight.io/docs/opensubtitles-api/e3750fd63a100-getting-started)
- [SubDL](https://subdl.com/)
- [SubSource](https://subsource.net/)
- [Textual](https://textual.textualize.io/)
- [ffsubsync](https://github.com/smacke/ffsubsync)

## Licencia

Este proyecto está disponible bajo la [Licencia MIT](LICENSE).
