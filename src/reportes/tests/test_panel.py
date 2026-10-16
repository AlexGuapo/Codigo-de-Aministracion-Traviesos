import time
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from calculo.models import EstadoCalculo, Periodo, ValorCalculado
from cuentas.models import Cuenta, Origen, Rol
from cuentas.models import Estado as EstadoCuenta
from cuentas.services import crear_administrador
from lecturas.models import Lectura
from reportes.selectors import (
    Estado,
    EstadoDia,
    estado_red,
    hueco_mas_largo,
    ultima_hora_cerrada,
)
from sensores.models import Colonia, Sensor, Ubicacion

CONTRASENA = "contrasena-de-prueba"
HOY = date(2026, 10, 14)


def a_las(h, m=0, dia=HOY):
    return datetime(dia.year, dia.month, dia.day, h, m)


@pytest.fixture
def admin(db):
    return crear_administrador("doctora@ejemplo.mx", "Doctora", CONTRASENA)


@pytest.fixture
def colonia(db):
    return Colonia.objects.create(nombre="Centro", municipio="Zacatecas")


def crear_sensor(nombre, colonia=None, admin=None, desde=date(2026, 9, 1), **extra):
    sensor = Sensor.objects.create(
        nombre_corto=nombre,
        mac_cifrada="mac-cifrada",
        mac_huella=nombre.ljust(64, "x"),
        token_cifrado="token-cifrado",
        lecturas_desde=desde,
        **extra,
    )
    if colonia is not None:
        Ubicacion.objects.create(
            sensor=sensor,
            colonia=colonia,
            vigente_desde=datetime(2026, 9, 1),
            registrada_por=admin,
        )
    return sensor


def lectura(sensor, hora, intervalo_s=1800):
    return Lectura.objects.create(
        sensor=sensor,
        hora=hora,
        hora_nube_original="x",
        ruta="history",
        origen="nube",
        pm2_5=10.0,
        intervalo_s=intervalo_s,
        huella_valores=f"{sensor.pk}-{hora.isoformat()}".ljust(64, "x"),
        crudo="{}",
    )


def valor_hora(sensor, inicio, variable, valor):
    ValorCalculado.objects.create(
        sensor=sensor,
        variable=variable,
        periodo=Periodo.HORA,
        inicio=inicio,
        cobertura_min=Decimal("60"),
        lecturas_contadas=2,
        es_valido=valor is not None,
        valor=valor,
        version_calculo="prueba",
        estado=EstadoCalculo.CERRADO,
    )


def dia_valido(sensor, fecha, valido=True):
    ValorCalculado.objects.create(
        sensor=sensor,
        variable="pm25",
        periodo=Periodo.DIA,
        inicio=datetime.combine(fecha, datetime.min.time()),
        horas_validas=20 if valido else 10,
        es_valido=valido,
        valor=Decimal("12.0") if valido else None,
        valor_entero=12 if valido else None,
        version_calculo="prueba",
        estado=EstadoCalculo.CERRADO,
    )


def de(red, nombre):
    return next(sensor for sensor in red.sensores if sensor.nombre == nombre)


# Estado de cada sensor


def test_a_las_16_09_transmite_y_a_las_16_11_esta_fuera_de_operacion(db):
    sensor = crear_sensor("S-1")
    lectura(sensor, a_las(15, 5))
    assert de(estado_red(a_las(16, 9)), "S-1").estado == Estado.TRANSMITIENDO
    assert de(estado_red(a_las(16, 11)), "S-1").estado == Estado.FUERA_DE_OPERACION


def test_sin_intervalo_el_corte_es_de_65_minutos(db):
    sensor = crear_sensor("S-1")
    lectura(sensor, a_las(15, 0), intervalo_s=None)
    assert de(estado_red(a_las(16, 5)), "S-1").estado == Estado.TRANSMITIENDO
    assert de(estado_red(a_las(16, 6)), "S-1").estado == Estado.FUERA_DE_OPERACION


def test_un_sensor_sin_lecturas_lo_dice(db):
    crear_sensor("S-1")
    sensor = de(estado_red(a_las(12)), "S-1")
    assert sensor.estado == Estado.SIN_LECTURAS
    assert sensor.ultima_lectura is None


def test_los_dados_de_baja_no_aparecen(db):
    crear_sensor("S-1", estado="dado_de_baja", dado_de_baja_en=datetime(2026, 10, 1))
    assert estado_red(a_las(12)).sensores == []


def test_trae_la_colonia_vigente(admin, colonia):
    crear_sensor("S-1", colonia, admin)
    sensor = de(estado_red(a_las(12)), "S-1")
    assert sensor.colonia == "Centro"
    assert sensor.municipio == "Zacatecas"


def test_orden_fuera_de_operacion_primero_del_mas_antiguo_al_mas_reciente(db):
    for nombre, hora in [("S-A", a_las(11)), ("S-B", a_las(7)), ("S-C", a_las(9)), ("S-D", None)]:
        sensor = crear_sensor(nombre)
        if hora:
            lectura(sensor, hora)
    lectura(Sensor.objects.get(nombre_corto="S-A"), a_las(11, 50))
    red = estado_red(a_las(12))
    assert [s.nombre for s in red.sensores] == ["S-B", "S-C", "S-A", "S-D"]
    assert [s.nombre for s in red.fuera_de_operacion] == ["S-B", "S-C"]


# Partículas de la última hora cerrada


def test_la_ultima_hora_cerrada():
    assert ultima_hora_cerrada(a_las(16, 11)) == a_las(14)
    assert ultima_hora_cerrada(a_las(16, 20)) == a_las(15)


def test_pm25_y_pm10_de_la_ultima_hora_cerrada(db):
    sensor = crear_sensor("S-1")
    lectura(sensor, a_las(15, 5))
    valor_hora(sensor, a_las(14), "pm25", Decimal("18.4"))
    valor_hora(sensor, a_las(14), "pm10", None)
    datos = de(estado_red(a_las(16, 0)), "S-1")
    assert datos.pm25 == Decimal("18.4")
    assert datos.pm10 is None  # «datos insuficientes»


# Continuidad de 30 días


def test_continuidad_valido_incompleto_sin_lecturas_y_hoy(db):
    sensor = crear_sensor("S-1", desde=date(2026, 10, 10))
    dia_valido(sensor, date(2026, 10, 10))
    lectura(sensor, a_las(8, dia=date(2026, 10, 11)))
    lectura(sensor, a_las(8))
    datos = de(estado_red(a_las(12)), "S-1")
    assert [dia.estado for dia in datos.continuidad] == [
        EstadoDia.VALIDO,
        EstadoDia.INCOMPLETO,
        EstadoDia.SIN_LECTURAS,
        EstadoDia.SIN_LECTURAS,
        EstadoDia.EN_CURSO,
    ]
    assert datos.porcentaje_validos == 25


def test_la_continuidad_cubre_30_dias(db):
    crear_sensor("S-1", desde=date(2026, 1, 1))
    datos = de(estado_red(a_las(12)), "S-1")
    assert len(datos.continuidad) == 30
    assert datos.continuidad[-1].fecha == HOY


def test_el_porcentaje_de_la_red_suma_todos_los_sensores(db):
    uno = crear_sensor("S-1", desde=date(2026, 10, 12))
    dos = crear_sensor("S-2", desde=date(2026, 10, 12))
    dia_valido(uno, date(2026, 10, 12))
    dia_valido(uno, date(2026, 10, 13))
    dia_valido(dos, date(2026, 10, 12))
    assert estado_red(a_las(12)).porcentaje_validos == 75


# Hueco más largo


def test_el_hueco_mas_largo_cuenta_hasta_ahora(db):
    sensor = crear_sensor("S-1")
    lectura(sensor, a_las(8, dia=date(2026, 10, 1)))
    lectura(sensor, a_las(8, dia=date(2026, 10, 13)))
    lectura(sensor, a_las(8, 30, dia=date(2026, 10, 13)))
    assert hueco_mas_largo(sensor.pk, a_las(12)) == timedelta(days=12)


def test_un_envio_perdido_no_es_hueco(db):
    sensor = crear_sensor("S-1")
    lectura(sensor, a_las(10))
    lectura(sensor, a_las(11))
    assert hueco_mas_largo(sensor.pk, a_las(11, 10)) == timedelta(0)


def test_sin_lecturas_no_hay_hueco(db):
    sensor = crear_sensor("S-1")
    assert hueco_mas_largo(sensor.pk, a_las(12)) is None


# Pantalla


def entrar(client, cuenta):
    client.post(reverse("cuentas:entrar"), {"correo": cuenta.correo, "contrasena": CONTRASENA})
    return client


def test_el_panel_muestra_cada_sensor_sin_mac_ni_token(client, admin, colonia):
    sensor = crear_sensor("S-1", colonia, admin)
    lectura(sensor, datetime.now() - timedelta(minutes=10))
    html = entrar(client, admin).get(reverse("reportes:panel_red")).content.decode()
    assert "S-1" in html
    assert "Zacatecas · Centro" in html
    assert "Transmitiendo" in html
    assert "mac-cifrada" not in html and "token-cifrado" not in html
    assert "batería" not in html.lower().replace("la batería o el wifi", "")


def test_el_panel_se_actualiza_solo_cada_15_minutos(client, admin):
    html = entrar(client, admin).get(reverse("reportes:panel_red")).content.decode()
    assert 'hx-trigger="every 15m"' in html
    assert "X-Consulta-Automatica" in html


def test_elegir_un_sensor_devuelve_solo_el_contenido(client, admin):
    uno = crear_sensor("S-1")
    crear_sensor("S-2")
    respuesta = entrar(client, admin).get(
        reverse("reportes:panel_red"), {"sensor": uno.pk}, HTTP_HX_REQUEST="true"
    )
    html = respuesta.content.decode()
    assert "<html" not in html
    assert respuesta.context["elegido"].id == uno.pk


def test_el_filtro_deja_solo_los_fuera_de_operacion(client, admin):
    viejo = crear_sensor("S-1")
    lectura(viejo, datetime.now() - timedelta(hours=3))
    nuevo = crear_sensor("S-2")
    lectura(nuevo, datetime.now() - timedelta(minutes=5))
    respuesta = entrar(client, admin).get(reverse("reportes:panel_red"), {"filtro": "fuera"})
    assert [s.nombre for s in respuesta.context["visibles"]] == ["S-1"]


def test_otro_rol_no_ve_el_panel(client, db):
    vecino = Cuenta(
        correo="vecino@ejemplo.mx",
        nombre="Vecino",
        rol=Rol.VECINO_CON_SENSOR,
        estado=EstadoCuenta.VALIDADA,
        origen=Origen.PRECARGA,
    )
    vecino.set_password(CONTRASENA)
    vecino.save()
    assert entrar(client, vecino).get(reverse("reportes:panel_red")).status_code == 403


def test_carga_en_menos_de_5_segundos_con_7_sensores(client, admin, colonia):
    ahora = datetime.now()
    for numero in range(7):
        sensor = crear_sensor(f"S-{numero}", colonia, admin)
        for paso in range(30 * 48):
            lectura(sensor, ahora - timedelta(minutes=30 * paso + numero))
    entrar(client, admin)
    inicio = time.monotonic()
    assert client.get(reverse("reportes:panel_red")).status_code == 200
    assert time.monotonic() - inicio < 5
