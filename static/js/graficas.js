// Dibuja las gráficas de cada lámina del reporte diario (y de las láminas del mensual, que llegan
// después con HTMX). Cada lámina dice en `data-lamina` el id del <script type="application/json">
// con sus series. El eje horizontal va en minutos desde las 00:00 del día, para no depender de
// la zona horaria del navegador.
(function () {
  "use strict";

  const COLORES = ["#0E5F58", "#B4651B", "#3D5A99", "#8E3B73", "#5B7A2A", "#8C3B2E", "#55615C"];
  const MINUTOS_DEL_DIA = 24 * 60;

  function minutosDesdeMedianoche(iso) {
    // "2026-09-26T12:18:11" -> 738.18
    const [h, m, s] = iso.slice(11, 19).split(":").map(Number);
    return h * 60 + m + s / 60;
  }

  function horaLegible(minutos) {
    const h = Math.floor(minutos / 60);
    const m = Math.floor(minutos % 60);
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0");
  }

  function dibujar(lamina, grafica) {
    const lienzo = lamina.querySelector('canvas[data-variable="' + grafica.variable + '"]');
    if (!lienzo) {
      return;
    }
    const conjuntos = grafica.series.map(function (serie, i) {
      return {
        label: serie.sensor,
        data: serie.puntos.map(function (punto) {
          return { x: minutosDesdeMedianoche(punto[0]), y: punto[1] };
        }),
        borderColor: COLORES[i % COLORES.length],
        backgroundColor: COLORES[i % COLORES.length],
        borderWidth: 2,
        pointRadius: 1.5,
        spanGaps: false,
      };
    });

    new Chart(lienzo, {
      type: "line",
      data: { datasets: conjuntos },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        parsing: false,
        interaction: { mode: "nearest", intersect: false },
        plugins: {
          legend: { display: conjuntos.length > 1, position: "bottom" },
          tooltip: {
            callbacks: {
              title: function (elementos) {
                return elementos.length ? horaLegible(elementos[0].parsed.x) : "";
              },
              label: function (elemento) {
                return elemento.dataset.label + ": " + elemento.parsed.y + " " + grafica.unidad;
              },
            },
          },
        },
        scales: {
          x: {
            type: "linear",
            min: 0,
            max: MINUTOS_DEL_DIA,
            ticks: {
              stepSize: 180,
              callback: function (valor) {
                return horaLegible(valor).slice(0, 2);
              },
            },
          },
          y: {
            beginAtZero: true,
            title: { display: true, text: grafica.unidad },
          },
        },
      },
    });
  }

  function dibujarLaminas(raiz) {
    if (typeof Chart === "undefined") {
      return;
    }
    raiz.querySelectorAll("[data-lamina]:not([data-dibujada])").forEach(function (lamina) {
      const fuente = document.getElementById(lamina.dataset.lamina);
      if (!fuente) {
        return;
      }
      lamina.dataset.dibujada = "1";
      JSON.parse(fuente.textContent).forEach(function (grafica) {
        dibujar(lamina, grafica);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    dibujarLaminas(document);
  });
  // Una lámina que llega con HTMX reemplaza a su marcador, así que se busca en todo el documento.
  document.addEventListener("htmx:afterSettle", function () {
    dibujarLaminas(document);
  });
})();
