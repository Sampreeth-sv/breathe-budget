"use strict";

/* All server text is inserted as text nodes via textContent, never parsed as markup. */

const RISK_ICONS = {
  good: "🟢",
  moderate: "🟡",
  unhealthy_sensitive: "🟠",
  unhealthy: "🔴",
  very_unhealthy: "🟣",
  hazardous: "⚫",
};

const MEMBER_ICONS = {
  "Children": "👧",
  "Older adults": "👴",
  "Adults with asthma, COPD or heart conditions": "💊",
  "Adults": "🧑",
};

const COST_LABELS = {
  free: "Free",
  low: "Low cost",
  medium: "Medium cost",
  high: "Higher cost",
};

const COST_CLASSES = {
  free: "cost-free",
  low: "cost-low",
  medium: "cost-medium",
  high: "cost-high",
};

const EXAMPLE = {
  city: "Delhi",
  adults: 2,
  children: 1,
  seniors: 0,
  respiratory: true,
  commute_mode: "two_wheeler",
  commute_minutes: 40,
  exercise: 30,
  cooking: "lpg",
  heating: "none",
  neighbourhood: 60,
  purifier: false,
  pm25: "",
};

const $ = (id) => document.getElementById(id);

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.id) node.id = options.id;
  if (options.role) node.setAttribute("role", options.role);
  for (const [k, v] of Object.entries(options.attrs || {})) node.setAttribute(k, v);
  for (const child of children) node.append(child);
  return node;
}

function clearNode(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function intValue(id) {
  const value = $(id).value.trim();
  return value === "" ? 0 : Number(value);
}

function readForm() {
  const override = $("pm25").value.trim();
  const body = {
    city: $("city").value.trim(),
    household: {
      adults: intValue("adults"),
      children: intValue("children"),
      seniors: intValue("seniors"),
      respiratory_condition: $("respiratory").checked,
    },
    commute_mode: $("commute_mode").value,
    commute_minutes_each_way: intValue("commute_minutes"),
    cooking_fuel: $("cooking").value,
    heating: $("heating").value,
    has_purifier: $("purifier").checked,
    outdoor_exercise_minutes: intValue("exercise"),
    neighbourhood_households: intValue("neighbourhood") || 1,
  };
  if (override !== "") body.pm25_override = Number(override);
  return body;
}

function validate(body) {
  const problems = [];
  if (body.city.length < 2) problems.push({ id: "city", message: "Enter your city (at least 2 letters)." });
  if (body.household.adults + body.household.children + body.household.seniors < 1) {
    problems.push({ id: "adults", message: "Add at least one person to the household." });
  }
  const numeric = [
    ["adults", body.household.adults, 0, 10],
    ["children", body.household.children, 0, 10],
    ["seniors", body.household.seniors, 0, 10],
    ["commute_minutes", body.commute_minutes_each_way, 0, 240],
    ["exercise", body.outdoor_exercise_minutes, 0, 240],
    ["neighbourhood", body.neighbourhood_households, 1, 10000],
  ];
  for (const [id, value, low, high] of numeric) {
    if (!Number.isFinite(value) || value < low || value > high) {
      problems.push({ id, message: `${$(id).labels[0].textContent}: enter a number from ${low} to ${high}.` });
    }
  }
  if ("pm25_override" in body && (!Number.isFinite(body.pm25_override) || body.pm25_override < 0 || body.pm25_override > 1000)) {
    problems.push({ id: "pm25", message: "PM2.5 reading: enter a number from 0 to 1000." });
  }
  return problems;
}

function showErrors(problems) {
  const box = $("form-errors");
  clearNode(box);
  for (const input of document.querySelectorAll("[aria-invalid]")) input.removeAttribute("aria-invalid");
  if (problems.length === 0) {
    box.hidden = true;
    return;
  }
  box.append(el("p", { text: `Please fix ${problems.length === 1 ? "this" : "these"}:` }));
  const list = el("ul");
  for (const problem of problems) {
    const link = el("a", { text: problem.message });
    link.href = `#${problem.id}`;
    link.addEventListener("click", (event) => {
      event.preventDefault();
      $(problem.id).focus();
    });
    list.append(el("li", {}, [link]));
    const field = $(problem.id);
    if (field) field.setAttribute("aria-invalid", "true");
  }
  box.append(list);
  box.hidden = false;
  box.scrollIntoView({ block: "nearest" });
}

function round(value, digits = 0) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

/* ─── AQI GAUGE ──────────────────────────────────────────────────────── */
function drawAqiGauge(canvas, aqi, level) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const size = 120;
  canvas.width = size * dpr;
  canvas.height = size * dpr;
  canvas.style.width = size + "px";
  canvas.style.height = size + "px";
  ctx.scale(dpr, dpr);

  const cx = size / 2, cy = size / 2;
  const outerR = 52, innerR = 36;
  const startAngle = Math.PI * 0.75;
  const totalAngle = Math.PI * 1.5;

  const COLORS = {
    good: "#4ade80",
    moderate: "#fbbf24",
    unhealthy_sensitive: "#fb923c",
    unhealthy: "#f87171",
    very_unhealthy: "#c084fc",
    hazardous: "#fb7185",
  };

  // Track background
  ctx.beginPath();
  ctx.arc(cx, cy, (outerR + innerR) / 2, startAngle, startAngle + totalAngle);
  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.lineWidth = outerR - innerR;
  ctx.lineCap = "round";
  ctx.stroke();

  // AQI fill (0–500 scale)
  const pct = Math.min(aqi / 500, 1);
  const color = COLORS[level] || "#00e5b8";

  ctx.beginPath();
  ctx.arc(cx, cy, (outerR + innerR) / 2, startAngle, startAngle + totalAngle * pct);
  ctx.strokeStyle = color;
  ctx.lineWidth = outerR - innerR;
  ctx.lineCap = "round";
  ctx.shadowColor = color;
  ctx.shadowBlur = 12;
  ctx.stroke();
  ctx.shadowBlur = 0;

  // AQI number
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = color;
  ctx.font = `800 24px 'Inter', system-ui, sans-serif`;
  ctx.fillText(aqi, cx, cy - 5);

  ctx.fillStyle = "rgba(255,255,255,0.45)";
  ctx.font = `600 10px 'Inter', system-ui, sans-serif`;
  ctx.fillText("AQI", cx, cy + 13);
}

/* ─── TYPEWRITER EFFECT ──────────────────────────────────────────────── */
function typewriterEffect(element, text, speed = 18) {
  element.textContent = "";
  element.classList.add("typing");
  let i = 0;
  function next() {
    if (i < text.length) {
      element.textContent += text[i++];
      setTimeout(next, speed);
    } else {
      element.classList.remove("typing");
    }
  }
  next();
}

/* ─── RENDER ─────────────────────────────────────────────────────────── */
function render(data) {
  // Risk card
  const risk = $("risk");
  risk.dataset.level = data.risk.level;
  $("risk-icon").textContent = RISK_ICONS[data.risk.level] || "●";
  $("risk-label").textContent = data.risk.label;
  $("risk-headline").textContent = data.risk.headline;
  $("stat-pm25").textContent = `${round(data.air.pm25, 1)} µg/m³`;
  $("stat-aqi").textContent = `${data.air.aqi} · ${data.air.category_label}`;
  $("stat-who").textContent = `${data.air.times_who_guideline}×`;

  const place = data.place.country ? `${data.place.name}, ${data.place.country}` : data.place.name;
  const when = data.air.observed_at ? ` · ${data.air.observed_at}` : "";
  const sourceText = $("air-source");
  clearNode(sourceText);
  sourceText.append(
    el("span", { text: "📍 " }),
    el("span", { text: `${place}  ·  ${data.air.source}${when}` })
  );

  // AQI gauge
  const gaugeCanvas = $("aqi-gauge");
  if (gaugeCanvas && gaugeCanvas.getContext) {
    requestAnimationFrame(() => drawAqiGauge(gaugeCanvas, data.air.aqi, data.risk.level));
  }

  // Explanation + badge
  const badge = $("explanation-badge");
  const summaryEl = $("summary");
  if (data.explanation.source === "gemini") {
    badge.textContent = "✨ Explained by Gemini AI";
    badge.className = "explanation-badge gemini-powered";
    $("header-gemini-badge").hidden = false;
    // Typewriter reveal for Gemini content
    setTimeout(() => typewriterEffect(summaryEl, data.explanation.summary, 15), 100);
  } else {
    badge.textContent = "📊 Written from computed numbers";
    badge.className = "explanation-badge rules-powered";
    summaryEl.textContent = data.explanation.summary;
  }

  // Exposure bars (animate after short delay)
  const before = data.dose.total_ug;
  const after = before * (1 - data.combined_reduction_pct / 100);
  const scale = Math.max(before, 1);
  $("val-before").textContent = `${round(before)} µg`;
  $("val-after").textContent = `${round(after)} µg`;

  // Start bars at 0, then animate
  $("bar-before").style.width = "0%";
  $("bar-after").style.width = "0%";
  setTimeout(() => {
    $("bar-before").style.width = "100%";
    $("bar-after").style.width = `${Math.max(2, (after / scale) * 100)}%`;
  }, 300);

  $("impact-text").textContent =
    data.combined_reduction_pct >= 1
      ? `✅ Doing all steps below could cut your daily exposure by about ${round(data.combined_reduction_pct)}%.`
      : "Your current habits are already close to the best you can do on today's air.";

  const parts = $("dose-parts");
  clearNode(parts);
  for (const [label, value] of [
    ["🏠 At home", data.dose.home_ug],
    ["🚌 Commuting", data.dose.commute_ug],
    ["🏃 Exercising outdoors", data.dose.exercise_ug],
  ]) {
    if (value > 0) {
      parts.append(el("li", { text: `${label}: about ${round(value, 1)} µg` }));
    }
  }

  // Action list
  const list = $("actions");
  clearNode(list);
  $("no-actions").hidden = data.actions.length > 0;
  for (const action of data.actions) {
    const badges = el("div", { className: "badges" }, [
      el("span", { className: `badge ${COST_CLASSES[action.cost_tier] || ""}`, text: COST_LABELS[action.cost_tier] || action.cost_tier }),
    ]);
    if (action.exposure_reduction_pct > 0) {
      badges.append(
        el("span", {
          className: "badge impact",
          text: `↓ ${round(action.exposure_reduction_pct)}% exposure (${round(action.exposure_reduction_ug, 1)} µg/day)`,
        }),
      );
    }
    if (action.co2e_kg_saved_per_day > 0) {
      badges.append(el("span", { className: "badge", text: `🌱 Saves ~${action.co2e_kg_saved_per_day} kg CO₂e/day` }));
    }
    const noteEl = action.note ? el("p", { className: "muted small", text: action.note }) : null;
    list.append(
      el("li", { className: "action" }, [
        el("h4", { text: action.title }),
        el("p", { text: action.detail }),
        ...(noteEl ? [noteEl] : []),
        badges,
      ]),
    );
  }

  // Clean window
  const windowEl = $("window-text");
  clearNode(windowEl);
  windowEl.append(el("span", { text: data.clean_window.advice }));

  // Member guidance
  const members = $("members");
  clearNode(members);
  for (const note of data.member_notes) {
    const icon = MEMBER_ICONS[note.group] || "👤";
    const item = el("div", { className: "member-item" }, [
      el("span", { className: "member-icon", text: icon }),
      el("div", {}, [
        el("dt", { className: "member-name", text: note.group }),
        el("dd", { className: "member-advice", text: note.advice }),
      ]),
    ]);
    members.append(item);
  }

  // Community
  const communityText = $("community-text");
  if (data.community.co2e_kg_saved_per_day > 0) {
    communityText.textContent = `If all ${data.community.households} households made the changes that cut emissions, you would avoid about ${data.community.co2e_kg_saved_per_day} kg of CO₂e every day — meaning fewer tailpipes and fires and cleaner air for the whole street.`;
  } else {
    communityText.textContent = `Cleaner air is a shared effort. Here are steps your ${data.community.households} households can take together.`;
  }

  const pledges = $("pledges");
  clearNode(pledges);
  for (const pledge of data.community.pledges) pledges.append(el("li", { text: pledge }));

  $("disclaimer").textContent = data.disclaimer;
}

/* ─── API ─────────────────────────────────────────────────────────────── */
async function requestAdvice(body) {
  const response = await fetch("/api/advice", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    /* non-JSON error body */
  }
  if (!response.ok) {
    const error = new Error((payload && payload.detail) || "Something went wrong. Please try again.");
    error.fieldErrors = payload && Array.isArray(payload.errors) ? payload.errors : [];
    throw error;
  }
  return payload;
}

/* ─── SUBMIT ─────────────────────────────────────────────────────────── */
async function onSubmit(event) {
  event.preventDefault();
  const body = readForm();
  const problems = validate(body);
  showErrors(problems);
  if (problems.length) return;

  const button = $("submit");
  const btnText = button.querySelector(".btn-text");
  button.disabled = true;
  button.classList.add("loading");
  btnText.textContent = "Fetching…";
  $("status").textContent = "Fetching air quality and building your plan.";
  $("results").hidden = true;
  $("skeleton-results").hidden = false;

  try {
    const data = await requestAdvice(body);
    $("skeleton-results").hidden = true;
    render(data);
    const results = $("results");
    results.hidden = false;
    $("status").textContent = `Your plan is ready. Air quality is ${data.risk.label.toLowerCase()}.`;
    results.focus({ preventScroll: true });
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    $("skeleton-results").hidden = true;
    const messages = error.fieldErrors && error.fieldErrors.length
      ? error.fieldErrors.map((e) => ({ id: "city", message: e.message }))
      : [{ id: "city", message: error.message }];
    showErrors(messages);
    $("status").textContent = "We couldn't build your plan.";
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
    btnText.textContent = "Get my plan";
  }
}

/* ─── EXAMPLE ────────────────────────────────────────────────────────── */
function fillExample() {
  $("city").value = EXAMPLE.city;
  $("adults").value = EXAMPLE.adults;
  $("children").value = EXAMPLE.children;
  $("seniors").value = EXAMPLE.seniors;
  $("respiratory").checked = EXAMPLE.respiratory;
  $("commute_mode").value = EXAMPLE.commute_mode;
  $("commute_minutes").value = EXAMPLE.commute_minutes;
  $("exercise").value = EXAMPLE.exercise;
  $("cooking").value = EXAMPLE.cooking;
  $("heating").value = EXAMPLE.heating;
  $("neighbourhood").value = EXAMPLE.neighbourhood;
  $("purifier").checked = EXAMPLE.purifier;
  $("pm25").value = EXAMPLE.pm25;
  showErrors([]);
  $("city").focus();
}

$("advice-form").addEventListener("submit", onSubmit);
$("example").addEventListener("click", fillExample);
