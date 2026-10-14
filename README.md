# Traviesos.py · SARRCA

SARRCA es el sistema que estamos haciendo para la red de sensores de calidad del aire de Zacatecas y Guadalupe. La idea es que las lecturas de los sensores M5Stack lleguen solas, se guarden sin perder ni repetir ninguna, se calculen los promedios como dice la NOM-025 y salgan los reportes diario y mensual que hoy se hacen a mano en Excel.

Equipo 3 · Administración de Proyectos de Software · Ago–Dic 2026 · UAZ

---

## Qué lleva el MVP

Para la primera entrega el flujo es más o menos este: la administradora entra, registra un sensor, las lecturas empiezan a llegar solas y cada día puede ver su reporte diario (gráficas de cada variable + tabla de promedios de 24 h). Al cerrar el mes ve el reporte mensual.

O sea, en el MVP van:

- Inicio de sesión
- Registrar un sensor
- Recibir las lecturas automáticamente desde la nube de M5Stack (EzData)
- Saber si cada hora es válida y calcular su concentración
- Promedio diario y excedencias de la norma
- Reporte diario y reporte mensual

Lo que **no** va todavía (ni el código ni sus tablas): bitácora, monitoreo de salud del sistema, respaldos, correos, banderas automáticas, catalogar lecturas, el índice de calidad del aire, PDF, borrado de datos personales e invitaciones. Todo eso llega en los incrementos.

---

## Tecnologías

| Para qué | Qué usamos |
|---|---|
| Lenguaje / framework | Python 3.13 y Django 5.2 LTS |
| Interfaz | Plantillas de Django + HTMX 2 + Bootstrap 5 (todo se genera en el servidor, no hay React ni nada así) |
| Gráficas | Chart.js 4.5.1, servido desde `static/vendor/` |
| Base de datos | PostgreSQL 18 |
| Tareas en segundo plano | APScheduler, en un contenedor aparte (`worker`) |
| Cifrado | `cryptography` (Fernet) |
| Contenedores | Docker Compose |
| Calidad | pytest, ruff, import-linter y GitHub Actions |

---

## Cómo está armado

Es un **monolito modular**: un solo proyecto de Django partido en módulos (apps), y el mismo código corre en dos procesos.

```mermaid
flowchart LR
    U(["Administradora"]) --> W["<b>web</b><br/>Django + gunicorn<br/>login, alta de sensores,<br/>reportes"]
    W -- "SQL" --> DB[("<b>db</b><br/>PostgreSQL 18")]
    K["<b>worker</b><br/>Django + APScheduler<br/>· hilos de recepción<br/>· hilos de cálculo"] -- "SQL" --> DB
    K -- "HTTPS GET<br/>(solo recepción)" --> EZ[("Nube EzData<br/>M5Stack")]
```

### Los procesos

- **web**: las pantallas, los permisos por rol, el alta de sensores y los reportes. La web **nunca** le habla a EzData; cuando das de alta un sensor solo deja una "verificación pendiente" en la base y el worker se encarga.
- **worker**: un solo proceso con dos grupos de hilos, para que uno no frene al otro.
  - *Recepción*: consulta la nube cada 15 min, baja el historial una vez al día (02:10), concilia los domingos y atiende las verificaciones de los sensores nuevos.
  - *Cálculo*: cada minuto revisa qué horas hay que recalcular, y cierra la hora (a las hh+1:20), el día (00:30) y el mes (el día 1 a las 00:45).
- **db**: los datos, y además es por donde se coordinan web y worker.

No usamos broker (ni Celery, ni Redis, ni señales de Django). Web y worker se comunican con tablas: la web crea una *verificación de sensor* y la va consultando cada 2 s con HTMX hasta que el worker deja el resultado; y cada vez que se guarda una lectura se deja una *marca de recálculo* que el cálculo recoge después.

### Capas dentro de cada módulo

Siempre se llama hacia abajo, nunca al revés:

| Capa | Archivo(s) | Qué va ahí |
|---|---|---|
| Presentación | `views.py`, `urls.py`, `forms.py`, `templates/` | Nada de reglas de negocio, solo llama a servicios y consultas |
| Servicios | `services.py` | Lo único que escribe en la base. Revisa el rol y abre la transacción |
| Consultas | `selectors.py` | Lo que leen las pantallas y los reportes |
| Modelos | `models.py` | Las tablas |
| Tareas | `jobs.py` | Las tareas programadas; llaman a los mismos servicios que la web |

Hay dos excepciones a propósito:

- **`calculo/dominio/`** es Python puro, **sin Django y sin base de datos**. Ahí van las reglas de la norma (hora válida, concentración horaria, promedio de 24 h, excedencias, promedio mensual). Así se pueden probar solitas contra el cálculo a mano.
- **`recepcion/ports.py` + `recepcion/adapters/`**: EzData no tiene documentación y puede cambiar cuando quiera, entonces el resto del sistema habla con una interfaz (`FuenteDeLecturas`) y solo `adapters/ezdata.py` sabe cómo responde la nube. Para pruebas hay otra fuente que lee de un archivo.

import-linter revisa en cada PR que:

1. ningún módulo importe `reportes`,
2. solo `recepcion.adapters` sepa de EzData,
3. `calculo.dominio` no importe Django.

### Cosas que hay que respetar sí o sí

- **Hora local de Zacatecas en todo**: `USE_TZ=False` y `TIME_ZONE="America/Mexico_City"`, igual en los contenedores y en APScheduler. EzData manda la hora en UTC+8; se convierte en el adaptador y en ningún otro lado.
- **MAC y token de los sensores van cifrados** (y la MAC con una huella HMAC para poder buscarla). Nunca deben salir en logs ni en mensajes de error.
- **Las lecturas solo se insertan**, no se editan ni se borran. Todas entran por `lecturas.services.registrar_lectura`, que evita duplicados con la clave (sensor, hora de la nube, huella).
- Se guarda el dato crudo tal cual llega (el campo `value`), pero **sin el token**.
- Un valor que no vino es `None`, **no** `0`.
- Se redondea solo al final: un decimal en la hora y en el día.
- Se calculan PM2.5 y PM10, y con la misma regla PM1, PM4 y CO2. Temperatura, humedad, VOC y NOx no se calculan.
- Los límites de la norma no se ponen como constantes en el código: están en una tabla con fechas de vigencia y se usa el que aplicaba en la fecha del dato.

---

## Estructura de carpetas

Las apps están en `src/` y esa carpeta se agrega al `PYTHONPATH` (en `manage.py`, en `worker/main.py`, en la config de pytest y en el Dockerfile). Por eso se importan directo, `from recepcion.ports import FuenteDeLecturas`, y **no** `from src.recepcion...`.

Lo marcado con *(después)* todavía no existe, se crea cuando toque.

```
Traviesos.py/
├── docker-compose.yml           # web, worker y db
├── Dockerfile                   # una sola imagen para web y worker
├── .env.example                 # nombres de las variables, sin valores
├── requirements.txt
├── pyproject.toml               # ruff, pytest (pythonpath = ["src"]) e import-linter
├── manage.py
├── .github/workflows/ci.yml     # pruebas, ruff e import-linter en cada PR
│
├── config/                      # settings.py, urls.py, wsgi.py
│
├── src/
│   ├── cuentas/                 # usuarios y roles, login, bloqueo por intentos, permisos,
│   │                            #   comandos crear_admin y precargar_cuentas
│   ├── sensores/                # sensores, ubicación y responsable, colonias, cifrado, alta con HTMX
│   │   └── fixtures/            # catálogo de colonias
│   ├── recepcion/               # tareas de consulta a la nube
│   │   ├── ports.py             # FuenteDeLecturas, LecturaNormalizada, FuenteNoDisponible
│   │   ├── adapters/            # ezdata.py, el único que habla con la nube
│   │   └── tests/fixtures/      # respuestas guardadas de EzData (sin MAC ni token!)
│   ├── lecturas/                # Lectura, registrar_lectura, interpretación del valor que llega
│   ├── calculo/
│   │   └── dominio/             # la norma en Python puro: tipos, cobertura, horario, diario, mensual, redondeo
│   ├── reportes/                # series para las gráficas, láminas del día, reportes diario y mensual
│   ├── operacion/               # por ahora vacío
│   ├── bitacora/                # (después)
│   └── notificaciones/          # (después) correos
│
├── worker/                      # main.py: arranca APScheduler con los dos grupos de hilos
├── templates/                   # base.html, menú, páginas de error
├── static/                      # vendor/ (Bootstrap, HTMX, Chart.js), css/, js/
├── scripts/                     # (después) respaldo y restauración
└── tests/
    ├── datos/                   # datos de prueba compartidos (lecturas reales de un sensor + casos de borde)
    └── integracion/             # pruebas de punta a punta
```

Dentro de cada app, cuando se cree, va lo de la tabla de capas: `models.py`, `services.py`, `selectors.py`, `views.py`, `urls.py`, `forms.py`, `jobs.py`, `templates/<app>/`, `management/commands/` y `tests/`.

> Las carpetas de `src/` ahorita solo tienen un `.gitkeep`, sin `__init__.py`, para que `startapp` no se queje: `python manage.py startapp cuentas src/cuentas` (y así con cada una). En el `apps.py` de cada app queda `name = "cuentas"`, sin el `src.`.

### ¿Dónde pongo lo que voy a programar?

| Si es… | Va en… |
|---|---|
| Una regla de la norma (hora válida, promedio, excedencia…) | `src/calculo/dominio/`, en Python puro y con su prueba |
| Algo que escribe en la base | el `services.py` del módulo |
| Una consulta para una pantalla o reporte | el `selectors.py` del módulo |
| Algo que sabe cómo responde EzData | `src/recepcion/adapters/ezdata.py` y nada más |
| Una tarea programada | el `jobs.py` del módulo, y se registra en `worker/main.py` |
| Gráficas / series de datos | `src/reportes/` |
| Datos de prueba | `tests/datos/` (porfa no dejen datos de prueba sueltos por ahí) |

Si no saben en qué módulo va algo, pregunten antes de crear el archivo.

---

## Git

1. Antes de empezar: `git pull origin develop`.
2. Cada quien trabaja en su rama, que sale de `develop`. Nada directo a `main`.
3. Commits tipo *Conventional Commits*: `feat(recepcion): adaptador de EzData`, `fix(calculo): ...`, etc.
4. PR hacia `develop`, mínimo una vez al día, y lo revisa alguien que no lo programó.

---

## Instalación

Todavía no está, falta el `docker-compose` y el esqueleto de Django. Cuando esté la idea es que sea algo así:

```bash
cp .env.example .env          # y llenar los valores
docker compose up --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py crear_admin
docker compose exec web python manage.py precargar_cuentas
```
