document.addEventListener("DOMContentLoaded", () => {
  const shell = document.getElementById("mareas-app");
  const dataElement = document.getElementById("mareas-stations-data");
  const stationSelect = document.getElementById("mareas-station-select");
  const centerButton = document.getElementById("mareas-chart-center-button");

  if (!shell || !dataElement || !stationSelect) {
    return;
  }

  const stations = JSON.parse(dataElement.textContent);
  const stationsMap = Object.fromEntries(stations.map((station) => [station.key, station]));
  const controls = document.querySelectorAll("[data-day]");

  const fields = {
    updated: document.getElementById("mareas-updated"),
    updatedInline: document.getElementById("mareas-updated-inline"),
    height: document.getElementById("mareas-height"),
    change: document.getElementById("mareas-change"),
    state: document.getElementById("mareas-state"),
    nextHigh: document.getElementById("mareas-next-high"),
    nextLow: document.getElementById("mareas-next-low"),
    temperature: document.getElementById("mareas-temp"),
    wind: document.getElementById("mareas-wind"),
    sky: document.getElementById("mareas-sky"),
    skyItem: document.getElementById("mareas-sky-item"),
    rain: document.getElementById("mareas-rain"),
    momentLabel: document.getElementById("mareas-moment-label"),
    tableBody: document.getElementById("mareas-table-body"),
  };

  const chart = {
    wrap: document.querySelector(".mareas-chart-scroll"),
    svg: document.getElementById("mareas-chart"),
    grid: document.querySelector(".mareas-chart-grid"),
    yLabels: document.getElementById("mareas-chart-y-labels"),
    yLabelsFixed: document.getElementById("mareas-chart-y-axis-fixed"),
    line: document.getElementById("mareas-chart-line"),
    minLine: document.getElementById("mareas-chart-line-min"),
    maxLine: document.getElementById("mareas-chart-line-max"),
    area: document.getElementById("mareas-chart-area"),
    reference: document.getElementById("mareas-chart-reference"),
    points: document.getElementById("mareas-chart-points"),
    overlays: document.getElementById("mareas-chart-overlays"),
    markers: document.getElementById("mareas-chart-markers"),
    labels: document.getElementById("mareas-chart-labels"),
  };

  let activeStationKey = stationSelect.value;
  let activeDaySlug = controls[0]?.dataset.day || "hoy";
  let dragState = null;
  let chartIsScrollable = false;
  const MIN_CHART_WIDTH = 600;
  const CHART_HEIGHT = 300;

  const getChartLayout = () => {
    const containerWidth = (chart.wrap && chart.wrap.clientWidth) || MIN_CHART_WIDTH;
    const svgWidth = Math.max(MIN_CHART_WIDTH, containerWidth);
    const isScrollable = containerWidth < MIN_CHART_WIDTH;

    return {
      svgWidth,
      isScrollable,
      frame: {
        left: 8,
        right: svgWidth - 8,
        top: 20,
        bottom: 260,
      },
      xLabelY: 292,
      xLabelStep: svgWidth < 900 ? 3 : 2,
      yTickCount: 5,
      pointRadius: 5,
      markerWidthFactor: 9,
      markerMinWidth: 96,
      markerRectHeight: 32,
      markerYOffset: 52,
      markerTextYOffset: 30,
      showCurrentLabel: true,
    };
  };

  const centerChartOnCurrentTime = () => {
    if (!chartIsScrollable) {
      return;
    }

    const wrap = chart.wrap;
    const currentMarker = document.querySelector(".mareas-chart-marker.is-current");

    if (!wrap || !currentMarker) {
      return;
    }

    const line = currentMarker.querySelector("line");
    if (!line) {
      return;
    }

    const x = Number(line.getAttribute("x1"));
    if (Number.isNaN(x)) {
      return;
    }

    const svg = document.querySelector(".mareas-chart");
    if (!svg) {
      return;
    }

    if (wrap.scrollWidth <= wrap.clientWidth) {
      return;
    }

    const svgWidth = svg.viewBox?.baseVal?.width || 760;
    const renderedWidth = svg.getBoundingClientRect().width;
    const ratio = renderedWidth / svgWidth;
    const targetLeft = x * ratio - wrap.clientWidth / 2;
    const maxLeft = wrap.scrollWidth - wrap.clientWidth;

    wrap.scrollLeft = Math.max(0, Math.min(targetLeft, maxLeft));
  };

  const stopChartDrag = () => {
    if (!dragState || !chart.wrap) {
      return;
    }

    chart.wrap.classList.remove("is-dragging");
    dragState = null;
  };

  const setupChartDrag = () => {
    if (!chart.wrap || !chart.svg) {
      return;
    }

    chart.wrap.addEventListener("pointerdown", (event) => {
      if (!chartIsScrollable) {
        return;
      }

      if (event.pointerType === "mouse" && event.button !== 0) {
        return;
      }

      dragState = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startScrollLeft: chart.wrap.scrollLeft,
      };

      chart.wrap.classList.add("is-dragging");
      chart.wrap.setPointerCapture?.(event.pointerId);
    });

    chart.wrap.addEventListener("pointermove", (event) => {
      if (!dragState || dragState.pointerId !== event.pointerId) {
        return;
      }

      const deltaX = event.clientX - dragState.startX;
      chart.wrap.scrollLeft = dragState.startScrollLeft - deltaX;
      event.preventDefault();
    });

    chart.wrap.addEventListener("pointerup", stopChartDrag);
    chart.wrap.addEventListener("pointercancel", stopChartDrag);
    chart.wrap.addEventListener("pointerleave", (event) => {
      if (event.pointerType === "mouse") {
        stopChartDrag();
      }
    });
  };

  const parseHour = (value) => {
    const [hours, minutes = "0"] = String(value).split(":");
    return Number.parseInt(hours, 10) + Number.parseInt(minutes, 10) / 60;
  };

  const formatHeight = (value) => `${Number(value).toFixed(2)} m`;

  const formatTideEventMarkup = (label, time, height) => `
    <span class="mareas-event-name">${label}</span>
    <span class="mareas-event-value">${time} · ${formatHeight(height)}</span>
  `;

  const formatDayDate = (day) => {
    if (window.innerWidth > 760) {
      return day.date_label;
    }

    if (day.date_short) {
      return day.date_short;
    }

    if (day.slug && /^\d{4}-\d{2}-\d{2}$/.test(day.slug)) {
      const [, month, date] = day.slug.split("-");
      return `${date}/${month}`;
    }

    return day.date_label;
  };

  const buildYAxisScale = (values) => {
    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);
    const padding = 0.1;
    const rawMin = Math.max(0, minValue - padding);
    const rawMax = maxValue + padding;
    const rawRange = rawMax - rawMin;
    const step = rawRange <= 0.4 ? 0.05 : 0.1;
    const domainMin = Math.max(0, Math.floor(rawMin / step) * step);
    const domainMax = Math.ceil(rawMax / step) * step;
    const alignedRange = domainMax - domainMin;
    const steps = 4;
    const tickStep = Math.ceil((alignedRange / steps) / step) * step;
    const adjustedMax = domainMin + tickStep * steps;
    const ticks = Array.from({ length: 5 }, (_, index) => (
      adjustedMax - tickStep * index
    ));

    return { domainMin, domainMax: adjustedMax, ticks };
  };

  const buildPath = (projected) =>
    projected
      .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
      .join(" ");

  const projectY = (value, domainMin, domainMax, frameTop, frameBottom) => (
    frameBottom - ((value - domainMin) / (domainMax - domainMin)) * (frameBottom - frameTop)
  );

  const projectSeries = (series, domainMin, domainMax, width, height) =>
    series.map((point) => {
      const { frame } = getChartLayout();
      const x = frame.left + (parseHour(point.time) / 24) * width;
      const y = projectY(point.height, domainMin, domainMax, frame.top, frame.bottom);
      return { ...point, x, y, hourValue: parseHour(point.time) };
    });

  const interpolateHeight = (series, targetHour) => {
    if (targetHour <= series[0].hourValue) {
      return series[0].height;
    }
    if (targetHour >= series[series.length - 1].hourValue) {
      return series[series.length - 1].height;
    }

    for (let index = 0; index < series.length - 1; index += 1) {
      const start = series[index];
      const end = series[index + 1];
      if (start.hourValue <= targetHour && targetHour <= end.hourValue) {
        const span = end.hourValue - start.hourValue;
        const ratio = span === 0 ? 0 : (targetHour - start.hourValue) / span;
        return start.height + (end.height - start.height) * ratio;
      }
    }

    return series[series.length - 1].height;
  };

  const renderChart = (selectedDay) => {
    const layout = getChartLayout();
    const chartFrame = layout.frame;

    chartIsScrollable = layout.isScrollable;
    chart.wrap.classList.toggle("is-scrollable", layout.isScrollable);

    if (chart.svg) {
      chart.svg.setAttribute("viewBox", `0 0 ${layout.svgWidth} ${CHART_HEIGHT}`);
      chart.svg.setAttribute("width", layout.isScrollable ? String(layout.svgWidth) : "100%");
    }

    if (centerButton) {
      centerButton.style.pointerEvents = layout.isScrollable ? "" : "none";
      centerButton.classList.toggle("is-functional", layout.isScrollable);
    }

    const points = selectedDay.chart_points || [];
    const minPoints = selectedDay.chart_min_points || points;
    const maxPoints = selectedDay.chart_max_points || points;

    if (!points.length) {
      return;
    }

    const currentHour = parseHour(selectedDay.current_marker.time);
    const scaleValues = [
      ...points.map((point) => point.height),
      ...minPoints.map((point) => point.height),
      ...points.map((point) => point.height),
      ...maxPoints.map((point) => point.height),
      selectedDay.current_marker.height,
      selectedDay.next_low_marker.height,
      selectedDay.next_high_marker.height
    ];
    const yScale = buildYAxisScale(scaleValues);
    const width = chartFrame.right - chartFrame.left;
    const height = chartFrame.bottom - chartFrame.top;
    const projected = projectSeries(points, yScale.domainMin, yScale.domainMax, width, height);
    const projectedMin = projectSeries(minPoints, yScale.domainMin, yScale.domainMax, width, height);
    const projectedMax = projectSeries(maxPoints, yScale.domainMin, yScale.domainMax, width, height);

    const linePath = buildPath(projected);
    const minLinePath = buildPath(projectedMin);
    const maxLinePath = buildPath(projectedMax);

    const areaPath = `${linePath} L ${projected[projected.length - 1].x.toFixed(2)} ${chartFrame.bottom} L ${projected[0].x.toFixed(2)} ${chartFrame.bottom} Z`;

    chart.line.setAttribute("d", linePath);
    chart.minLine.setAttribute("d", minLinePath);
    chart.maxLine.setAttribute("d", maxLinePath);
    chart.area.setAttribute("d", areaPath);

    chart.points.innerHTML = projected
      .map(
        (point) =>
          `<circle cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="${layout.pointRadius.toFixed(1)}"></circle>`
      )
      .join("");

    chart.labels.innerHTML = projected
      .filter((point) => {
        const wholeHour = Math.round(point.hourValue);
        const isWholeHour = Math.abs(point.hourValue - wholeHour) < 0.01;
        return isWholeHour && wholeHour % layout.xLabelStep === 0;
      })
      .map((point, index, items) => {
        const hourLabel = String(Math.round(point.hourValue)).padStart(2, "0");
        const isFirst = index === 0;
        const isLast = index === items.length - 1;
        const anchor = isFirst ? "start" : isLast ? "end" : "middle";
        const x = isFirst
          ? point.x + 4
          : isLast
            ? point.x - 4
            : point.x;

        return `<text x="${x.toFixed(2)}" y="${layout.xLabelY}" text-anchor="${anchor}">${hourLabel}</text>`;
      })
      .join("");

    if (chart.grid) {
      chart.grid.innerHTML = yScale.ticks
        .map((value) => {
          const y = projectY(value, yScale.domainMin, yScale.domainMax, chartFrame.top, chartFrame.bottom);
          return `<line x1="0" y1="${y.toFixed(2)}" x2="${layout.svgWidth}" y2="${y.toFixed(2)}"></line>`;
        })
        .join("");
    }

    if (chart.yLabels) {
      chart.yLabels.style.display = "none";
    }

    if (chart.yLabelsFixed) {
      chart.yLabelsFixed.innerHTML = yScale.ticks
        .map((value) => {
          const y = projectY(value, yScale.domainMin, yScale.domainMax, chartFrame.top, chartFrame.bottom);
          return `<span style="top:${y.toFixed(2)}px">${value.toFixed(2)} m</span>`;
        })
        .join("");
    }

    const currentX = chartFrame.left + (currentHour / 24) * width;
    if (chart.reference) {
      chart.reference.innerHTML = `
        <line class="mareas-chart-current-line" x1="${currentX.toFixed(2)}" y1="${chartFrame.top}" x2="${currentX.toFixed(2)}" y2="${chartFrame.bottom}"></line>
      `;
    }

    if (chart.overlays) {
      chart.overlays.innerHTML = "";
    }

    const markers = [
      { ...selectedDay.current_marker, className: "is-current" },
      { ...selectedDay.next_high_marker, className: "is-high" },
      { ...selectedDay.next_low_marker, className: "is-low" },
    ];

    chart.markers.innerHTML = markers
      .map((marker) => {
        const markerHour = parseHour(marker.time);
        const markerX = projected.reduce((closest, point) => {
          const distance = Math.abs(point.hourValue - markerHour);
          return distance < closest.distance ? { x: point.x, distance } : closest;
        }, { x: chartFrame.left, distance: Number.POSITIVE_INFINITY }).x;
        const markerY = projectY(marker.height, yScale.domainMin, yScale.domainMax, chartFrame.top, chartFrame.bottom);
        const markerText =
          marker.className === "is-current"
            ? `${marker.label} ${formatHeight(marker.height)}`
            : `${marker.label} ${marker.time} · ${formatHeight(marker.height)}`;
        const markerWidth = Math.max(layout.markerMinWidth, markerText.length * layout.markerWidthFactor);
        const markerLabelX = Math.min(
          chartFrame.right - markerWidth / 2 - 8,
          Math.max(chartFrame.left + markerWidth / 2 + 8, markerX)
        );
        const markerRectX = markerLabelX - markerWidth / 2;
        const shouldShowLabel = marker.className !== "is-current" || layout.showCurrentLabel;

        const markerLabel = shouldShowLabel
          ? `
            <rect x="${markerRectX.toFixed(2)}" y="${Math.max(
              chartFrame.top,
              markerY - layout.markerYOffset
            ).toFixed(2)}" width="${markerWidth.toFixed(2)}" height="${layout.markerRectHeight}" rx="${
              layout.markerRectHeight / 2
            }"></rect>
            <text x="${markerLabelX.toFixed(2)}" y="${Math.max(
              chartFrame.top + 18,
              markerY - layout.markerTextYOffset
            ).toFixed(2)}" text-anchor="middle">${markerText}</text>
          `
          : "";

        return `
          <g class="mareas-chart-marker ${marker.className}">
            <line x1="${markerX.toFixed(2)}" y1="${chartFrame.top}" x2="${markerX.toFixed(2)}" y2="${chartFrame.bottom}"></line>
            <circle cx="${markerX.toFixed(2)}" cy="${markerY.toFixed(2)}" r="7"></circle>
            ${markerLabel}
          </g>
        `;
      })
      .join("");

    requestAnimationFrame(centerChartOnCurrentTime);
  };

  const getSelectedDay = (stationKey, daySlug) => {
    const station = stationsMap[stationKey];

    if (!station) {
      return null;
    }

    return station.days.find((day) => day.slug === daySlug) || station.days[0] || null;
  };

  const syncDayButtons = (station) => {
    controls.forEach((control) => {
      const day = station.days.find((item) => item.slug === control.dataset.day);
      const isActive = control.dataset.day === activeDaySlug;
      control.classList.toggle("is-active", isActive);
      control.setAttribute("aria-pressed", isActive ? "true" : "false");

      if (day) {
        const label = control.querySelector("span");
        const dateLabel = control.querySelector("small");

        if (label) {
          label.textContent = day.label;
        }

        if (dateLabel) {
          dateLabel.textContent = formatDayDate(day);
        }
      }
    });
  };

  const renderTable = (selectedDay) => {
    if (!fields.tableBody) {
      return;
    }

    const rows = selectedDay.table_rows || [];
    fields.tableBody.innerHTML = rows
      .map(
        (row) => `
          <tr>
            <td class="col-key">${row.time}</td>
            <td class="col-key">${row.avg}</td>
            <td>${row.min}</td>
            <td>${row.max}</td>
          </tr>
        `
      )
      .join("");
  };

  const applySelection = () => {
    const station = stationsMap[activeStationKey];
    const selectedDay = getSelectedDay(activeStationKey, activeDaySlug);

    if (!station || !selectedDay) {
      return;
    }

    activeDaySlug = selectedDay.slug;

    fields.updated.textContent = selectedDay.updated_at;
    if (fields.updatedInline) {
      fields.updatedInline.textContent = selectedDay.updated_at;
    }
    fields.height.textContent = selectedDay.height_now;
    fields.change.textContent = selectedDay.height_change;
    fields.state.textContent = selectedDay.state;
    fields.nextHigh.innerHTML = formatTideEventMarkup(
      "Pleamar",
      selectedDay.next_high,
      selectedDay.next_high_marker.height
    );
    fields.nextLow.innerHTML = formatTideEventMarkup(
      "Bajamar",
      selectedDay.next_low,
      selectedDay.next_low_marker.height
    );
    fields.temperature.textContent = selectedDay.temperature;
    fields.wind.textContent = selectedDay.wind;
    if (fields.sky) {
      fields.sky.textContent = selectedDay.sky;
    }
    if (fields.skyItem) {
      fields.skyItem.hidden = !selectedDay.has_sky;
    }
    fields.rain.textContent = selectedDay.rain;
    if (fields.momentLabel) {
      fields.momentLabel.textContent =
        shell.dataset.visualMoment.charAt(0).toUpperCase() +
        shell.dataset.visualMoment.slice(1);
    }
    renderChart(selectedDay);
    syncDayButtons(station);
    renderTable(selectedDay);
  };

  controls.forEach((control) => {
    control.addEventListener("click", () => {
      activeDaySlug = control.dataset.day;
      applySelection();
    });
  });

  stationSelect.addEventListener("change", () => {
    activeStationKey = stationSelect.value;
    applySelection();
  });

  if (centerButton) {
    centerButton.addEventListener("click", () => {
      requestAnimationFrame(centerChartOnCurrentTime);
    });
  }

  const chartResizeObserver = new ResizeObserver(() => {
    requestAnimationFrame(applySelection);
  });
  chartResizeObserver.observe(chart.wrap);

  setupChartDrag();
  applySelection();
});

document.addEventListener("DOMContentLoaded", () => {
  const lightbox = document.getElementById("mareas-lightbox");
  const lightboxImg = document.getElementById("mareas-lightbox-img");
  const closeButton = lightbox?.querySelector(".mareas-lightbox-close");
  const triggers = document.querySelectorAll(".mareas-shot-btn");

  if (!lightbox || !lightboxImg || !triggers.length) {
    return;
  }

  // <main> tiene position:relative + z-index, así que crea su propio stacking
  // context: ningún z-index de acá adentro puede superar al header/back-to-top
  // mientras el lightbox siga siendo descendiente de <main>. Lo movemos a
  // body para que quede hermano de esos elementos y el z-index sí compare.
  document.body.appendChild(lightbox);

  const openLightbox = (src, alt) => {
    lightboxImg.src = src;
    lightboxImg.alt = alt || "";
    lightbox.hidden = false;
  };

  const closeLightbox = () => {
    lightbox.hidden = true;
    lightboxImg.src = "";
  };

  triggers.forEach((trigger) => {
    trigger.addEventListener("click", () => {
      openLightbox(trigger.dataset.lightboxSrc, trigger.dataset.lightboxAlt);
    });
  });

  closeButton?.addEventListener("click", closeLightbox);

  lightbox.addEventListener("click", (event) => {
    if (event.target === lightbox) {
      closeLightbox();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !lightbox.hidden) {
      closeLightbox();
    }
  });
});
