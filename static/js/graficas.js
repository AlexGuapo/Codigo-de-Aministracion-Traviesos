// Dibuja las gráficas del reporte diario a partir de las series que deja la página en
// <script id="series" type="application/json">. El eje horizontal va en minutos desde las
// 00:00 del día, para no depender de la zona horaria del navegador.
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

  function dibujar(grafica) {
    const lienzo = document.getElementById("grafica-" + grafica.variable);
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

  document.addEventListener("DOMContentLoaded", function () {
    const fuente = document.getElementById("series");
    if (!fuente || typeof Chart === "undefined") {
      return;
    }
    JSON.parse(fuente.textContent).forEach(dibujar);
  });
})();
