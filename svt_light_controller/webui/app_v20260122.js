const state = {
  controllers: [],
  lights: [],
  solar: null,
  editingIndex: null,
  filteredControllers: [],
  visibleCount: 0,
  selection: new Set(),
  pageSize: 20,
  timeOffsetMinutes: 0,
};
let currentSelectedLights = [];

const controllerTable = document.getElementById("controller-table");
const editor = document.getElementById("editor");
const editorTitle = document.getElementById("editor-title");
const form = document.getElementById("controller-form");
const addBtn = document.getElementById("add-btn");
const cancelBtn = document.getElementById("cancel-btn");
const saveMasterBtn = document.getElementById("save-master");
const masterSection = document.getElementById("master");
const toggleMasterBtn = document.getElementById("toggle-master");
const hideMasterBtn = document.getElementById("hide-master");
const nameInput = document.getElementById("name");
const uniqueInput = document.getElementById("unique_id");
const errorText = document.getElementById("form-error");
const circadianToggle = document.getElementById("circadian-enabled");
const useMasterBrightnessToggle = document.getElementById("use-master-brightness");
const useMasterColorToggle = document.getElementById("use-master-color-temp");
const circadianFields = document.getElementById("circadian-fields");
const brightnessCanvas = document.getElementById("curve-brightness");
const colorTempCanvas = document.getElementById("curve-color-temp");
const masterBrightnessCanvas = document.getElementById("master-curve-brightness");
const masterColorTempCanvas = document.getElementById("master-curve-color-temp");
const masterSolarBrightnessToggle = document.getElementById("master-solar-brightness");
const masterSolarColorToggle = document.getElementById("master-solar-color-temp");
const circadianIntervalInput = document.getElementById("circadian-interval");
const wakeupIntervalInput = document.getElementById("wakeup-interval");
const weatherEnabledToggle = document.getElementById("weather-enabled");
const weatherCloudInput = document.getElementById("weather-cloud-sensor");
const weatherUvInput = document.getElementById("weather-uv-sensor");
const weatherVisibilityInput = document.getElementById("weather-visibility-sensor");
const weatherCodeInput = document.getElementById("weather-code-sensor");
const weatherUvMaxInput = document.getElementById("weather-uv-max");
const weatherVisibilityMaxInput = document.getElementById("weather-visibility-max");
const weatherMaxReductionInput = document.getElementById("weather-max-reduction");
const smoothBrightnessRateInput = document.getElementById("smooth-brightness-rate");
const smoothCtRateInput = document.getElementById("smooth-ct-rate");
const awayStartInput = document.getElementById("away-start");
const awayEndInput = document.getElementById("away-end");
const awayMinMinutesInput = document.getElementById("away-min-minutes");
const awayMaxMinutesInput = document.getElementById("away-max-minutes");
const awayOffsetMinutesInput = document.getElementById("away-offset-minutes");
const sleepBrightnessInput = document.getElementById("sleep-brightness");
const sleepCtInput = document.getElementById("sleep-ct");
const sleepHueInput = document.getElementById("sleep-hue");
const sleepSatInput = document.getElementById("sleep-sat");
const wakeupDurationInput = document.getElementById("wakeup-duration");
const wakeupStartBrightnessInput = document.getElementById("wakeup-start-brightness");
const retryEnabledToggle = document.getElementById("retry-enabled");
const retryDelayInput = document.getElementById("retry-delay");
const retryMaxInput = document.getElementById("retry-max");
const retryTolBrightnessInput = document.getElementById("retry-tol-brightness");
const retryTolCtInput = document.getElementById("retry-tol-ct");
const retryTolHsInput = document.getElementById("retry-tol-hs");
const retryTolRgbInput = document.getElementById("retry-tol-rgb");
const retryTolXyInput = document.getElementById("retry-tol-xy");
const sleepUseMasterToggle = document.getElementById("sleep-use-master");
const sleepBrightnessOverrideInput = document.getElementById("sleep-brightness-override");
const sleepCtOverrideInput = document.getElementById("sleep-ct-override");
const sleepHueOverrideInput = document.getElementById("sleep-hue-override");
const sleepSatOverrideInput = document.getElementById("sleep-sat-override");
const wakeupUseMasterToggle = document.getElementById("wakeup-use-master");
const wakeupDurationOverrideInput = document.getElementById("wakeup-duration-override");
const wakeupStartBrightnessOverrideInput = document.getElementById("wakeup-start-brightness-override");
const solarBrightnessToggle = document.getElementById("solar-brightness");
const solarColorToggle = document.getElementById("solar-color-temp");
const brightnessMinInput = document.getElementById("brightness-min");
const brightnessMaxInput = document.getElementById("brightness-max");
const brightnessMinValue = document.getElementById("brightness-min-value");
const brightnessMaxValue = document.getElementById("brightness-max-value");
const ctMinInput = document.getElementById("ct-min");
const ctMaxInput = document.getElementById("ct-max");
const ctMinValue = document.getElementById("ct-min-value");
const ctMaxValue = document.getElementById("ct-max-value");
const weatherMinInput = document.getElementById("weather-min");
const weatherMinValue = document.getElementById("weather-min-value");
const controllerSearch = document.getElementById("controller-search");
const controllerSort = document.getElementById("controller-sort");
const filterCircadian = document.getElementById("filter-circadian");
const filterMasterBrightness = document.getElementById("filter-master-brightness");
const filterMasterColor = document.getElementById("filter-master-color");
const bulkActions = document.getElementById("bulk-actions");
const bulkCount = document.getElementById("bulk-count");
const bulkSelectAll = document.getElementById("bulk-select-all");
const bulkClear = document.getElementById("bulk-clear");
const solarControls = {
  brightness: solarBrightnessToggle,
  color: solarColorToggle,
};

let brightnessCurve = null;
let colorTempCurve = null;
let masterBrightnessCurve = null;
let masterColorTempCurve = null;
let editorCustomBrightness = null;
let editorCustomColorTemp = null;
let lastUseMasterBrightness = false;
let lastUseMasterColor = false;
let editorBrightnessEnabled = true;
let editorColorTempEnabled = true;
let graphRefreshTimer = null;
let graphRefreshSeconds = 15;

const curveDefaults = {
  brightness: [
    { t: 0, v: 20 },
    { t: 360, v: 80 },
    { t: 720, v: 200 },
    { t: 1080, v: 130 },
    { t: 1320, v: 40 },
  ],
  color_temp: [
    { t: 0, v: 2200 },
    { t: 360, v: 2800 },
    { t: 720, v: 5200 },
    { t: 1080, v: 3600 },
    { t: 1320, v: 2600 },
  ],
};

const limitDefaults = {
  brightness_min_pct: 1,
  brightness_max_pct: 100,
  ct_min_kelvin: 2000,
  ct_max_kelvin: 6500,
  weather_min_kelvin: 2300,
};
const ctDefaultBounds = {
  min: 1500,
  max: 8000,
};
let currentCtBounds = { ...ctDefaultBounds };

const basePath = window.location.pathname.endsWith("/")
  ? window.location.pathname
  : `${window.location.pathname}/`;

function coalesce(value, fallback) {
  return value !== null && value !== undefined ? value : fallback;
}

function getPath(obj, path) {
  let current = obj;
  for (let i = 0; i < path.length; i += 1) {
    if (current === null || current === undefined) {
      return undefined;
    }
    current = current[path[i]];
  }
  return current;
}

async function fetchJson(path) {
  const target = path.startsWith("http") || path.startsWith("/") ? path : `${basePath}${path}`;
  const resp = await fetch(target);
  if (!resp.ok) {
    throw new Error(`Failed to fetch ${path}`);
  }
  return resp.json();
}

async function loadData() {
  const [config, lightData] = await Promise.all([
    fetchJson("api/config"),
    fetchJson("api/lights"),
  ]);
  let solarData = null;
  try {
    solarData = await fetchJson("api/solar");
  } catch (err) {
    solarData = null;
  }
  state.controllers = Array.isArray(config.controllers) ? config.controllers : [];
  state.lights = Array.isArray(lightData.lights) ? lightData.lights : [];
  state.solar = solarData || null;
  if (state.solar && Number.isFinite(state.solar.now_minutes)) {
    const localNow = new Date();
    const localMinutes = localNow.getHours() * 60 + localNow.getMinutes() + localNow.getSeconds() / 60;
    state.timeOffsetMinutes = state.solar.now_minutes - localMinutes;
  }
  if (state.solar && Number.isFinite(state.solar.now_epoch)) {
    state.timeOffsetMinutes =
      (state.solar.now_epoch - Date.now() / 1000) / 60;
  }
  const validKeys = new Set(state.controllers.map((controller) => normalizeControllerKey(controller)));
  state.selection = new Set([...state.selection].filter((key) => validKeys.has(key)));
  if (circadianIntervalInput) {
    try {
      const runtime = await fetchJson("api/runtime");
      if (circadianIntervalInput) {
        circadianIntervalInput.value = runtime.circadian_interval;
        graphRefreshSeconds = Number.isFinite(runtime.circadian_interval)
          ? Math.max(1, runtime.circadian_interval)
          : graphRefreshSeconds;
      }
      if (wakeupIntervalInput) {
        wakeupIntervalInput.value = coalesce(runtime.wakeup_interval, 2);
      }
    } catch (err) {
      if (circadianIntervalInput) {
        circadianIntervalInput.value = 60;
        graphRefreshSeconds = 60;
      }
      if (wakeupIntervalInput) {
        wakeupIntervalInput.value = 2;
      }
    }
  }
  state.master = normalizeMaster(config.master);
  initMasterEditors();
  if (masterBrightnessCurve) {
    masterBrightnessCurve.setPoints(state.master.brightness_curve);
  }
  if (masterColorTempCurve) {
    masterColorTempCurve.setPoints(state.master.color_temp_curve);
  }
  if (masterSolarBrightnessToggle) {
    masterSolarBrightnessToggle.checked = state.master.solar_shift_brightness;
  }
  if (masterSolarColorToggle) {
    masterSolarColorToggle.checked = state.master.solar_shift_color_temp;
  }
  if (weatherCloudInput) {
    weatherCloudInput.value = getPath(state.master, ["weather", "cloud_sensor"]) || "";
  }
  if (weatherUvInput) {
    weatherUvInput.value = getPath(state.master, ["weather", "uv_sensor"]) || "";
  }
  if (weatherVisibilityInput) {
    weatherVisibilityInput.value = getPath(state.master, ["weather", "visibility_sensor"]) || "";
  }
  if (weatherCodeInput) {
    weatherCodeInput.value = getPath(state.master, ["weather", "weather_code_sensor"]) || "";
  }
  if (weatherUvMaxInput) {
    weatherUvMaxInput.value = coalesce(getPath(state.master, ["weather", "uv_max"]), 8);
  }
  if (weatherVisibilityMaxInput) {
    weatherVisibilityMaxInput.value = coalesce(getPath(state.master, ["weather", "visibility_max_km"]), 10);
  }
  if (weatherMaxReductionInput) {
    weatherMaxReductionInput.value = coalesce(getPath(state.master, ["weather", "max_reduction_pct"]), 60);
  }
  if (smoothBrightnessRateInput) {
    smoothBrightnessRateInput.value = coalesce(getPath(state.master, ["smoothing", "brightness_rate_pct"]), 0.11);
  }
  if (smoothCtRateInput) {
    smoothCtRateInput.value = coalesce(getPath(state.master, ["smoothing", "ct_rate_k"]), 2.67);
  }
  if (awayStartInput) {
    awayStartInput.value = formatMinutesToTime(getPath(state.master, ["away", "start_minutes"]), 360);
  }
  if (awayEndInput) {
    awayEndInput.value = formatMinutesToTime(getPath(state.master, ["away", "end_minutes"]), 1350);
  }
  if (awayMinMinutesInput) {
    awayMinMinutesInput.value = coalesce(getPath(state.master, ["away", "min_minutes"]), 30);
  }
  if (awayMaxMinutesInput) {
    awayMaxMinutesInput.value = coalesce(getPath(state.master, ["away", "max_minutes"]), 180);
  }
  if (awayOffsetMinutesInput) {
    awayOffsetMinutesInput.value = coalesce(getPath(state.master, ["away", "offset_minutes"]), 30);
  }
  if (sleepBrightnessInput) {
    sleepBrightnessInput.value = coalesce(getPath(state.master, ["sleep", "brightness_pct"]), 10);
  }
  if (sleepCtInput) {
    sleepCtInput.value = coalesce(getPath(state.master, ["sleep", "color_temp_kelvin"]), 2200);
  }
  if (sleepHueInput) {
    sleepHueInput.value = coalesce(getPath(state.master, ["sleep", "hs_color", 0]), 30);
  }
  if (sleepSatInput) {
    sleepSatInput.value = coalesce(getPath(state.master, ["sleep", "hs_color", 1]), 70);
  }
  if (wakeupDurationInput) {
    wakeupDurationInput.value = coalesce(getPath(state.master, ["wakeup", "duration_minutes"]), 30);
  }
  if (wakeupStartBrightnessInput) {
    wakeupStartBrightnessInput.value = coalesce(getPath(state.master, ["wakeup", "start_brightness_pct"]), 1);
  }
  if (retryEnabledToggle) {
    retryEnabledToggle.checked = getPath(state.master, ["retry", "enabled"]) !== false;
  }
  if (retryDelayInput) {
    retryDelayInput.value = coalesce(getPath(state.master, ["retry", "delay_seconds"]), 2);
  }
  if (retryMaxInput) {
    retryMaxInput.value = coalesce(getPath(state.master, ["retry", "max_retries"]), 3);
  }
  if (retryTolBrightnessInput) {
    retryTolBrightnessInput.value = coalesce(getPath(state.master, ["retry", "tolerance_brightness"]), 2);
  }
  if (retryTolCtInput) {
    retryTolCtInput.value = coalesce(getPath(state.master, ["retry", "tolerance_ct_k"]), 25);
  }
  if (retryTolHsInput) {
    retryTolHsInput.value = coalesce(getPath(state.master, ["retry", "tolerance_hs"]), 3);
  }
  if (retryTolRgbInput) {
    retryTolRgbInput.value = coalesce(getPath(state.master, ["retry", "tolerance_rgb"]), 3);
  }
  if (retryTolXyInput) {
    retryTolXyInput.value = coalesce(getPath(state.master, ["retry", "tolerance_xy"]), 0.01);
  }
  updateMasterOverlays();
  renderControllers();
  if (!editor.classList.contains("hidden")) {
    updateCurveOverlays();
  }
  setMasterVisible(!(masterSection && masterSection.classList.contains("hidden")));
  updateGraphRefreshTimer();
}

function parseIntOr(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function parseFloatOr(value, fallback) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function parseTimeToMinutes(value, fallback) {
  if (typeof value !== "string" || !value.includes(":")) {
    return fallback;
  }
  const [hoursRaw, minutesRaw] = value.split(":");
  const hours = Number.parseInt(hoursRaw, 10);
  const minutes = Number.parseInt(minutesRaw, 10);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
    return fallback;
  }
  return clampValue(hours, 0, 23) * 60 + clampValue(minutes, 0, 59);
}

function formatMinutesToTime(value, fallback) {
  const minutes = Number.isFinite(value) ? Number(value) : fallback;
  const clamped = ((minutes % 1440) + 1440) % 1440;
  const hh = String(Math.floor(clamped / 60)).padStart(2, "0");
  const mm = String(Math.floor(clamped % 60)).padStart(2, "0");
  return `${hh}:${mm}`;
}

function roundTo2(value) {
  if (!Number.isFinite(value)) {
    return value;
  }
  return Math.round(value * 100) / 100;
}

function clampValue(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function getNowMinutes() {
  const now = new Date();
  const localMinutes = now.getHours() * 60 + now.getMinutes() + now.getSeconds() / 60;
  const shifted = (localMinutes + state.timeOffsetMinutes + 1440) % 1440;
  return shifted;
}

function getSelectedLightIds() {
  return currentSelectedLights.slice();
}

function calculateCtBounds(selectedLights) {
  const minValues = [];
  const maxValues = [];
  const selectedSet = new Set(selectedLights);

  state.lights.forEach((light) => {
    if (!selectedSet.has(light.entity_id)) {
      return;
    }
    const minMireds = light.min_mireds;
    const maxMireds = light.max_mireds;
    if (!Number.isFinite(minMireds) || !Number.isFinite(maxMireds) || minMireds <= 0 || maxMireds <= 0) {
      return;
    }
    const minKelvin = Math.round(1000000 / maxMireds);
    const maxKelvin = Math.round(1000000 / minMireds);
    minValues.push(minKelvin);
    maxValues.push(maxKelvin);
  });

  if (!minValues.length || !maxValues.length) {
    return { ...ctDefaultBounds };
  }

  let min = Math.max(...minValues);
  let max = Math.min(...maxValues);
  if (min > max) {
    [min, max] = [max, min];
  }
  min = clampValue(min, ctDefaultBounds.min, ctDefaultBounds.max);
  max = clampValue(max, ctDefaultBounds.min, ctDefaultBounds.max);
  if (min > max) {
    min = ctDefaultBounds.min;
    max = ctDefaultBounds.max;
  }
  return { min, max };
}

function applyCtBounds(bounds) {
  currentCtBounds = bounds;
  if (ctMinInput) {
    ctMinInput.min = String(bounds.min);
    ctMinInput.max = String(bounds.max);
  }
  if (ctMaxInput) {
    ctMaxInput.min = String(bounds.min);
    ctMaxInput.max = String(bounds.max);
  }
  if (weatherMinInput) {
    weatherMinInput.min = String(bounds.min);
    weatherMinInput.max = String(bounds.max);
  }
}

function updateLimitBoundsFromSelection({ syncValues = true } = {}) {
  if (!ctMinInput || !ctMaxInput) {
    return;
  }
  const selectedLights = getSelectedLightIds();
  const bounds = calculateCtBounds(selectedLights);
  applyCtBounds(bounds);
  if (syncValues) {
    syncLimitInputs();
  }
}

function normalizeLimits(raw) {
  const limits = raw && typeof raw === "object" ? raw : {};

  let brightnessMin = clampValue(
    parseIntOr(limits.brightness_min_pct, limitDefaults.brightness_min_pct),
    1,
    100
  );
  let brightnessMax = clampValue(
    parseIntOr(limits.brightness_max_pct, limitDefaults.brightness_max_pct),
    1,
    100
  );
  if (brightnessMin > brightnessMax) {
    [brightnessMin, brightnessMax] = [brightnessMax, brightnessMin];
  }

  let ctMin = clampValue(
    parseIntOr(limits.ct_min_kelvin, limitDefaults.ct_min_kelvin),
    currentCtBounds.min,
    currentCtBounds.max
  );
  let ctMax = clampValue(
    parseIntOr(limits.ct_max_kelvin, limitDefaults.ct_max_kelvin),
    currentCtBounds.min,
    currentCtBounds.max
  );
  if (ctMin > ctMax) {
    [ctMin, ctMax] = [ctMax, ctMin];
  }

  let weatherMin = clampValue(
    parseIntOr(limits.weather_min_kelvin, limitDefaults.weather_min_kelvin),
    currentCtBounds.min,
    currentCtBounds.max
  );

  return {
    brightness_min_pct: brightnessMin,
    brightness_max_pct: brightnessMax,
    ct_min_kelvin: ctMin,
    ct_max_kelvin: ctMax,
    weather_min_kelvin: weatherMin,
  };
}

function setLimitLabels(limits) {
  if (brightnessMinValue) {
    brightnessMinValue.textContent = `${limits.brightness_min_pct}%`;
  }
  if (brightnessMaxValue) {
    brightnessMaxValue.textContent = `${limits.brightness_max_pct}%`;
  }
  if (ctMinValue) {
    ctMinValue.textContent = `${limits.ct_min_kelvin}K`;
  }
  if (ctMaxValue) {
    ctMaxValue.textContent = `${limits.ct_max_kelvin}K`;
  }
  if (weatherMinValue) {
    weatherMinValue.textContent = `${limits.weather_min_kelvin}K`;
  }
}

function syncLimitInputs() {
  if (!brightnessMinInput || !brightnessMaxInput || !ctMinInput || !ctMaxInput || !weatherMinInput) {
    return;
  }
  const normalized = normalizeLimits({
    brightness_min_pct: brightnessMinInput.value,
    brightness_max_pct: brightnessMaxInput.value,
    ct_min_kelvin: ctMinInput.value,
    ct_max_kelvin: ctMaxInput.value,
    weather_min_kelvin: weatherMinInput.value,
  });
  brightnessMinInput.value = normalized.brightness_min_pct;
  brightnessMaxInput.value = normalized.brightness_max_pct;
  ctMinInput.value = normalized.ct_min_kelvin;
  ctMaxInput.value = normalized.ct_max_kelvin;
  weatherMinInput.value = normalized.weather_min_kelvin;
  setLimitLabels(normalized);
  updateCurveDisplayLimits();
  updateCurveOverlays();
}

function applyLimitInputs(raw) {
  if (!brightnessMinInput || !brightnessMaxInput || !ctMinInput || !ctMaxInput || !weatherMinInput) {
    return;
  }
  const normalized = normalizeLimits(raw);
  brightnessMinInput.value = normalized.brightness_min_pct;
  brightnessMaxInput.value = normalized.brightness_max_pct;
  ctMinInput.value = normalized.ct_min_kelvin;
  ctMaxInput.value = normalized.ct_max_kelvin;
  weatherMinInput.value = normalized.weather_min_kelvin;
  setLimitLabels(normalized);
  updateCurveOverlays();
}

function readLimitInputs() {
  if (!brightnessMinInput || !brightnessMaxInput || !ctMinInput || !ctMaxInput || !weatherMinInput) {
    return { ...limitDefaults };
  }
  return normalizeLimits({
    brightness_min_pct: brightnessMinInput.value,
    brightness_max_pct: brightnessMaxInput.value,
    ct_min_kelvin: ctMinInput.value,
    ct_max_kelvin: ctMaxInput.value,
    weather_min_kelvin: weatherMinInput.value,
  });
}

function getCurveRange(points) {
  if (!Array.isArray(points) || !points.length) {
    return null;
  }
  let min = null;
  let max = null;
  points.forEach((point) => {
    if (!point || !Number.isFinite(point.v)) {
      return;
    }
    if (min === null || point.v < min) min = point.v;
    if (max === null || point.v > max) max = point.v;
  });
  if (min === null || max === null) {
    return null;
  }
  return { min, max };
}

function buildBrightnessTransform(limits) {
  const minPct = limits.brightness_min_pct;
  const maxPct = limits.brightness_max_pct;
  const span = maxPct - minPct;
  return {
    displayMin: minPct,
    displayMax: maxPct,
    toDisplay: (value) => {
      const pct = (value / 255) * 100;
      if (!span) {
        return minPct;
      }
      return minPct + (pct / 100) * span;
    },
    fromDisplay: (display) => {
      if (!span) {
        return 0;
      }
      const ratio = (display - minPct) / span;
      const pct = ratio * 100;
      return (pct / 100) * 255;
    },
  };
}

function buildCtTransform(limits, points) {
  const minK = limits.ct_min_kelvin;
  const maxK = limits.ct_max_kelvin;
  const range = getCurveRange(points);
  const span = maxK - minK;
  return {
    displayMin: minK,
    displayMax: maxK,
    toDisplay: (value) => {
      if (!range || range.min === range.max) {
        return clampValue(value, minK, maxK);
      }
      if (!span) {
        return minK;
      }
      const ratio = (value - range.min) / (range.max - range.min);
      const clamped = clampValue(ratio, 0, 1);
      return minK + clamped * span;
    },
    fromDisplay: (display) => {
      if (!range || range.min === range.max) {
        return range ? range.min : display;
      }
      if (!span) {
        return range.min;
      }
      const ratio = (display - minK) / span;
      const clamped = clampValue(ratio, 0, 1);
      return range.min + clamped * (range.max - range.min);
    },
  };
}

function updateCurveDisplayLimits() {
  if (!brightnessCurve || !colorTempCurve) {
    return;
  }
  const limits = readLimitInputs();
  const brightnessTransform = buildBrightnessTransform(limits);
  const brightnessDisplayMin = 0;
  const brightnessDisplayMax = 100;
  brightnessCurve.setDisplayRange(brightnessDisplayMin, brightnessDisplayMax);
  brightnessCurve.setValueTransform(brightnessTransform.toDisplay, brightnessTransform.fromDisplay);

  const ctTransform = buildCtTransform(limits, colorTempCurve.getPoints());
  const ctDefaultMin = 2000;
  const ctDefaultMax = 6500;
  const ctDisplayMin = Math.min(ctDefaultMin, ctTransform.displayMin);
  const ctDisplayMax = Math.max(ctDefaultMax, ctTransform.displayMax);
  colorTempCurve.setDisplayRange(ctDisplayMin, ctDisplayMax);
  colorTempCurve.setValueTransform(ctTransform.toDisplay, ctTransform.fromDisplay);
}

function setMasterVisible(visible) {
  if (!masterSection) {
    return;
  }
  masterSection.classList.toggle("hidden", !visible);
  if (toggleMasterBtn) {
    toggleMasterBtn.textContent = visible ? "Hide Master" : "Master Settings";
  }
  if (visible) {
    requestAnimationFrame(() => {
      if (masterBrightnessCurve) {
        masterBrightnessCurve.resize();
      }
      if (masterColorTempCurve) {
        masterColorTempCurve.resize();
      }
    });
  }
}

function normalizeControllerKey(controller) {
  const raw = (controller.unique_id || controller.name || "").toString().trim().toLowerCase();
  return `svtlc_${raw.replace(/\s+/g, "_")}`;
}

function controllerMatchesFilters(controller) {
  const query = controllerSearch ? controllerSearch.value.trim().toLowerCase() : "";
  const circadian = controller.circadian || {};
  if (query) {
    const haystack = `${controller.name || ""} ${controller.unique_id || ""} ${(controller.input_lights || []).join(" ")}`.toLowerCase();
    if (!haystack.includes(query)) {
      return false;
    }
  }
  if (filterCircadian && filterCircadian.checked && !circadian.enabled) {
    return false;
  }
  if (filterMasterBrightness && filterMasterBrightness.checked && !circadian.use_master_brightness) {
    return false;
  }
  if (filterMasterColor && filterMasterColor.checked && !circadian.use_master_color_temp) {
    return false;
  }
  return true;
}

function sortControllers(list) {
  const sortValue = controllerSort ? controllerSort.value : "name";
  return list.slice().sort((a, b) => {
    if (sortValue === "inputs") {
      return (b.input_lights || []).length - (a.input_lights || []).length;
    }
    if (sortValue === "id") {
      return (a.unique_id || "").localeCompare(b.unique_id || "");
    }
    return (a.name || "").localeCompare(b.name || "");
  });
}

function updateBulkBar() {
  if (!bulkActions || !bulkCount) {
    return;
  }
  const count = state.selection.size;
  bulkCount.textContent = `${count} selected`;
  bulkActions.classList.toggle("hidden", count === 0);
}

function applyBulkAction(action) {
  if (!action) {
    return;
  }
  const selected = new Set(state.selection);
  if (!selected.size) {
    return;
  }

  state.controllers.forEach((controller) => {
    const key = normalizeControllerKey(controller);
    if (!selected.has(key)) {
      return;
    }
    const circadian = controller.circadian || {};
    controller.circadian = circadian;

    switch (action) {
      case "circadian_on":
        circadian.enabled = true;
        break;
      case "circadian_off":
        circadian.enabled = false;
        break;
      case "master_brightness_on":
        circadian.use_master_brightness = true;
        break;
      case "master_brightness_off":
        circadian.use_master_brightness = false;
        break;
      case "master_color_on":
        circadian.use_master_color_temp = true;
        break;
      case "master_color_off":
        circadian.use_master_color_temp = false;
        break;
      case "solar_brightness_on":
        circadian.solar_shift_brightness = true;
        break;
      case "solar_brightness_off":
        circadian.solar_shift_brightness = false;
        break;
      case "solar_color_on":
        circadian.solar_shift_color_temp = true;
        break;
      case "solar_color_off":
        circadian.solar_shift_color_temp = false;
        break;
      default:
        break;
    }
  });

  saveConfig()
    .then(loadData)
    .catch(() => {
      errorText.textContent = "Failed to save configuration.";
    });
}

function buildControllerRow(controller) {
  const circadian = controller.circadian || {};
  const inputLights = Array.isArray(controller.input_lights) ? controller.input_lights : [];
  return {
    name: controller.name || "Unnamed",
    unique_id: controller.unique_id || "",
    inputs: inputLights.length,
    controller,
  };
}


let controllerTabulator = null;

function initControllerTable(rows) {
  if (!controllerTable) {
    return;
  }
  const data = rows.map(buildControllerRow);
  if (controllerTabulator) {
    controllerTabulator.setData(data);
    return;
  }
  if (typeof Tabulator === "undefined") {
    controllerTable.innerHTML = "<div class=\"controller-empty\">Tabulator failed to load.</div>";
    return;
  }
  controllerTabulator = new Tabulator(controllerTable, {
    headerSortElement: function () {
      const span = document.createElement("span");
      span.className = "tabulator-sorter";
      return span;
    },
    data,
    layout: "fitColumns",
    height: "480px",
    reactiveData: false,
    index: "unique_id",
    columns: [
      {
        formatter: "rowSelection",
        titleFormatter: "rowSelection",
        headerSort: false,
        width: 40,
        hozAlign: "center",
        cellClick: (e, cell) => cell.getRow().toggleSelect(),
      },
      { title: "Name", field: "name", headerSort: true },
      { title: "ID", field: "unique_id", headerSort: true, width: 160 },
      { title: "Inputs", field: "inputs", headerSort: true, hozAlign: "right", width: 80 },
      {
        title: "Actions",
        headerSort: false,
        width: 140,
        formatter: () => "<span class=\"table-actions\"><button type=\"button\" class=\"edit-row\">Edit</button><button type=\"button\" class=\"delete-row\">Delete</button></span>",
        cellClick: (e, cell) => {
          const row = cell.getRow();
          const data = row.getData();
          if (e.target && e.target.classList.contains("edit-row")) {
            const index = state.controllers.indexOf(data.controller);
            if (index >= 0) {
              openEditor(index);
            }
          }
          if (e.target && e.target.classList.contains("delete-row")) {
            const index = state.controllers.indexOf(data.controller);
            if (index >= 0) {
              deleteController(index);
            }
          }
        },
      },
    ],
    rowClick: (e, row) => {
      if (e.target && (e.target.tagName === "BUTTON" || e.target.closest(".table-actions"))) {
        return;
      }
      const data = row.getData();
      const index = state.controllers.indexOf(data.controller);
      if (index >= 0) {
        openEditor(index);
      }
    },
    rowSelectionChanged: (data) => {
      state.selection.clear();
      data.forEach((row) => state.selection.add(normalizeControllerKey(row.controller)));
      updateBulkBar();
    },
  });
}

function refreshControllerTable() {
  if (!controllerTabulator) {
    return;
  }
  const filtered = sortControllers(state.controllers.filter(controllerMatchesFilters));
  controllerTabulator.setData(filtered.map(buildControllerRow));
}

function renderControllers(reset = true) {
  if (!controllerTable) {
    return;
  }
  if (reset) {
    controllerTable.innerHTML = "";
    if (!state.controllers.length) {
      controllerTable.innerHTML = "<div class=\"controller-empty\">No controllers configured yet.</div>";
      updateBulkBar();
      return;
    }
    state.filteredControllers = sortControllers(state.controllers.filter(controllerMatchesFilters));
    if (!state.filteredControllers.length) {
      controllerTable.innerHTML = "<div class=\"controller-empty\">No controllers match the current filters.</div>";
      updateBulkBar();
      return;
    }
    initControllerTable(state.filteredControllers);
    updateBulkBar();
    return;
  }

  if (!state.filteredControllers.length) {
    controllerTable.innerHTML = "<div class=\"controller-empty\">No controllers match the current filters.</div>";
    updateBulkBar();
    return;
  }

  refreshControllerTable();
  updateBulkBar();
}

function openEditor(index) {
  state.editingIndex = typeof index === "number" ? index : null;
  const controller = state.editingIndex !== null ? state.controllers[state.editingIndex] : null;

  editorTitle.textContent = controller ? "Edit Controller" : "New Controller";
  nameInput.value = controller ? controller.name || "" : "";
  uniqueInput.value = controller ? controller.unique_id || "" : "";
  errorText.textContent = "";

  initCurveEditors();
  const circadian = controller && controller.circadian ? controller.circadian : {};
  if (circadianToggle) {
    circadianToggle.checked = Boolean(circadian.enabled);
  }
  if (useMasterBrightnessToggle) {
    useMasterBrightnessToggle.checked = Boolean(circadian.use_master_brightness);
  }
  if (useMasterColorToggle) {
    useMasterColorToggle.checked = Boolean(circadian.use_master_color_temp);
  }
  if (solarBrightnessToggle) {
    solarBrightnessToggle.checked = circadian.solar_shift_brightness !== false;
  }
  if (solarColorToggle) {
    solarColorToggle.checked = circadian.solar_shift_color_temp !== false;
  }
  if (weatherEnabledToggle) {
    const legacyMasterEnabled = Boolean(getPath(state.master, ["weather", "enabled"]));
    const controllerEnabled = controller && typeof controller.weather_enabled === "boolean"
      ? controller.weather_enabled
      : legacyMasterEnabled;
    weatherEnabledToggle.checked = controllerEnabled;
  }
  const sleepCfg = controller && typeof controller.sleep === "object" ? controller.sleep : {};
  const sleepUseMaster = sleepUseMasterToggle ? sleepUseMasterToggle.checked : true;
  if (sleepUseMasterToggle) {
    sleepUseMasterToggle.checked = sleepCfg.use_master !== false;
  }
  const sleepBase = sleepCfg.use_master === false ? sleepCfg : (state.master && state.master.sleep ? state.master.sleep : {});
  if (sleepBrightnessOverrideInput) {
    sleepBrightnessOverrideInput.value = coalesce(
      coalesce(getPath(sleepBase, ["brightness_pct"]), getPath(state.master, ["sleep", "brightness_pct"])),
      10
    );
  }
  if (sleepCtOverrideInput) {
    sleepCtOverrideInput.value = coalesce(
      coalesce(getPath(sleepBase, ["color_temp_kelvin"]), getPath(state.master, ["sleep", "color_temp_kelvin"])),
      2200
    );
  }
  if (sleepHueOverrideInput) {
    sleepHueOverrideInput.value = coalesce(
      coalesce(getPath(sleepBase, ["hs_color", 0]), getPath(state.master, ["sleep", "hs_color", 0])),
      30
    );
  }
  if (sleepSatOverrideInput) {
    sleepSatOverrideInput.value = coalesce(
      coalesce(getPath(sleepBase, ["hs_color", 1]), getPath(state.master, ["sleep", "hs_color", 1])),
      70
    );
  }
  const wakeupCfg = controller && typeof controller.wakeup === "object" ? controller.wakeup : {};
  if (wakeupUseMasterToggle) {
    wakeupUseMasterToggle.checked = wakeupCfg.use_master !== false;
  }
  const wakeupBase = wakeupCfg.use_master === false ? wakeupCfg : (state.master && state.master.wakeup ? state.master.wakeup : {});
  if (wakeupDurationOverrideInput) {
    wakeupDurationOverrideInput.value = coalesce(
      coalesce(getPath(wakeupBase, ["duration_minutes"]), getPath(state.master, ["wakeup", "duration_minutes"])),
      30
    );
  }
  if (wakeupStartBrightnessOverrideInput) {
    wakeupStartBrightnessOverrideInput.value = coalesce(
      coalesce(getPath(wakeupBase, ["start_brightness_pct"]), getPath(state.master, ["wakeup", "start_brightness_pct"])),
      1
    );
  }
  toggleCircadianFields();
  updateSleepOverrides();
  updateWakeupOverrides();
  editorCustomBrightness = (circadian.brightness_curve || curveDefaults.brightness).map((point) => ({ ...point }));
  editorCustomColorTemp = (circadian.color_temp_curve || curveDefaults.color_temp).map((point) => ({ ...point }));
  editorBrightnessEnabled = circadian.brightness_enabled !== false;
  editorColorTempEnabled = circadian.color_temp_enabled !== false;
  lastUseMasterBrightness = Boolean(circadian.use_master_brightness);
  lastUseMasterColor = Boolean(circadian.use_master_color_temp);
  updateEditorCurveUsage();

  if (lightSearch) {
    lightSearch.value = "";
  }
  currentSelectedLights = Array.isArray(controller && controller.input_lights) ? controller.input_lights.slice() : [];
  renderLightLists(currentSelectedLights);
  updateLimitBoundsFromSelection({ syncValues: false });
  applyLimitInputs(controller && controller.limits ? controller.limits : limitDefaults);
  updateCurveDisplayLimits();
  updateCurveOverlays();
  editor.classList.remove("hidden");
  document.body.classList.add("editor-open");
  if (brightnessCurve) {
    requestAnimationFrame(() => {
      brightnessCurve.resize();
      if (colorTempCurve) {
        colorTempCurve.resize();
      }
    });
  }
}

function closeEditor() {
  editor.classList.add("hidden");
  document.body.classList.remove("editor-open");
  if (lightSearch) {
    lightSearch.value = "";
  }
  if (circadianToggle) {
    circadianToggle.checked = false;
  }
  if (useMasterBrightnessToggle) {
    useMasterBrightnessToggle.checked = false;
  }
  if (useMasterColorToggle) {
    useMasterColorToggle.checked = false;
  }
  if (solarBrightnessToggle) {
    solarBrightnessToggle.checked = true;
  }
  if (solarColorToggle) {
    solarColorToggle.checked = true;
  }
  if (weatherEnabledToggle) {
    weatherEnabledToggle.checked = false;
  }
  if (sleepUseMasterToggle) {
    sleepUseMasterToggle.checked = true;
  }
  if (sleepBrightnessOverrideInput) {
    sleepBrightnessOverrideInput.value = "";
  }
  if (sleepCtOverrideInput) {
    sleepCtOverrideInput.value = "";
  }
  if (sleepHueOverrideInput) {
    sleepHueOverrideInput.value = "";
  }
  if (sleepSatOverrideInput) {
    sleepSatOverrideInput.value = "";
  }
  if (wakeupUseMasterToggle) {
    wakeupUseMasterToggle.checked = true;
  }
  if (wakeupDurationOverrideInput) {
    wakeupDurationOverrideInput.value = "";
  }
  if (wakeupStartBrightnessOverrideInput) {
    wakeupStartBrightnessOverrideInput.value = "";
  }
  toggleCircadianFields();
  applyLimitInputs(limitDefaults);
  if (brightnessCurve) {
    brightnessCurve.setPoints(curveDefaults.brightness);
  }
  if (colorTempCurve) {
    colorTempCurve.setPoints(curveDefaults.color_temp);
  }
  form.reset();
  if (availableList) {
    availableList.innerHTML = "";
  }
  if (selectedList) {
    selectedList.innerHTML = "";
  }
  errorText.textContent = "";
  state.editingIndex = null;
  editorCustomBrightness = null;
  editorCustomColorTemp = null;
  lastUseMasterBrightness = false;
  lastUseMasterColor = false;
  editorBrightnessEnabled = true;
  editorColorTempEnabled = true;
  currentCtBounds = { ...ctDefaultBounds };
  currentSelectedLights = [];
}

function renderLightLists(selected) {
  if (!availableList || !selectedList) {
    return;
  }
  if (Array.isArray(selected)) {
    currentSelectedLights = Array.from(new Set(selected));
  }
  const selectedSet = new Set(currentSelectedLights);
  const used = new Set();
  state.controllers.forEach((controller, idx) => {
    if (idx === state.editingIndex) return;
    (controller.input_lights || []).forEach((light) => used.add(light));
  });

  const query = lightSearch ? lightSearch.value.trim().toLowerCase() : "";

  availableList.innerHTML = "";
  selectedList.innerHTML = "";

  let availableVisible = 0;
  state.lights.forEach((light) => {
    if (selectedSet.has(light.entity_id)) {
      return;
    }
    if (query) {
      const haystack = `${light.name} ${light.entity_id}`.toLowerCase();
      if (!haystack.includes(query)) {
        return;
      }
    }

    const wrapper = document.createElement("label");
    wrapper.className = "light-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = light.entity_id;
    checkbox.disabled = used.has(light.entity_id);

    const label = document.createElement("span");
    label.textContent = `${light.name} (${light.entity_id})`;

    if (checkbox.disabled) {
      const note = document.createElement("span");
      note.className = "light-note";
      note.textContent = "In use";
      wrapper.appendChild(checkbox);
      wrapper.appendChild(label);
      wrapper.appendChild(note);
    } else {
      wrapper.appendChild(checkbox);
      wrapper.appendChild(label);
    }

    availableList.appendChild(wrapper);
    availableVisible += 1;
  });

  const lightById = new Map(state.lights.map((light) => [light.entity_id, light]));
  currentSelectedLights.forEach((entityId) => {
    const light = lightById.get(entityId) || { name: entityId, entity_id: entityId };
    const wrapper = document.createElement("label");
    wrapper.className = "light-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = entityId;

    const label = document.createElement("span");
    label.textContent = `${light.name} (${light.entity_id})`;

    wrapper.appendChild(checkbox);
    wrapper.appendChild(label);
    selectedList.appendChild(wrapper);
  });

  if (availableCount) {
    availableCount.textContent = String(availableVisible);
  }
  if (selectedCount) {
    selectedCount.textContent = String(currentSelectedLights.length);
  }
}

function collectCheckedIds(container) {
  if (!container) {
    return [];
  }
  return Array.from(container.querySelectorAll("input[type=checkbox]:checked")).map((input) => input.value);
}

function addSelectedLights(ids) {
  if (!ids.length) {
    return;
  }
  currentSelectedLights = Array.from(new Set([...currentSelectedLights, ...ids]));
  renderLightLists(currentSelectedLights);
  updateLimitBoundsFromSelection();
}

function removeSelectedLights(ids) {
  if (!ids.length) {
    return;
  }
  const toRemove = new Set(ids);
  currentSelectedLights = currentSelectedLights.filter((id) => !toRemove.has(id));
  renderLightLists(currentSelectedLights);
  updateLimitBoundsFromSelection();
}

function toggleCircadianFields() {
  if (!circadianFields || !circadianToggle) {
    return;
  }
  circadianFields.classList.toggle("hidden", !circadianToggle.checked);
  if (circadianToggle.checked) {
    updateCurveOverlays();
  }
}

function updateSleepOverrides() {
  if (!sleepUseMasterToggle) {
    return;
  }
  const useMaster = sleepUseMasterToggle.checked;
  if (sleepBrightnessOverrideInput) {
    sleepBrightnessOverrideInput.disabled = useMaster;
  }
  if (sleepCtOverrideInput) {
    sleepCtOverrideInput.disabled = useMaster;
  }
  if (sleepHueOverrideInput) {
    sleepHueOverrideInput.disabled = useMaster;
  }
  if (sleepSatOverrideInput) {
    sleepSatOverrideInput.disabled = useMaster;
  }
  if (useMaster) {
    if (sleepBrightnessOverrideInput) {
      sleepBrightnessOverrideInput.value = coalesce(getPath(state.master, ["sleep", "brightness_pct"]), 10);
    }
    if (sleepCtOverrideInput) {
      sleepCtOverrideInput.value = coalesce(getPath(state.master, ["sleep", "color_temp_kelvin"]), 2200);
    }
    if (sleepHueOverrideInput) {
      sleepHueOverrideInput.value = coalesce(getPath(state.master, ["sleep", "hs_color", 0]), 30);
    }
    if (sleepSatOverrideInput) {
      sleepSatOverrideInput.value = coalesce(getPath(state.master, ["sleep", "hs_color", 1]), 70);
    }
  }
}

function updateWakeupOverrides() {
  if (!wakeupUseMasterToggle) {
    return;
  }
  const useMaster = wakeupUseMasterToggle.checked;
  if (wakeupDurationOverrideInput) {
    wakeupDurationOverrideInput.disabled = useMaster;
  }
  if (wakeupStartBrightnessOverrideInput) {
    wakeupStartBrightnessOverrideInput.disabled = useMaster;
  }
  if (useMaster) {
    if (wakeupDurationOverrideInput) {
      wakeupDurationOverrideInput.value = coalesce(getPath(state.master, ["wakeup", "duration_minutes"]), 30);
    }
    if (wakeupStartBrightnessOverrideInput) {
      wakeupStartBrightnessOverrideInput.value = coalesce(getPath(state.master, ["wakeup", "start_brightness_pct"]), 1);
    }
  }
}

function updateCurveOverlays() {
  if (!state.solar || !brightnessCurve || !colorTempCurve) {
    return;
  }

  const controller = state.editingIndex !== null ? state.controllers[state.editingIndex] : null;
  const circadian = controller && controller.circadian ? controller.circadian : {};

  const nowMinutes = getNowMinutes();

  const { baseSunrise, baseSunset } = getBaseSunTimes(state.solar, circadian);

  const useSolarBrightness = solarBrightnessToggle ? solarBrightnessToggle.checked : true;
  const useSolarColor = solarColorToggle ? solarColorToggle.checked : true;
  const useMasterBrightness = useMasterBrightnessToggle ? useMasterBrightnessToggle.checked : false;
  const useMasterColor = useMasterColorToggle ? useMasterColorToggle.checked : false;
  const masterSolarBrightness = state.master ? state.master.solar_shift_brightness : true;
  const masterSolarColor = state.master ? state.master.solar_shift_color_temp : true;

  const monthSamples = (state.solar.months || []).map((month) => {
    return buildScaledSamples(
      useMasterBrightness ? state.master.brightness_curve : brightnessCurve.getPoints(),
      baseSunrise,
      baseSunset,
      (useMasterBrightness ? masterSolarBrightness : useSolarBrightness) ? month.sunrise : baseSunrise,
      (useMasterBrightness ? masterSolarBrightness : useSolarBrightness) ? month.sunset : baseSunset,
      brightnessCurve.min,
      brightnessCurve.max,
      (useMasterBrightness ? masterSolarBrightness : useSolarBrightness) ? month.dst_offset || 0 : 0
    );
  });

  const monthSamplesCt = (state.solar.months || []).map((month) => {
    return buildScaledSamples(
      useMasterColor ? state.master.color_temp_curve : colorTempCurve.getPoints(),
      baseSunrise,
      baseSunset,
      (useMasterColor ? masterSolarColor : useSolarColor) ? month.sunrise : baseSunrise,
      (useMasterColor ? masterSolarColor : useSolarColor) ? month.sunset : baseSunset,
      colorTempCurve.min,
      colorTempCurve.max,
      (useMasterColor ? masterSolarColor : useSolarColor) ? month.dst_offset || 0 : 0
    );
  });

  const currentDay = state.solar.today;
  const currentBrightness = currentDay
    ? buildScaledSamples(
        useMasterBrightness ? state.master.brightness_curve : brightnessCurve.getPoints(),
        baseSunrise,
        baseSunset,
        (useMasterBrightness ? masterSolarBrightness : useSolarBrightness) ? currentDay.sunrise : baseSunrise,
        (useMasterBrightness ? masterSolarBrightness : useSolarBrightness) ? currentDay.sunset : baseSunset,
        brightnessCurve.min,
        brightnessCurve.max,
        (useMasterBrightness ? masterSolarBrightness : useSolarBrightness) ? currentDay.dst_offset || 0 : 0
      )
    : null;
  const currentColorTemp = currentDay
    ? buildScaledSamples(
        useMasterColor ? state.master.color_temp_curve : colorTempCurve.getPoints(),
        baseSunrise,
        baseSunset,
        (useMasterColor ? masterSolarColor : useSolarColor) ? currentDay.sunrise : baseSunrise,
        (useMasterColor ? masterSolarColor : useSolarColor) ? currentDay.sunset : baseSunset,
        colorTempCurve.min,
        colorTempCurve.max,
        (useMasterColor ? masterSolarColor : useSolarColor) ? currentDay.dst_offset || 0 : 0
      )
    : null;

  brightnessCurve.setOverlays(buildOverlayBundle(monthSamples, currentBrightness));
  colorTempCurve.setOverlays(buildOverlayBundle(monthSamplesCt, currentColorTemp));

  const nowBrightnessRaw = currentDay
    ? computeCurrentValue(
        useMasterBrightness ? state.master.brightness_curve : brightnessCurve.getPoints(),
        baseSunrise,
        baseSunset,
        (useMasterBrightness ? masterSolarBrightness : useSolarBrightness) ? currentDay.sunrise : baseSunrise,
        (useMasterBrightness ? masterSolarBrightness : useSolarBrightness) ? currentDay.sunset : baseSunset,
        brightnessCurve.min,
        brightnessCurve.max,
        (useMasterBrightness ? masterSolarBrightness : useSolarBrightness) ? currentDay.dst_offset || 0 : 0,
        nowMinutes
      )
    : null;
  const nowColorTempRaw = currentDay
    ? computeCurrentValue(
        useMasterColor ? state.master.color_temp_curve : colorTempCurve.getPoints(),
        baseSunrise,
        baseSunset,
        (useMasterColor ? masterSolarColor : useSolarColor) ? currentDay.sunrise : baseSunrise,
        (useMasterColor ? masterSolarColor : useSolarColor) ? currentDay.sunset : baseSunset,
        colorTempCurve.min,
        colorTempCurve.max,
        (useMasterColor ? masterSolarColor : useSolarColor) ? currentDay.dst_offset || 0 : 0,
        nowMinutes
      )
    : null;
  const nowBrightness = Number.isFinite(nowBrightnessRaw)
    ? clampValue(Math.round(nowBrightnessRaw), 0, 255)
    : null;
  const nowColorTemp = Number.isFinite(nowColorTempRaw)
    ? clampValue(Math.round(nowColorTempRaw), 1500, 8000)
    : null;
  brightnessCurve.setNowValue(nowBrightness);
  colorTempCurve.setNowValue(nowColorTemp);
  const limits = readLimitInputs();
  const brightnessTransform = buildBrightnessTransform(limits);
  const ctTransform = buildCtTransform(limits, colorTempCurve.getPoints());
  const brightnessDisplay = Number.isFinite(nowBrightness) ? brightnessTransform.toDisplay(nowBrightness) : null;
  const colorDisplay = Number.isFinite(nowColorTemp) ? ctTransform.toDisplay(nowColorTemp) : null;
  brightnessCurve.setNowValueDisplay(brightnessDisplay);
  colorTempCurve.setNowValueDisplay(colorDisplay);
  brightnessCurve.setNowMinutes(nowMinutes);
  colorTempCurve.setNowMinutes(nowMinutes);
}

function updateMasterOverlays() {
  if (!state.solar || !masterBrightnessCurve || !masterColorTempCurve) {
    return;
  }
  const nowMinutes = getNowMinutes();
  const { baseSunrise, baseSunset } = getBaseSunTimes(state.solar, {});
  const useSolarBrightness = masterSolarBrightnessToggle ? masterSolarBrightnessToggle.checked : true;
  const useSolarColor = masterSolarColorToggle ? masterSolarColorToggle.checked : true;
  const monthSamples = (state.solar.months || []).map((month) => {
    return buildScaledSamples(
      masterBrightnessCurve.getPoints(),
      baseSunrise,
      baseSunset,
      useSolarBrightness ? month.sunrise : baseSunrise,
      useSolarBrightness ? month.sunset : baseSunset,
      masterBrightnessCurve.min,
      masterBrightnessCurve.max,
      useSolarBrightness ? month.dst_offset || 0 : 0
    );
  });
  const monthSamplesCt = (state.solar.months || []).map((month) => {
    return buildScaledSamples(
      masterColorTempCurve.getPoints(),
      baseSunrise,
      baseSunset,
      useSolarColor ? month.sunrise : baseSunrise,
      useSolarColor ? month.sunset : baseSunset,
      masterColorTempCurve.min,
      masterColorTempCurve.max,
      useSolarColor ? month.dst_offset || 0 : 0
    );
  });
  const currentDay = state.solar.today;
  const currentBrightness = currentDay
    ? buildScaledSamples(
        masterBrightnessCurve.getPoints(),
        baseSunrise,
        baseSunset,
        useSolarBrightness ? currentDay.sunrise : baseSunrise,
        useSolarBrightness ? currentDay.sunset : baseSunset,
        masterBrightnessCurve.min,
        masterBrightnessCurve.max,
        useSolarBrightness ? currentDay.dst_offset || 0 : 0
      )
    : null;
  const currentColorTemp = currentDay
    ? buildScaledSamples(
        masterColorTempCurve.getPoints(),
        baseSunrise,
        baseSunset,
        useSolarColor ? currentDay.sunrise : baseSunrise,
        useSolarColor ? currentDay.sunset : baseSunset,
        masterColorTempCurve.min,
        masterColorTempCurve.max,
        useSolarColor ? currentDay.dst_offset || 0 : 0
      )
    : null;

  masterBrightnessCurve.setOverlays(buildOverlayBundle(monthSamples, currentBrightness));
  masterColorTempCurve.setOverlays(buildOverlayBundle(monthSamplesCt, currentColorTemp));

  const nowBrightness = currentDay
    ? computeCurrentValue(
        masterBrightnessCurve.getPoints(),
        baseSunrise,
        baseSunset,
        useSolarBrightness ? currentDay.sunrise : baseSunrise,
        useSolarBrightness ? currentDay.sunset : baseSunset,
        masterBrightnessCurve.min,
        masterBrightnessCurve.max,
        useSolarBrightness ? currentDay.dst_offset || 0 : 0,
        nowMinutes
      )
    : null;
  const nowColorTemp = currentDay
    ? computeCurrentValue(
        masterColorTempCurve.getPoints(),
        baseSunrise,
        baseSunset,
        useSolarColor ? currentDay.sunrise : baseSunrise,
        useSolarColor ? currentDay.sunset : baseSunset,
        masterColorTempCurve.min,
        masterColorTempCurve.max,
        useSolarColor ? currentDay.dst_offset || 0 : 0,
        nowMinutes
      )
    : null;
  masterBrightnessCurve.setNowValue(nowBrightness);
  masterColorTempCurve.setNowValue(nowColorTemp);
  masterBrightnessCurve.setNowValueDisplay(
    Number.isFinite(nowBrightness) ? nowBrightness : null
  );
  masterColorTempCurve.setNowValueDisplay(nowColorTemp);
  masterBrightnessCurve.setNowMinutes(nowMinutes);
  masterColorTempCurve.setNowMinutes(nowMinutes);
}

function normalizeMaster(master) {
  if (!master || typeof master !== "object") {
    return {
      brightness_curve: curveDefaults.brightness,
      color_temp_curve: curveDefaults.color_temp,
      solar_shift_brightness: true,
      solar_shift_color_temp: true,
      weather: {
        cloud_sensor: "sensor.openweathermap_cloud_coverage",
        uv_sensor: "sensor.openweathermap_uv_index",
        visibility_sensor: "sensor.openweathermap_visibility",
        weather_code_sensor: "sensor.openweathermap_weather_code",
        uv_max: 8,
        visibility_max_km: 10,
        max_reduction_pct: 60,
      },
      smoothing: {
        brightness_rate_pct: 0.11,
        ct_rate_k: 2.67,
      },
      away: {
        start_minutes: 360,
        end_minutes: 1350,
        min_minutes: 30,
        max_minutes: 180,
        offset_minutes: 30,
      },
      sleep: {
        brightness_pct: 10,
        color_temp_kelvin: 2200,
        hs_color: [30, 70],
      },
      wakeup: {
        duration_minutes: 30,
        start_brightness_pct: 1,
      },
      retry: {
        enabled: true,
        delay_seconds: 2,
        max_retries: 3,
        tolerance_brightness: 2,
        tolerance_ct_k: 25,
        tolerance_hs: 3,
        tolerance_rgb: 3,
        tolerance_xy: 0.01,
      },
    };
  }
  return {
    brightness_curve: Array.isArray(master.brightness_curve) ? master.brightness_curve : curveDefaults.brightness,
    color_temp_curve: Array.isArray(master.color_temp_curve) ? master.color_temp_curve : curveDefaults.color_temp,
    solar_shift_brightness: master.solar_shift_brightness !== false,
    solar_shift_color_temp: master.solar_shift_color_temp !== false,
    weather: {
      cloud_sensor: getPath(master, ["weather", "cloud_sensor"]) || "sensor.openweathermap_cloud_coverage",
      uv_sensor: getPath(master, ["weather", "uv_sensor"]) || "sensor.openweathermap_uv_index",
      visibility_sensor: getPath(master, ["weather", "visibility_sensor"]) || "sensor.openweathermap_visibility",
      weather_code_sensor: getPath(master, ["weather", "weather_code_sensor"]) || "sensor.openweathermap_weather_code",
      uv_max: Number.isFinite(getPath(master, ["weather", "uv_max"])) ? master.weather.uv_max : 8,
      visibility_max_km: Number.isFinite(getPath(master, ["weather", "visibility_max_km"])) ? master.weather.visibility_max_km : 10,
      max_reduction_pct: Number.isFinite(getPath(master, ["weather", "max_reduction_pct"])) ? master.weather.max_reduction_pct : 60,
    },
    smoothing: {
      brightness_rate_pct: Number.isFinite(getPath(master, ["smoothing", "brightness_rate_pct"]))
        ? master.smoothing.brightness_rate_pct
        : 0.11,
      ct_rate_k: Number.isFinite(getPath(master, ["smoothing", "ct_rate_k"])) ? master.smoothing.ct_rate_k : 2.67,
    },
    away: {
      start_minutes: Number.isFinite(getPath(master, ["away", "start_minutes"])) ? master.away.start_minutes : 360,
      end_minutes: Number.isFinite(getPath(master, ["away", "end_minutes"])) ? master.away.end_minutes : 1350,
      min_minutes: Number.isFinite(getPath(master, ["away", "min_minutes"])) ? master.away.min_minutes : 30,
      max_minutes: Number.isFinite(getPath(master, ["away", "max_minutes"])) ? master.away.max_minutes : 180,
      offset_minutes: Number.isFinite(getPath(master, ["away", "offset_minutes"])) ? master.away.offset_minutes : 30,
    },
    sleep: {
      brightness_pct: Number.isFinite(getPath(master, ["sleep", "brightness_pct"])) ? master.sleep.brightness_pct : 10,
      color_temp_kelvin: Number.isFinite(getPath(master, ["sleep", "color_temp_kelvin"])) ? master.sleep.color_temp_kelvin : 2200,
      hs_color: Array.isArray(getPath(master, ["sleep", "hs_color"])) ? master.sleep.hs_color.slice(0, 2) : [30, 70],
    },
    wakeup: {
      duration_minutes: Number.isFinite(getPath(master, ["wakeup", "duration_minutes"])) ? master.wakeup.duration_minutes : 30,
      start_brightness_pct: Number.isFinite(getPath(master, ["wakeup", "start_brightness_pct"])) ? master.wakeup.start_brightness_pct : 1,
    },
    retry: {
      enabled: getPath(master, ["retry", "enabled"]) !== false,
      delay_seconds: Number.isFinite(getPath(master, ["retry", "delay_seconds"])) ? master.retry.delay_seconds : 2,
      max_retries: Number.isFinite(getPath(master, ["retry", "max_retries"])) ? master.retry.max_retries : 3,
      tolerance_brightness: Number.isFinite(getPath(master, ["retry", "tolerance_brightness"])) ? master.retry.tolerance_brightness : 2,
      tolerance_ct_k: Number.isFinite(getPath(master, ["retry", "tolerance_ct_k"])) ? master.retry.tolerance_ct_k : 25,
      tolerance_hs: Number.isFinite(getPath(master, ["retry", "tolerance_hs"])) ? master.retry.tolerance_hs : 3,
      tolerance_rgb: Number.isFinite(getPath(master, ["retry", "tolerance_rgb"])) ? master.retry.tolerance_rgb : 3,
      tolerance_xy: Number.isFinite(getPath(master, ["retry", "tolerance_xy"])) ? master.retry.tolerance_xy : 0.01,
    },
  };
}

function updateEditorCurveUsage() {
  if (!brightnessCurve || !colorTempCurve) {
    return;
  }
  const useMasterBrightness = useMasterBrightnessToggle ? useMasterBrightnessToggle.checked : false;
  const useMasterColor = useMasterColorToggle ? useMasterColorToggle.checked : false;

  if (useMasterBrightness && !lastUseMasterBrightness) {
    editorCustomBrightness = brightnessCurve.getPoints();
  }
  if (useMasterColor && !lastUseMasterColor) {
    editorCustomColorTemp = colorTempCurve.getPoints();
  }

  if (useMasterBrightness) {
    brightnessCurve.setPoints(state.master.brightness_curve);
  } else {
    brightnessCurve.setPoints(editorCustomBrightness || curveDefaults.brightness);
  }
  if (useMasterColor) {
    colorTempCurve.setPoints(state.master.color_temp_curve);
  } else {
    colorTempCurve.setPoints(editorCustomColorTemp || curveDefaults.color_temp);
  }

  setCurveEditable(brightnessCanvas, !useMasterBrightness);
  setCurveEditable(colorTempCanvas, !useMasterColor);
  setSolarEditable("brightness", !useMasterBrightness);
  setSolarEditable("color", !useMasterColor);
  lastUseMasterBrightness = useMasterBrightness;
  lastUseMasterColor = useMasterColor;
  updateCurveOverlays();
  updateCurveDisplayLimits();
}

function setCurveEditable(canvas, editable) {
  if (!canvas) {
    return;
  }
  canvas.style.pointerEvents = editable ? "auto" : "none";
  canvas.classList.toggle("curve-locked", !editable);
}

function setSolarEditable(kind, editable) {
  const toggle = solarControls[kind];
  if (!toggle) {
    return;
  }
  if (!editable) {
    const masterValue = kind === "brightness"
      ? state.master.solar_shift_brightness
      : state.master.solar_shift_color_temp;
    toggle.checked = Boolean(masterValue);
  }
  toggle.disabled = !editable;
  if (toggle.parentElement) {
    toggle.parentElement.classList.toggle("curve-locked", !editable);
  }
}

function buildOverlayBundle(monthSamples, current) {
  const envelopeSamples = current ? monthSamples.concat([current]) : monthSamples;
  const envelope = buildEnvelope(envelopeSamples);
  return {
    envelope,
    months: monthSamples,
    current,
  };
}

function getBaseSunTimes(solar, circadian) {
  if (solar && Array.isArray(solar.months) && solar.months.length) {
    const march = solar.months.find((month) => month.month === 3);
    if (march && Number.isFinite(march.sunrise) && Number.isFinite(march.sunset)) {
      return { baseSunrise: march.sunrise, baseSunset: march.sunset };
    }
  }
  return {
    baseSunrise: solar ? solar.today.sunrise : null,
    baseSunset: solar ? solar.today.sunset : null,
  };
}

function buildEnvelope(monthSamples) {
  if (!monthSamples.length) {
    return null;
  }
  if (monthSamples.length === 1) {
    return { min: monthSamples[0], max: monthSamples[0] };
  }
  const min = [];
  const max = [];
  const steps = monthSamples[0].length;
  for (let i = 0; i < steps; i += 1) {
    const values = monthSamples.map((samples) => samples[i].v);
    min.push({ t: monthSamples[0][i].t, v: Math.min(...values) });
    max.push({ t: monthSamples[0][i].t, v: Math.max(...values) });
  }
  return { min, max };
}

function buildScaledSamples(points, baseSunrise, baseSunset, sunrise, sunset, min, max, dstOffset) {
  if (![baseSunrise, baseSunset, sunrise, sunset].every(Number.isFinite)) {
    return [];
  }
  const samples = [];
  const step = 2;
  for (let t = 0; t <= 1440; t += step) {
    const shifted = (t - (dstOffset || 0) + 1440) % 1440;
    const baseT = unscaleTime(shifted, baseSunrise, baseSunset, sunrise, sunset);
    const v = sampleCurve(points, baseT, min, max);
    samples.push({ t, v });
  }
  return samples;
}

function evaluateCurveBackend(points, tMinutes) {
  const normalized = points
    .filter((point) => point && Number.isFinite(point.t) && Number.isFinite(point.v))
    .map((point) => ({
      t: Math.max(0, Math.min(1440, Number(point.t))),
      v: Number(point.v),
    }))
    .sort((a, b) => a.t - b.t);

  if (normalized.length < 2) {
    return null;
  }

  const t = ((tMinutes % 1440) + 1440) % 1440;
  const extended = normalized
    .map((point) => ({ t: point.t - 1440, v: point.v }))
    .concat(normalized)
    .concat(normalized.map((point) => ({ t: point.t + 1440, v: point.v })));
  const start = normalized.length;
  const end = normalized.length * 2;

  let idx = start;
  while (idx < end - 1 && t > extended[idx + 1].t) {
    idx += 1;
  }

  const p0 = extended[Math.max(idx - 1, 0)];
  const p1 = extended[idx];
  const p2 = extended[idx + 1];
  const p3 = extended[Math.min(idx + 2, extended.length - 1)];
  const span = p2.t - p1.t;
  if (span <= 0) {
    return p1.v;
  }
  const localT = (t - p1.t) / span;
  return monotoneHermite(p0, p1, p2, p3, localT, span);
}

function computeCurrentValue(points, baseSunrise, baseSunset, sunrise, sunset, min, max, dstOffset, nowMinutes) {
  if (!Array.isArray(points) || points.length < 2) {
    return null;
  }
  const tMinutes = Number.isFinite(nowMinutes)
    ? nowMinutes
    : new Date().getHours() * 60 + new Date().getMinutes() + new Date().getSeconds() / 60;
  if (![baseSunrise, baseSunset, sunrise, sunset].every(Number.isFinite)) {
    const value = evaluateCurveBackend(points, tMinutes);
    return Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : null;
  }
  const shifted = (tMinutes - (dstOffset || 0) + 1440) % 1440;
  const baseT = unscaleTime(shifted, baseSunrise, baseSunset, sunrise, sunset);
  const value = evaluateCurveBackend(points, baseT);
  return Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : null;
}


function unscaleTime(actualT, baseSunrise, baseSunset, sunrise, sunset) {
  if (![baseSunrise, baseSunset, sunrise, sunset].every(Number.isFinite)) {
    return actualT;
  }
  const dayBase = baseSunset - baseSunrise;
  const dayActual = sunset - sunrise;
  const nightBase = 1440 - dayBase;
  const nightActual = 1440 - dayActual;
  const baseNoon = 720;
  const actualNoon = 720;
  const baseMidnight = 0;
  const actualMidnight = 0;
  const transition = 60;
  const warpStrength = 1;

  const t = ((actualT % 1440) + 1440) % 1440;
  const dayMap = () => {
    if (dayActual <= 0 || dayBase <= 0) {
      return t;
    }
    const delta = t - actualNoon;
    return baseNoon + (delta * dayBase) / dayActual;
  };

  const nightMap = () => {
    if (nightActual <= 0 || nightBase <= 0) {
      return t;
    }
    const nightDelta = normalizeSignedDelta(t, actualMidnight);
    return (baseMidnight + (nightDelta * nightBase) / nightActual + 1440) % 1440;
  };

  const inDay = t >= sunrise && t < sunset;
  const sunriseBlend = t >= sunrise - transition && t <= sunrise + transition;
  const sunsetBlend = t >= sunset - transition && t <= sunset + transition;

  if (sunriseBlend) {
    const alpha = smoothstep((t - (sunrise - transition)) / (2 * transition));
    return mix(nightMap(), dayMap(), alpha);
  }
  if (sunsetBlend) {
    const alpha = smoothstep((t - (sunset - transition)) / (2 * transition));
    return mix(dayMap(), nightMap(), alpha);
  }

  const mapped = inDay ? dayMap() : nightMap();
  return mix(t, mapped, warpStrength);
}

function normalizeSignedDelta(value, center) {
  let delta = value - center;
  if (delta > 720) {
    delta -= 1440;
  } else if (delta < -720) {
    delta += 1440;
  }
  return delta;
}

function smoothstep(x) {
  const t = Math.max(0, Math.min(1, x));
  return t * t * (3 - 2 * t);
}

function mix(a, b, t) {
  return a + (b - a) * t;
}

function initCurveEditors() {
  if (!brightnessCanvas || !colorTempCanvas || brightnessCurve || colorTempCurve) {
    return;
  }
  brightnessCurve = new CurveEditor(brightnessCanvas, {
    min: 0,
    max: 255,
    color: "#f4c84b",
    onChange: () => {
      updateCurveOverlays();
      updateCurveDisplayLimits();
    },
    formatValue: (value) => `${Math.round(value)}%`,
  });
  colorTempCurve = new CurveEditor(colorTempCanvas, {
    min: 2000,
    max: 6500,
    color: "#6bd6ff",
    onChange: () => {
      updateCurveOverlays();
      updateCurveDisplayLimits();
    },
    formatValue: (value) => `${Math.round(value)}K`,
  });
}

function initMasterEditors() {
  if (!masterBrightnessCanvas || !masterColorTempCanvas || masterBrightnessCurve || masterColorTempCurve) {
    return;
  }
  masterBrightnessCurve = new CurveEditor(masterBrightnessCanvas, {
    min: 0,
    max: 255,
    color: "#f4c84b",
    onChange: () => {
      state.master.brightness_curve = masterBrightnessCurve.getPoints();
      updateMasterOverlays();
      if (useMasterBrightnessToggle && useMasterBrightnessToggle.checked) {
        updateEditorCurveUsage();
      }
    },
    formatValue: (value) => `${Math.round((value / 255) * 100)}%`,
  });
  masterColorTempCurve = new CurveEditor(masterColorTempCanvas, {
    min: 2000,
    max: 6500,
    color: "#6bd6ff",
    onChange: () => {
      state.master.color_temp_curve = masterColorTempCurve.getPoints();
      updateMasterOverlays();
      if (useMasterColorToggle && useMasterColorToggle.checked) {
        updateEditorCurveUsage();
      }
    },
    formatValue: (value) => `${Math.round(value)}K`,
  });
}

async function saveConfig() {
  const resp = await fetch("api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ controllers: state.controllers, master: state.master }),
  });

  if (!resp.ok) {
    throw new Error("Failed to save config");
  }
}

function validateForm() {
  const name = nameInput.value.trim();
  const uniqueId = uniqueInput.value.trim();
  const selectedLights = currentSelectedLights.slice();
  
  if (!name) {
    return "Name is required.";
  }

  const duplicateName = state.controllers.some((controller, idx) => {
    if (idx === state.editingIndex) return false;
    return (controller.name || "").trim().toLowerCase() === name.toLowerCase();
  });
  if (duplicateName) {
    return "Name already exists.";
  }

  if (!selectedLights.length) {
    return "Select at least one input light.";
  }

  if (uniqueId) {
    const duplicateId = state.controllers.some((controller, idx) => {
      if (idx === state.editingIndex) return false;
      return (controller.unique_id || "").trim().toLowerCase() === uniqueId.toLowerCase();
    });
    if (duplicateId) {
      return "Unique ID already exists.";
    }
  }

  if (circadianToggle && circadianToggle.checked) {
    const useMasterBrightness = useMasterBrightnessToggle ? useMasterBrightnessToggle.checked : false;
    const useMasterColor = useMasterColorToggle ? useMasterColorToggle.checked : false;
    const brightnessPoints = useMasterBrightness
      ? state.master.brightness_curve
      : (brightnessCurve ? brightnessCurve.getPoints() : []);
    const colorPoints = useMasterColor
      ? state.master.color_temp_curve
      : (colorTempCurve ? colorTempCurve.getPoints() : []);

    if (!brightnessPoints || brightnessPoints.length < 2) {
      return "Brightness curve needs at least two points.";
    }
    if (!colorPoints || colorPoints.length < 2) {
      return "Color temperature curve needs at least two points.";
    }
  }

  return null;
}

addBtn.addEventListener("click", () => openEditor(null));
cancelBtn.addEventListener("click", closeEditor);
if (circadianToggle) {
  circadianToggle.addEventListener("change", toggleCircadianFields);
}
if (sleepUseMasterToggle) {
  sleepUseMasterToggle.addEventListener("change", updateSleepOverrides);
}
if (wakeupUseMasterToggle) {
  wakeupUseMasterToggle.addEventListener("change", updateWakeupOverrides);
}
if (solarBrightnessToggle) {
  solarBrightnessToggle.addEventListener("change", updateCurveOverlays);
}
if (solarColorToggle) {
  solarColorToggle.addEventListener("change", updateCurveOverlays);
}
if (useMasterBrightnessToggle) {
  useMasterBrightnessToggle.addEventListener("change", updateEditorCurveUsage);
}
if (useMasterColorToggle) {
  useMasterColorToggle.addEventListener("change", updateEditorCurveUsage);
}
if (saveMasterBtn) {
  saveMasterBtn.addEventListener("click", async () => {
    if (masterBrightnessCurve) {
      state.master.brightness_curve = masterBrightnessCurve.getPoints();
    }
    if (masterColorTempCurve) {
      state.master.color_temp_curve = masterColorTempCurve.getPoints();
    }
    if (masterSolarBrightnessToggle) {
      state.master.solar_shift_brightness = masterSolarBrightnessToggle.checked;
    }
    if (masterSolarColorToggle) {
      state.master.solar_shift_color_temp = masterSolarColorToggle.checked;
    }
    state.master.weather = {
      cloud_sensor: weatherCloudInput ? weatherCloudInput.value.trim() : "",
      uv_sensor: weatherUvInput ? weatherUvInput.value.trim() : "",
      visibility_sensor: weatherVisibilityInput ? weatherVisibilityInput.value.trim() : "",
      weather_code_sensor: weatherCodeInput ? weatherCodeInput.value.trim() : "",
      uv_max: Number((weatherUvMaxInput && weatherUvMaxInput.value) || 8),
      visibility_max_km: Number((weatherVisibilityMaxInput && weatherVisibilityMaxInput.value) || 10),
      max_reduction_pct: Number((weatherMaxReductionInput && weatherMaxReductionInput.value) || 60),
    };
    state.master.smoothing = {
      brightness_rate_pct: roundTo2(Number(coalesce(smoothBrightnessRateInput && smoothBrightnessRateInput.value, 0.11))),
      ct_rate_k: roundTo2(Number(coalesce(smoothCtRateInput && smoothCtRateInput.value, 2.67))),
    };
    state.master.sleep = {
      brightness_pct: parseIntOr(sleepBrightnessInput ? sleepBrightnessInput.value : undefined, 10),
      color_temp_kelvin: parseIntOr(sleepCtInput ? sleepCtInput.value : undefined, 2200),
      hs_color: [
        parseFloatOr(sleepHueInput ? sleepHueInput.value : undefined, 30),
        parseFloatOr(sleepSatInput ? sleepSatInput.value : undefined, 70),
      ],
    };
    state.master.wakeup = {
      duration_minutes: parseIntOr(wakeupDurationInput ? wakeupDurationInput.value : undefined, 30),
      start_brightness_pct: parseIntOr(wakeupStartBrightnessInput ? wakeupStartBrightnessInput.value : undefined, 1),
    };
    state.master.retry = {
      enabled: retryEnabledToggle ? retryEnabledToggle.checked : true,
      delay_seconds: parseIntOr(retryDelayInput ? retryDelayInput.value : undefined, 2),
      max_retries: parseIntOr(retryMaxInput ? retryMaxInput.value : undefined, 3),
      tolerance_brightness: parseIntOr(retryTolBrightnessInput ? retryTolBrightnessInput.value : undefined, 2),
      tolerance_ct_k: parseIntOr(retryTolCtInput ? retryTolCtInput.value : undefined, 25),
      tolerance_hs: parseFloatOr(retryTolHsInput ? retryTolHsInput.value : undefined, 3),
      tolerance_rgb: parseIntOr(retryTolRgbInput ? retryTolRgbInput.value : undefined, 3),
      tolerance_xy: parseFloatOr(retryTolXyInput ? retryTolXyInput.value : undefined, 0.01),
    };
    state.master.away = {
      start_minutes: parseTimeToMinutes(awayStartInput ? awayStartInput.value : undefined, 360),
      end_minutes: parseTimeToMinutes(awayEndInput ? awayEndInput.value : undefined, 1350),
      min_minutes: parseIntOr(awayMinMinutesInput ? awayMinMinutesInput.value : undefined, 30),
      max_minutes: parseIntOr(awayMaxMinutesInput ? awayMaxMinutesInput.value : undefined, 180),
      offset_minutes: parseIntOr(awayOffsetMinutesInput ? awayOffsetMinutesInput.value : undefined, 30),
    };
    try {
      await saveConfig();
      await loadData();
    } catch (err) {
      alert("Failed to save master curves.");
    }
  });
}
if (toggleMasterBtn) {
  toggleMasterBtn.addEventListener("click", () => {
    const isHidden = masterSection ? masterSection.classList.contains("hidden") : true;
    setMasterVisible(isHidden);
  });
}
if (hideMasterBtn) {
  hideMasterBtn.addEventListener("click", () => setMasterVisible(false));
}
if (masterSolarBrightnessToggle) {
  masterSolarBrightnessToggle.addEventListener("change", () => {
    state.master.solar_shift_brightness = masterSolarBrightnessToggle.checked;
    updateMasterOverlays();
    updateEditorCurveUsage();
  });
}
if (masterSolarColorToggle) {
  masterSolarColorToggle.addEventListener("change", () => {
    state.master.solar_shift_color_temp = masterSolarColorToggle.checked;
    updateMasterOverlays();
    updateEditorCurveUsage();
  });
}
if (controllerSearch) {
  controllerSearch.addEventListener("input", () => renderControllers(true));
}
if (controllerSort) {
  controllerSort.addEventListener("change", () => renderControllers(true));
}
if (filterCircadian) {
  filterCircadian.addEventListener("change", () => renderControllers(true));
}
if (filterMasterBrightness) {
  filterMasterBrightness.addEventListener("change", () => renderControllers(true));
}
if (filterMasterColor) {
  filterMasterColor.addEventListener("change", () => renderControllers(true));
}
if (bulkSelectAll) {
  bulkSelectAll.addEventListener("click", () => {
    state.filteredControllers.forEach((controller) => {
      state.selection.add(normalizeControllerKey(controller));
    });
    renderControllers(true);
  });
}
if (bulkClear) {
  bulkClear.addEventListener("click", () => {
    state.selection.clear();
    renderControllers(true);
  });
}
if (bulkActions) {
  bulkActions.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }
    const action = target.dataset.bulk;
    if (action) {
      applyBulkAction(action);
    }
  });
}
if (brightnessMinInput && brightnessMaxInput) {
  brightnessMinInput.addEventListener("input", syncLimitInputs);
  brightnessMaxInput.addEventListener("input", syncLimitInputs);
}
if (ctMinInput && ctMaxInput) {
  ctMinInput.addEventListener("input", syncLimitInputs);
  ctMaxInput.addEventListener("input", syncLimitInputs);
}
if (weatherMinInput) {
  weatherMinInput.addEventListener("input", syncLimitInputs);
}
if (circadianIntervalInput) {
  circadianIntervalInput.addEventListener("change", async () => {
    await saveRuntimeIntervals();
    const value = Number.parseInt(circadianIntervalInput.value, 10);
    if (Number.isFinite(value)) {
      graphRefreshSeconds = value;
      updateGraphRefreshTimer();
    }
  });
}
if (wakeupIntervalInput) {
  wakeupIntervalInput.addEventListener("change", async () => {
    await saveRuntimeIntervals();
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorText.textContent = "";

  const error = validateForm();
  if (error) {
    errorText.textContent = error;
    return;
  }

  const name = nameInput.value.trim();
  const uniqueId = uniqueInput.value.trim();
  const selectedLights = currentSelectedLights.slice();

  const existing = state.editingIndex !== null ? state.controllers[state.editingIndex] : null;
  const existingCircadian = existing && existing.circadian ? existing.circadian : {};
  const { baseSunrise, baseSunset } = getBaseSunTimes(state.solar, existingCircadian);

  const useMasterBrightness = useMasterBrightnessToggle ? useMasterBrightnessToggle.checked : false;
  const useMasterColor = useMasterColorToggle ? useMasterColorToggle.checked : false;
  const sleepUseMaster = sleepUseMasterToggle ? sleepUseMasterToggle.checked : true;
  const wakeupUseMaster = wakeupUseMasterToggle ? wakeupUseMasterToggle.checked : true;
  const sleepPayload = {
    use_master: sleepUseMaster,
  };
  if (!sleepUseMaster) {
    sleepPayload.brightness_pct = clampValue(
      parseIntOr(sleepBrightnessOverrideInput ? sleepBrightnessOverrideInput.value : undefined, 10),
      1,
      100
    );
    sleepPayload.color_temp_kelvin = clampValue(
      parseIntOr(sleepCtOverrideInput ? sleepCtOverrideInput.value : undefined, 2200),
      1500,
      8000
    );
    sleepPayload.hs_color = [
      clampValue(parseFloatOr(sleepHueOverrideInput ? sleepHueOverrideInput.value : undefined, 30), 0, 360),
      clampValue(parseFloatOr(sleepSatOverrideInput ? sleepSatOverrideInput.value : undefined, 70), 0, 100),
    ];
  }
  const wakeupPayload = {
    use_master: wakeupUseMaster,
  };
  if (!wakeupUseMaster) {
    wakeupPayload.duration_minutes = clampValue(
      parseIntOr(wakeupDurationOverrideInput ? wakeupDurationOverrideInput.value : undefined, 30),
      1,
      240
    );
    wakeupPayload.start_brightness_pct = clampValue(
      parseIntOr(wakeupStartBrightnessOverrideInput ? wakeupStartBrightnessOverrideInput.value : undefined, 1),
      1,
      100
    );
  }
  const payload = {
    name,
    unique_id: uniqueId || name,
    input_lights: selectedLights,
    weather_enabled: weatherEnabledToggle ? weatherEnabledToggle.checked : false,
    limits: readLimitInputs(),
    sleep: sleepPayload,
    wakeup: wakeupPayload,
    circadian: {
      enabled: circadianToggle ? circadianToggle.checked : false,
      use_master_brightness: useMasterBrightness,
      use_master_color_temp: useMasterColor,
      brightness_enabled: editorBrightnessEnabled,
      color_temp_enabled: editorColorTempEnabled,
      solar_shift_brightness: solarBrightnessToggle ? solarBrightnessToggle.checked : true,
      solar_shift_color_temp: solarColorToggle ? solarColorToggle.checked : true,
      brightness_curve: useMasterBrightness
        ? editorCustomBrightness || curveDefaults.brightness
        : brightnessCurve
          ? brightnessCurve.getPoints()
          : [],
      color_temp_curve: useMasterColor
        ? editorCustomColorTemp || curveDefaults.color_temp
        : colorTempCurve
          ? colorTempCurve.getPoints()
          : [],
      base_sunrise: baseSunrise,
      base_sunset: baseSunset,
    },
  };

  if (state.editingIndex !== null) {
    state.controllers[state.editingIndex] = payload;
  } else {
    state.controllers.push(payload);
  }

  try {
    await saveConfig();
    closeEditor();
    await loadData();
  } catch (err) {
    errorText.textContent = "Failed to save configuration.";
  }
});

async function deleteController(index) {
  if (!confirm("Delete this controller?")) {
    return;
  }
  state.controllers.splice(index, 1);
  try {
    await saveConfig();
    await loadData();
  } catch (err) {
    errorText.textContent = "Failed to save configuration.";
  }
}

loadData().catch(() => {
  if (controllerTable) { controllerTable.innerHTML = "<div class=\"controller-empty\">Unable to load data. Check add-on logs.</div>"; }
});

function updateGraphRefreshTimer() {
  if (graphRefreshTimer) {
    clearInterval(graphRefreshTimer);
  }
  graphRefreshTimer = setInterval(() => {
    if (masterSection && !masterSection.classList.contains("hidden")) {
      updateMasterOverlays();
    }
    if (!editor.classList.contains("hidden")) {
      updateCurveOverlays();
    }
  }, graphRefreshSeconds * 1000);
}

async function saveRuntimeIntervals() {
  const circadianValue = Number.parseInt(
    coalesce(circadianIntervalInput ? circadianIntervalInput.value : undefined, "60"),
    10
  );
  const wakeupValue = Number.parseInt(
    coalesce(wakeupIntervalInput ? wakeupIntervalInput.value : undefined, "2"),
    10
  );
  if (!Number.isFinite(circadianValue) || circadianValue < 1 || circadianValue > 3600) {
    if (circadianIntervalInput) {
      circadianIntervalInput.value = 60;
    }
    return;
  }
  if (!Number.isFinite(wakeupValue) || wakeupValue < 1 || wakeupValue > 3600) {
    if (wakeupIntervalInput) {
      wakeupIntervalInput.value = 2;
    }
    return;
  }
  try {
    await fetch("api/runtime", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        circadian_interval: circadianValue,
        wakeup_interval: wakeupValue,
      }),
    });
  } catch (err) {
    // No-op; UI will keep the last valid value.
  }
}

if (lightSearch) {
  lightSearch.addEventListener("input", () => {
    renderLightLists(currentSelectedLights);
  });
}

if (addSelectedBtn) {
  addSelectedBtn.addEventListener("click", () => {
    addSelectedLights(collectCheckedIds(availableList));
  });
}

if (addAllBtn) {
  addAllBtn.addEventListener("click", () => {
    if (!availableList) {
      return;
    }
    const ids = Array.from(availableList.querySelectorAll("input[type=checkbox]:not(:disabled)")).map(
      (input) => input.value
    );
    addSelectedLights(ids);
  });
}

if (removeSelectedBtn) {
  removeSelectedBtn.addEventListener("click", () => {
    removeSelectedLights(collectCheckedIds(selectedList));
  });
}

if (removeAllBtn) {
  removeAllBtn.addEventListener("click", () => {
    currentSelectedLights = [];
    renderLightLists(currentSelectedLights);
    updateLimitBoundsFromSelection();
  });
}








class CurveEditor {
  constructor(canvas, options) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.min = options.min;
    this.max = options.max;
    this.displayMin = Number.isFinite(options.displayMin) ? options.displayMin : this.min;
    this.displayMax = Number.isFinite(options.displayMax) ? options.displayMax : this.max;
    this.valueTransform = options.valueTransform || ((value) => value);
    this.valueInverse = options.valueInverse || ((value) => value);
    this.color = options.color;
    this.onChange = options.onChange || null;
    this.formatValue = options.formatValue || null;
    this.showNowLine = options.showNowLine !== false;
    this.showNowValue = options.showNowValue !== false;
    this.nowValue = null;
    this.nowValueDisplay = null;
    this.nowMinutes = null;
    this.points = [];
    this.dragIndex = null;
    this.overlays = null;
    this._bindEvents();
    this._resize();
    window.addEventListener("resize", () => this._resize());
  }

  resize() {
    this._resize();
  }

  setPoints(points) {
    this.points = this._normalizePoints(points);
    this._render();
  }

  setDisplayRange(displayMin, displayMax) {
    this.displayMin = displayMin;
    this.displayMax = displayMax;
    this._render();
  }

  setValueTransform(valueTransform, valueInverse) {
    this.valueTransform = valueTransform || ((value) => value);
    this.valueInverse = valueInverse || ((value) => value);
    this._render();
  }

  getPoints() {
    return this.points.map((point) => ({ t: point.t, v: point.v }));
  }

  setOverlays(overlays) {
    this.overlays = overlays;
    this._render();
  }

  setNowValue(value) {
    this.nowValue = Number.isFinite(value) ? value : null;
    this._render();
  }

  setNowMinutes(minutes) {
    this.nowMinutes = Number.isFinite(minutes) ? minutes : null;
    this._render();
  }

  setNowValueDisplay(value) {
    this.nowValueDisplay = Number.isFinite(value) ? value : null;
    this._render();
  }

  _normalizePoints(points) {
    if (!Array.isArray(points)) {
      return [];
    }
    const normalized = points
      .map((point) => ({
        t: Math.max(0, Math.min(1440, Number(point.t) || 0)),
        v: Math.max(this.min, Math.min(this.max, Number(point.v) || this.min)),
      }))
      .sort((a, b) => a.t - b.t);

    return normalized.length ? normalized : [];
  }

  _bindEvents() {
    this.canvas.addEventListener("pointerdown", (event) => this._onPointerDown(event));
    this.canvas.addEventListener("pointermove", (event) => this._onPointerMove(event));
    this.canvas.addEventListener("pointerup", () => this._onPointerUp());
    this.canvas.addEventListener("pointerleave", () => this._onPointerUp());
    this.canvas.addEventListener("dblclick", (event) => this._onDoubleClick(event));
  }

  _resize() {
    const ratio = window.devicePixelRatio || 1;
    const width = this.canvas.clientWidth || this.canvas.width;
    const height = this.canvas.clientHeight || this.canvas.height;
    this.canvas.width = width * ratio;
    this.canvas.height = height * ratio;
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    this._render();
  }

  _onPointerDown(event) {
    const pos = this._eventToPoint(event);
    const index = this._hitTest(pos.x, pos.y);
    if (index !== null) {
      if (index === 0) {
        this.lockX = true;
      }
      this.dragIndex = index;
      this.canvas.setPointerCapture(event.pointerId);
      return;
    }
    const point = this._canvasToData(pos.x, pos.y);
    this.points.push(point);
    this.points.sort((a, b) => a.t - b.t);
    this.dragIndex = this.points.indexOf(point);
    this._render();
    if (this.onChange) {
      this.onChange();
    }
  }

  _onPointerMove(event) {
    if (this.dragIndex === null) {
      return;
    }
    const pos = this._eventToPoint(event);
    const point = this._canvasToData(pos.x, pos.y);
    if (this.lockX) {
      point.t = 0;
    }
    this.points[this.dragIndex] = point;
    this.points.sort((a, b) => a.t - b.t);
    this.dragIndex = this.points.findIndex(
      (item) => item.t === point.t && item.v === point.v
    );
    this._render();
    if (this.onChange) {
      this.onChange();
    }
  }

  _onPointerUp() {
    this.dragIndex = null;
    this.lockX = false;
  }

  _onDoubleClick(event) {
    if (this.points.length <= 2) {
      return;
    }
    const pos = this._eventToPoint(event);
    const index = this._hitTest(pos.x, pos.y);
    if (index !== null) {
      this.points.splice(index, 1);
      this._render();
      if (this.onChange) {
        this.onChange();
      }
    }
  }

  _eventToPoint(event) {
    const rect = this.canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  _hitTest(x, y) {
    const hitRadius = 8;
    for (let i = 0; i < this.points.length; i += 1) {
      const point = this.points[i];
      const px = this._tToX(point.t);
      const py = this._vToY(point.v);
      const distance = Math.hypot(px - x, py - y);
      if (distance <= hitRadius) {
        return i;
      }
    }
    return null;
  }

  _canvasToData(x, y) {
    const t = Math.max(0, Math.min(1440, (x / this._width()) * 1440));
    const display = this._displayMax() - (y / this._height()) * this._displaySpan();
    const v = this.valueInverse(display, this.points);
    return {
      t: Math.round(t),
      v: Math.max(this.min, Math.min(this.max, Math.round(v))),
    };
  }

  _tToX(t) {
    return (t / 1440) * this._width();
  }

  _vToY(v) {
    const display = this._toDisplayValue(v);
    const span = this._displaySpan();
    if (!span) {
      return this._height() / 2;
    }
    return this._height() - ((display - this._displayMin()) / span) * this._height();
  }

  _width() {
    return this.canvas.clientWidth || this.canvas.width;
  }

  _height() {
    return this.canvas.clientHeight || this.canvas.height;
  }

  _toDisplayValue(value) {
    const transformed = this.valueTransform(value, this.points);
    return Math.max(this._displayMin(), Math.min(this._displayMax(), transformed));
  }

  _displayMin() {
    return Number.isFinite(this.displayMin) ? this.displayMin : this.min;
  }

  _displayMax() {
    return Number.isFinite(this.displayMax) ? this.displayMax : this.max;
  }

  _displaySpan() {
    const span = this._displayMax() - this._displayMin();
    return span === 0 ? 1 : span;
  }

  _drawOverlayLine(samples, width, height, color, lineWidth = 1.5, dashed = false) {
    if (!samples || samples.length < 2) {
      return;
    }
    const ctx = this.ctx;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    if (dashed) {
      ctx.setLineDash([6, 4]);
    }
    ctx.beginPath();
    samples.forEach((point, idx) => {
      const x = this._tToX(point.t);
      const y = this._vToY(point.v);
      if (idx === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();
    ctx.restore();
  }

  _drawNowLine(width, height) {
    if (!this.showNowLine) {
      return;
    }
    const minutes = Number.isFinite(this.nowMinutes)
      ? this.nowMinutes
      : new Date().getHours() * 60 + new Date().getMinutes() + new Date().getSeconds() / 60;
    const x = this._tToX(minutes);
    const ctx = this.ctx;
    ctx.save();
    ctx.strokeStyle = "rgba(255, 255, 255, 0.35)";
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 6]);
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
    ctx.restore();

    if (!this.showNowValue) {
      return;
    }

    let displayValue = this.nowValueDisplay;
    if (!Number.isFinite(displayValue)) {
      let value = this.nowValue;
      if (!Number.isFinite(value)) {
        const nowPoints = Array.isArray(this.overlays && this.overlays.current) && this.overlays.current.length >= 2
          ? this.overlays.current
          : this.points;
        if (nowPoints.length < 2) {
          return;
        }
        value = sampleCurve(nowPoints, minutes, this.min, this.max);
      }

      if (!Number.isFinite(value)) {
        return;
      }

      displayValue = this._toDisplayValue(value);
    }

    if (!Number.isFinite(displayValue)) {
      return;
    }

    const label = this.formatValue ? this.formatValue(displayValue) : `${Math.round(displayValue)}`;
    this._drawNowLabel(x, label, width);
  }

  _drawNowLabel(x, label, width) {
    const ctx = this.ctx;
    ctx.save();
    ctx.font = "11px 'IBM Plex Mono', monospace";
    const paddingX = 6;
    const paddingY = 3;
    const metrics = ctx.measureText(label);
    const textWidth = metrics.width;
    const boxWidth = textWidth + paddingX * 2;
    const boxHeight = 16;
    let left = x - boxWidth / 2;
    left = Math.max(6, Math.min(width - boxWidth - 6, left));
    const top = 6;
    ctx.fillStyle = "rgba(10, 12, 17, 0.9)";
    ctx.strokeStyle = "rgba(255, 255, 255, 0.2)";
    ctx.lineWidth = 1;
    this._roundRect(ctx, left, top, boxWidth, boxHeight, 6);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "rgba(255, 255, 255, 0.8)";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(label, left + paddingX, top + boxHeight / 2);
    ctx.restore();
  }

  _roundRect(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + width, y, x + width, y + height, r);
    ctx.arcTo(x + width, y + height, x, y + height, r);
    ctx.arcTo(x, y + height, x, y, r);
    ctx.arcTo(x, y, x + width, y, r);
    ctx.closePath();
  }

  _drawEnvelope(envelope, width, height) {
    if (!envelope || !envelope.min || !envelope.max) {
      return;
    }
    const ctx = this.ctx;
    ctx.save();
    ctx.fillStyle = "rgba(255, 255, 255, 0.08)";
    ctx.beginPath();
    envelope.max.forEach((point, idx) => {
      const x = this._tToX(point.t);
      const y = this._vToY(point.v);
      if (idx === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    for (let i = envelope.min.length - 1; i >= 0; i -= 1) {
      const point = envelope.min[i];
      ctx.lineTo(this._tToX(point.t), this._vToY(point.v));
    }
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  _render() {
    const ctx = this.ctx;
    const width = this._width();
    const height = this._height();
    ctx.clearRect(0, 0, width, height);

    ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
    ctx.lineWidth = 1;
    for (let i = 1; i < 8; i += 1) {
      const x = (width / 8) * i;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
    for (let i = 1; i < 4; i += 1) {
      const y = (height / 4) * i;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    ctx.fillStyle = "rgba(255, 255, 255, 0.45)";
    ctx.font = "12px 'IBM Plex Mono', monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const xLabels = [0, 3, 6, 9, 12, 15, 18, 21, 24];
    xLabels.forEach((hour) => {
      const x = (width / 24) * hour;
      ctx.fillText(`${hour}h`, x, height - 18);
    });

    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    const displayMin = this._displayMin();
    const displayMax = this._displayMax();
    const yLabels = [displayMax, Math.round((displayMax + displayMin) / 2), displayMin];
    yLabels.forEach((value, idx) => {
      const y = (height / 2) * idx;
      const label = this.formatValue ? this.formatValue(value) : `${value}`;
      ctx.fillText(label, 6, y + 2);
    });

    let currentOverlay = null;
    if (this.overlays) {
      if (this.overlays.envelope) {
        this._drawEnvelope(this.overlays.envelope, width, height);
      }
      if (Array.isArray(this.overlays.months)) {
        this.overlays.months.forEach((line) => {
          this._drawOverlayLine(line, width, height, "rgba(255, 255, 255, 0.18)");
        });
      }
      currentOverlay = this.overlays.current || null;
    }

    if (this.points.length >= 2) {
      const samples = 720;
      ctx.strokeStyle = this.color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i <= samples; i += 1) {
        const t = (1440 / samples) * i;
        const v = sampleCurve(this.points, t, this.min, this.max);
        const x = this._tToX(t);
        const y = this._vToY(v);
        if (i === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      }
      ctx.stroke();
    }

    if (currentOverlay) {
      this._drawOverlayLine(currentOverlay, width, height, "rgba(255, 255, 255, 0.8)", 2.5, true);
    }

    this._drawNowLine(width, height);

    this.points.forEach((point) => {
      const x = this._tToX(point.t);
      const y = this._vToY(point.v);
      ctx.fillStyle = "#0b0f14";
      ctx.strokeStyle = this.color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });
  }
}

function sampleCurve(points, t, min, max) {
  const normalized = points.slice().sort((a, b) => a.t - b.t);
  if (!normalized.length) {
    return min;
  }
  if (normalized.length === 1) {
    return normalized[0].v;
  }
  const wrapped = normalized.map((point) => ({ t: point.t, v: point.v }));
  const last = wrapped[wrapped.length - 1];
  const first = wrapped[0];
  wrapped.unshift({ t: last.t - 1440, v: last.v });
  wrapped.push({ t: first.t + 1440, v: first.v });

  const target = ((t % 1440) + 1440) % 1440;
  let idx = 1;
  while (idx < wrapped.length - 2 && target > wrapped[idx + 1].t) {
    idx += 1;
  }

  const p0 = wrapped[Math.max(0, idx - 1)];
  const p1 = wrapped[idx];
  const p2 = wrapped[idx + 1];
  const p3 = wrapped[Math.min(wrapped.length - 1, idx + 2)];
  const span = p2.t - p1.t || 1;
  const localT = (target - p1.t) / span;

  const v = monotoneHermite(p0, p1, p2, p3, localT, span);
  return Math.max(min, Math.min(max, v));
}

function catmullRom(p0, p1, p2, p3, t) {
  const t2 = t * t;
  const t3 = t2 * t;
  return 0.5 * (
    2 * p1 +
    (-p0 + p2) * t +
    (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
    (-p0 + 3 * p1 - 3 * p2 + p3) * t3
  );
}

function monotoneHermite(p0, p1, p2, p3, t, span) {
  const d0 = (p2.v - p0.v) / (p2.t - p0.t || 1);
  const d1 = (p3.v - p1.v) / (p3.t - p1.t || 1);
  let m1 = d0;
  let m2 = d1;
  const delta = (p2.v - p1.v) / (p2.t - p1.t || 1);

  if (Math.abs(delta) < 1e-6) {
    m1 = 0;
    m2 = 0;
  } else {
    if (m1 / delta < 0) m1 = 0;
    if (m2 / delta < 0) m2 = 0;
    const limit = 3 * Math.abs(delta);
    if (Math.abs(m1) > limit) m1 = Math.sign(m1) * limit;
    if (Math.abs(m2) > limit) m2 = Math.sign(m2) * limit;
  }

  const t2 = t * t;
  const t3 = t2 * t;
  const h00 = 2 * t3 - 3 * t2 + 1;
  const h10 = t3 - 2 * t2 + t;
  const h01 = -2 * t3 + 3 * t2;
  const h11 = t3 - t2;

  return h00 * p1.v + h10 * m1 * span + h01 * p2.v + h11 * m2 * span;
}




































