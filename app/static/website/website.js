(() => {
  "use strict";

  const state = { bootstrap: null, selectedWallet: null, activeFinalId: null };
  const $ = (id) => document.getElementById(id);
  const esc = (value) => { const d = document.createElement("div"); d.textContent = String(value ?? ""); return d.innerHTML; };
  const money = (value) => `₹${Number(value || 0).toLocaleString("en-IN")}`;
  const logo = (name) => {
    const key = String(name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    const map = {
      paytmbusiness: "paytm-business.png", phonepaybusiness: "phonepe-business.png", phonepebusiness: "phonepe-business.png",
      googlepaybusiness: "googlepay-business.png", gpaybusiness: "googlepay-business.png", bharatpaybusiness: "bharatpe-business.png",
      bharatpebusiness: "bharatpe-business.png", mobikwikbusiness: "mobikwik-business.png", bajajpaybusiness: "bajajpay-business.png",
      pinelabsbusiness: "pinelabs-business.png"
    };
    return `/static/miniapp/logos/${map[key] || "ibw-logo.png"}`;
  };

  let toastTimer;
  function toast(message) {
    const el = $("toast");
    if (!el) return;
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 1800);
  }

  async function copyText(value, message = "Copied ✅") {
    const text = String(value || "").trim();
    if (!text) return;
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
      else {
        const area = document.createElement("textarea");
        area.value = text; area.style.position = "fixed"; area.style.opacity = "0";
        document.body.appendChild(area); area.select(); document.execCommand("copy"); area.remove();
      }
      toast(message);
    } catch (_) { toast("Copy failed — long press to copy"); }
  }

  function showView(name) {
    document.querySelectorAll(".view").forEach((section) => section.classList.toggle("hidden", section.id !== `${name}View`));
    document.querySelectorAll("[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (name === "applications") loadApplications();
  }

  async function api(path, payload = null, form = false) {
    const options = { method: payload ? "POST" : "GET", cache: "no-store", credentials: "same-origin" };
    if (payload) {
      if (form) options.body = payload;
      else { options.headers = { "Content-Type": "application/json" }; options.body = JSON.stringify(payload); }
    }
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.message || "Request failed");
    return data;
  }

  async function loadBootstrap() {
    try {
      state.bootstrap = await api("/website/api/bootstrap");
      $("workingHours").textContent = state.bootstrap.working_hours || "—";
      const badge = $("serviceBadge");
      badge.textContent = state.bootstrap.service_available ? "● ONLINE" : "● CLOSED";
      badge.classList.toggle("online", !!state.bootstrap.service_available);
      badge.classList.toggle("offline", !state.bootstrap.service_available);
      if ($("whatsappLink")) $("whatsappLink").href = state.bootstrap.whatsapp_number ? `https://wa.me/${state.bootstrap.whatsapp_number}` : "https://wa.me/";
      if ($("channelLink")) $("channelLink").href = state.bootstrap.official_channel || "https://t.me/";
      renderWallets();
    } catch (error) {
      $("walletList").innerHTML = `<div class="empty">${esc(error.message)}</div>`;
    }
  }

  function renderWallets() {
    const wallets = state.bootstrap?.wallets || [];
    if (!wallets.length) { $("walletList").innerHTML = '<div class="empty">No wallet service is currently available.</div>'; return; }
    $("walletList").innerHTML = wallets.map((w) => `
      <article class="wallet-card">
        <div class="wallet-top">
          <div class="wallet-brand"><img class="wallet-logo" src="${logo(w.name)}" alt="${esc(w.name)} logo"><div><h3>${esc(w.name)}</h3><div class="processing"><span>Estimated wallet processing time</span><b>${esc(w.processing_time || "Subject to verification")}</b><small>Time may vary depending on document verification.</small></div></div></div>
          <div class="wallet-price">${money(w.total_fee)}</div>
        </div>
        ${w.description ? `<p>${esc(w.description)}</p>` : ""}
        <div class="availability"><i></i><span>Service Available</span></div>
        <div class="fee-grid"><div class="fee-box"><b>First Payment</b><span>${money(w.initial_amount)}</span><small>Pay at application start</small></div><div class="fee-box"><b>Remaining</b><span>${money(w.remaining_amount)}</span><small>After wallet ready</small></div></div>
        <div class="chips">${(w.documents || []).map((d) => `<span class="chip">${esc(d.name)}</span>`).join("")}</div>
        <button type="button" class="primary apply-wallet" data-id="${w.id}">Apply for ${esc(w.name)}</button>
      </article>`).join("");
    document.querySelectorAll(".apply-wallet").forEach((b) => b.addEventListener("click", () => openApplication(Number(b.dataset.id))));
  }

  function docKind(d) {
    const s = `${d.manual_kind || ""} ${d.name || ""} ${d.manual_label || ""}`.toLowerCase();
    if (s.includes("bank") || s.includes("ifsc") || s.includes("account")) return "bank";
    if (s.includes("mobile") || s.includes("phone")) return "mobile";
    if (s.includes("aadhaar") || s.includes("aadhar")) return "aadhaar";
    if (s.includes("pan")) return "pan";
    return "single";
  }

  function manualInput(d) {
    const id = `manual_${d.id}`, kind = docKind(d);
    if (kind === "bank") return `<div class="field"><label>Account Number<input id="${id}_account" inputmode="numeric" placeholder="Enter Account Number"></label><label>IFSC Code<input id="${id}_ifsc" autocapitalize="characters" placeholder="Enter IFSC Code"></label></div>`;
    return `<div class="field"><label>${esc(d.manual_label || d.name)}<input id="${id}" ${kind === "mobile" || kind === "aadhaar" ? 'inputmode="numeric"' : ""} ${kind === "pan" ? 'maxlength="10" style="text-transform:uppercase"' : ""} placeholder="${esc(d.manual_label || d.name)}"></label></div>`;
  }

  function documentBlock(d) {
    const manual = d.manual_allowed ? `<div id="manualArea_${d.id}">${manualInput(d)}</div>` : "";
    const upload = d.upload_allowed ? `<div id="uploadArea_${d.id}" class="${d.manual_allowed ? "hidden" : ""}"><div class="field"><label>Upload ${esc(d.name)}<input id="file_${d.id}" type="file" accept="image/jpeg,image/png,image/webp,application/pdf" data-file-label="fileName_${d.id}"></label><small>JPG, PNG, WEBP or PDF • Max 10 MB</small><span id="fileName_${d.id}" class="file-name"></span></div></div>` : "";
    const switcher = d.manual_allowed && d.upload_allowed ? `<div class="method-switch"><button type="button" class="active" data-doc="${d.id}" data-method="manual">Enter Manually</button><button type="button" data-doc="${d.id}" data-method="upload">Upload File</button></div>` : "";
    return `<div class="form-card"><h3>${esc(d.name)}${d.required ? " *" : ""}</h3>${switcher}${manual}${upload}</div>`;
  }

  function openApplication(id) {
    state.selectedWallet = state.bootstrap?.wallets?.find((w) => Number(w.id) === id);
    if (!state.selectedWallet) return;
    const w = state.selectedWallet;
    $("applyContent").innerHTML = `
      <div class="apply-summary"><div class="apply-summary-brand"><img class="wallet-logo" src="${logo(w.name)}" alt="${esc(w.name)} logo"><div><p class="eyebrow">New website application</p><h2>${esc(w.name)}</h2><p>Total Fee ${money(w.total_fee)} • First Payment ${money(w.initial_amount)}</p></div></div></div>
      <form id="applicationForm" class="application-layout">
        <div>
          <div class="form-card"><h3>Customer Details</h3><div class="field"><label>Full Name *<input id="fullName" maxlength="150" autocomplete="name" placeholder="Enter full name"></label><label>Mobile Number *<input id="mobileNumber" inputmode="numeric" maxlength="10" autocomplete="tel" placeholder="10-digit mobile number"></label></div></div>
          ${(w.documents || []).map(documentBlock).join("")}
        </div>
        <aside class="payment-sidebar">
          <div class="form-card"><h3>Initial Payment</h3>${w.has_qr ? `<div class="qr"><img src="/website/wallet/${w.id}/qr" alt="Payment QR"></div>` : '<div class="empty">Payment QR is not configured. Use UPI details below.</div>'}
            <div class="payment-meta"><div><b>Amount</b><br>${money(w.initial_amount)}</div><button type="button" class="copyable" data-copy-value="${esc(w.upi_id || "")}" data-copy-message="UPI ID copied ✅"><b>UPI ID</b><br>${esc(w.upi_id || "Contact Support")}<small>Tap to copy</small></button><div><b>Banking Name</b><br>${esc(w.banking_name || "Verify in UPI App")}</div><div><b>Remaining</b><br>${money(w.remaining_amount)}</div></div>
            <div class="field" style="margin-top:14px"><label>UTR Number *<input id="initialUtr" autocomplete="off" placeholder="Enter payment UTR"></label><label>Payment Receipt *<input id="initialReceipt" type="file" accept="image/jpeg,image/png,image/webp,application/pdf" data-file-label="receiptFileName"></label><span id="receiptFileName" class="file-name"></span></div>
          </div>
          <div id="applyError" class="error hidden"></div><button id="submitApplication" class="primary" type="submit" style="width:100%">Submit Application Securely</button>
        </aside>
      </form>`;

    document.querySelectorAll(".method-switch button").forEach((b) => b.addEventListener("click", () => {
      const docId = b.dataset.doc, method = b.dataset.method;
      b.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
      $(`manualArea_${docId}`)?.classList.toggle("hidden", method !== "manual");
      $(`uploadArea_${docId}`)?.classList.toggle("hidden", method !== "upload");
    }));
    document.querySelectorAll('input[type="file"][data-file-label]').forEach((input) => input.addEventListener("change", () => {
      const target = $(input.dataset.fileLabel); if (target) target.textContent = input.files?.[0] ? `Selected: ${input.files[0].name}` : "";
    }));
    $("applicationForm").addEventListener("submit", submitApplication);
    showView("apply");
  }

  function manualValue(d) {
    const area = $(`manualArea_${d.id}`);
    if (!area || area.classList.contains("hidden")) return "";
    if (docKind(d) === "bank") {
      const account = $(`manual_${d.id}_account`).value.trim(), ifsc = $(`manual_${d.id}_ifsc`).value.trim().toUpperCase();
      return account || ifsc ? JSON.stringify({ account_number: account, ifsc }) : "";
    }
    let value = $(`manual_${d.id}`)?.value.trim() || "";
    return docKind(d) === "pan" ? value.toUpperCase() : value;
  }

  async function submitApplication(event) {
    event.preventDefault();
    const button = $("submitApplication"), errorBox = $("applyError"), receipt = $("initialReceipt")?.files?.[0];
    errorBox.classList.add("hidden");
    if (!receipt) { errorBox.textContent = "Please select the initial payment receipt."; errorBox.classList.remove("hidden"); return; }
    const form = new FormData();
    form.append("full_name", $("fullName").value.trim()); form.append("mobile_number", $("mobileNumber").value.trim());
    form.append("wallet_id", state.selectedWallet.id); form.append("utr", $("initialUtr").value.trim());
    const manual = {};
    (state.selectedWallet.documents || []).forEach((d) => {
      const value = manualValue(d); if (value) manual[String(d.id)] = value;
      const file = $(`file_${d.id}`)?.files?.[0]; if (file && !$(`uploadArea_${d.id}`)?.classList.contains("hidden")) form.append(`doc_${d.id}`, file);
    });
    form.append("manual_values", JSON.stringify(manual)); form.append("receipt", receipt, receipt.name);
    button.disabled = true; button.textContent = "Submitting securely…";
    try {
      const data = await api("/website/api/applications", form, true);
      $("successCode").textContent = data.application.application_id; $("successCode").dataset.copyValue = data.application.application_id;
      $("successWallet").textContent = `${data.application.wallet} • ${data.application.status_label}`; showView("success");
    } catch (error) { errorBox.textContent = error.message; errorBox.classList.remove("hidden"); }
    finally { button.disabled = false; button.textContent = "Submit Application Securely"; }
  }

  const statusSteps = ["PAYMENT_UNDER_VERIFICATION", "PROCESSING", "WALLET_READY", "COMPLETED"];
  function timeline(status) {
    let current = statusSteps.indexOf(status);
    if (["PAYMENT_VERIFIED"].includes(status)) current = 0;
    if (status === "FINAL_PAYMENT_UNDER_VERIFICATION") current = 2;
    return `<div class="status-timeline">${statusSteps.map((s, i) => `<div class="status-step ${i < current ? "done" : i === current ? "active" : ""}"><i>${i < current ? "✓" : i + 1}</i></div>`).join("")}</div>`;
  }

  function ratingMarkup(a) {
    if (a.status !== "COMPLETED") return "";
    if (a.rating) return `<div class="rating-box"><span class="rating-thanks">Thank you for your ${a.rating}-star rating ✅</span></div>`;
    return `<div class="rating-box"><b>How was your experience?</b><div class="stars" data-rating-app="${a.id}">${[1,2,3,4,5].map((n) => `<button type="button" class="star-btn" data-stars="${n}" aria-label="${n} star">★</button>`).join("")}</div></div>`;
  }

  async function loadApplications() {
    const list = $("applicationsList"); list.innerHTML = '<div class="loading">Loading applications…</div>';
    try {
      const data = await api("/website/api/my-applications");
      if (!data.applications.length) { list.innerHTML = '<div class="empty">No applications found in this browser.</div>'; return; }
      list.innerHTML = `<div class="applications-grid">${data.applications.map((a) => `
        <article class="application-card">
          <div class="application-card-head"><div class="application-brand"><img src="${logo(a.wallet)}" alt="${esc(a.wallet)} logo"><div><button type="button" class="copyable code" data-copy-value="${esc(a.application_id)}" data-copy-message="Application ID copied ✅">${esc(a.application_id)}</button><p>${esc(a.wallet)}</p></div></div><span class="badge ${a.status === "COMPLETED" ? "completed" : ""}">${esc(a.status_label)}</span></div>
          ${timeline(a.status)}
          <div class="payment-summary"><div><b>Initial Paid</b><span>${money(a.paid_initial)}</span></div><div><b>Remaining</b><span>${money(a.remaining_amount)}</span></div><div><b>Submitted</b><span>${new Date(a.created_at).toLocaleDateString("en-IN")}</span></div></div>
          ${a.status === "WALLET_READY" && !a.final_payment_submitted ? `<button type="button" class="primary final-btn" data-id="${a.id}">Submit Final Payment</button>` : ""}
          ${ratingMarkup(a)}
        </article>`).join("")}</div>`;
      document.querySelectorAll(".final-btn").forEach((b) => b.addEventListener("click", () => openFinal(Number(b.dataset.id))));
      document.querySelectorAll(".stars").forEach((box) => {
        box.querySelectorAll(".star-btn").forEach((button) => {
          button.addEventListener("mouseenter", () => box.querySelectorAll(".star-btn").forEach((s) => s.classList.toggle("selected", Number(s.dataset.stars) <= Number(button.dataset.stars))));
          button.addEventListener("click", () => submitRating(Number(box.dataset.ratingApp), Number(button.dataset.stars)));
        });
      });
    } catch (error) { list.innerHTML = `<div class="empty">${esc(error.message)}</div>`; }
  }

  async function submitRating(applicationId, stars) {
    try { await api("/website/api/rating", { application_id: applicationId, stars }); toast("Thank you for your feedback ✅"); loadApplications(); }
    catch (error) { toast(error.message); }
  }

  async function trackApplication() {
    const result = $("trackResult"); result.classList.remove("hidden"); result.textContent = "Checking…";
    try {
      const data = await api("/website/api/track", { application_id: $("applicationId").value.trim(), mobile_number: $("trackMobile").value.trim() });
      const a = data.application;
      result.innerHTML = `<button type="button" class="copyable code" data-copy-value="${esc(a.application_id)}" data-copy-message="Application ID copied ✅">${esc(a.application_id)}</button><h3>${esc(a.wallet)}</h3><span class="badge ${a.status === "COMPLETED" ? "completed" : ""}">${esc(a.status_label)}</span>${timeline(a.status)}<p>Remaining Amount: <b>${money(a.remaining_amount)}</b></p>`;
    } catch (error) { result.textContent = error.message; }
  }

  async function openFinal(id) {
    state.activeFinalId = id;
    try {
      const info = await api("/website/api/final-payment-info", { application_id: id });
      $("finalPaymentContent").innerHTML = `<div class="apply-summary"><p class="eyebrow">Final payment</p><button type="button" class="copyable code" data-copy-value="${esc(info.application_id)}">${esc(info.application_id)}</button><p>Remaining Amount ${money(info.remaining_amount)}</p></div><form id="finalForm"><div class="form-card"><h3>Complete Remaining Payment</h3>${info.has_qr ? '<div class="qr"><img src="/website/final-payment-qr" alt="Final Payment QR"></div>' : ""}<div class="payment-meta"><button type="button" class="copyable" data-copy-value="${esc(info.upi_id || "")}"><b>UPI ID</b><br>${esc(info.upi_id || "Contact Support")}<small>Tap to copy</small></button><div><b>Banking Name</b><br>${esc(info.banking_name || "Verify in UPI App")}</div></div><div class="field" style="margin-top:14px"><label>UTR Number *<input id="finalUtr"></label><label>Payment Receipt *<input id="finalReceipt" type="file" accept="image/jpeg,image/png,image/webp,application/pdf" data-file-label="finalFileName"></label><span id="finalFileName" class="file-name"></span></div></div><div id="finalError" class="error hidden"></div><button id="submitFinal" class="primary" type="submit">Submit Final Payment</button></form>`;
      $("finalReceipt").addEventListener("change", () => $("finalFileName").textContent = $("finalReceipt").files?.[0] ? `Selected: ${$("finalReceipt").files[0].name}` : "");
      $("finalForm").addEventListener("submit", submitFinal); showView("finalPayment");
    } catch (error) { toast(error.message); }
  }

  async function submitFinal(event) {
    event.preventDefault();
    const button = $("submitFinal"), errorBox = $("finalError"), file = $("finalReceipt").files?.[0];
    errorBox.classList.add("hidden"); if (!file) { errorBox.textContent = "Please select the final payment receipt."; errorBox.classList.remove("hidden"); return; }
    const form = new FormData(); form.append("application_id", state.activeFinalId); form.append("utr", $("finalUtr").value.trim()); form.append("receipt", file, file.name);
    button.disabled = true; button.textContent = "Submitting…";
    try { const data = await api("/website/api/final-payment", form, true); toast(data.status_label); showView("applications"); }
    catch (error) { errorBox.textContent = error.message; errorBox.classList.remove("hidden"); }
    finally { button.disabled = false; button.textContent = "Submit Final Payment"; }
  }

  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  $("refreshWallets")?.addEventListener("click", loadBootstrap);
  $("refreshApplications")?.addEventListener("click", loadApplications);
  $("trackButton")?.addEventListener("click", trackApplication);
  $("applicationId")?.addEventListener("keydown", (e) => { if (e.key === "Enter") trackApplication(); });
  document.addEventListener("click", (event) => { const target = event.target.closest("[data-copy-value]"); if (target) copyText(t
