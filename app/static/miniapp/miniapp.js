(() => {
  const tg = window.Telegram?.WebApp;
  if (tg) { tg.ready(); tg.expand(); tg.setHeaderColor?.("#102c54"); tg.setBackgroundColor?.("#f3f6fb"); }
  const initData = tg?.initData || "";
  const initUser = tg?.initDataUnsafe?.user;
  let bootstrap = null;
  let selectedWallet = null;
  let activeFinalApplicationId = null;

  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => { const div = document.createElement("div"); div.textContent = String(value ?? ""); return div.innerHTML; };
  const money = (value) => `₹${Number(value || 0).toLocaleString("en-IN")}`;
  const notice = $("telegramNotice");
  const views = [...document.querySelectorAll(".view-section")];

  function showNotice(message) { notice.textContent = message; notice.classList.remove("hidden"); }
  function showView(name) {
    views.forEach((view) => view.classList.toggle("hidden", view.id !== `${name}View`));
    document.querySelectorAll(".bottom-nav [data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
    document.querySelectorAll(".quick-grid [data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (name === "applications") loadApplications();
  }
  async function jsonApi(path, body) {
    const response = await fetch(path, { method: body ? "POST" : "GET", headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined, cache: "no-store" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Request failed");
    return data;
  }
  async function formApi(path, formData) {
    const response = await fetch(path, { method: "POST", body: formData, cache: "no-store" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Request failed");
    return data;
  }

  async function loadBootstrap() {
    try {
      bootstrap = await jsonApi("/miniapp/api/bootstrap");
      $("workingHours").textContent = bootstrap.working_hours;
      const badge = $("serviceBadge");
      badge.textContent = bootstrap.service_available ? "● ONLINE" : "● CLOSED";
      badge.classList.add(bootstrap.service_available ? "online" : "offline");
      renderWallets();
    } catch (error) {
      $("walletList").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    }
  }

  function renderWallets() {
    if (!bootstrap?.wallets?.length) { $("walletList").innerHTML = '<div class="empty">No service is currently available.</div>'; return; }
    $("walletList").innerHTML = bootstrap.wallets.map((wallet) => `
      <article class="wallet-card">
        <div class="wallet-top"><div><h3>${escapeHtml(wallet.name)}</h3><p>${escapeHtml(wallet.processing_time || "Subject to verification")}</p></div><div class="price">${money(wallet.total_fee)}</div></div>
        ${wallet.description ? `<p>${escapeHtml(wallet.description)}</p>` : ""}
        <div class="fee-grid"><div class="fee-box"><b>First Payment</b><span>${money(wallet.initial_amount)}</span><small>${wallet.initial_percent}%</small></div><div class="fee-box"><b>Remaining</b><span>${money(wallet.remaining_amount)}</span><small>After wallet ready</small></div></div>
        <div class="doc-chips">${wallet.documents.map((doc) => `<span class="doc-chip">${escapeHtml(doc.name)}</span>`).join("")}</div>
        <button type="button" class="primary-btn apply-wallet" data-wallet-id="${wallet.id}">Apply for ${escapeHtml(wallet.name)}</button>
      </article>`).join("");
    document.querySelectorAll(".apply-wallet").forEach((button) => button.addEventListener("click", () => openApplication(Number(button.dataset.walletId))));
  }

  function effectiveManualKind(doc) {
    const configured = String(doc.manual_kind || "").toLowerCase();
    const searchable = `${doc.name || ""} ${doc.manual_label || ""}`.toLowerCase();
    if (configured === "bank" || searchable.includes("bank") || searchable.includes("ifsc") || searchable.includes("account number")) return "bank";
    if (configured === "mobile" || searchable.includes("mobile") || searchable.includes("phone")) return "mobile";
    if (configured === "aadhaar" || configured === "aadhar" || searchable.includes("aadhaar") || searchable.includes("aadhar")) return "aadhaar";
    if (configured === "pan" || searchable.includes("pan card") || searchable.includes("pan number")) return "pan";
    return configured || "single";
  }

  function inputForDocument(doc) {
    const id = `manual_${doc.id}`;
    const kind = effectiveManualKind(doc);
    if (kind === "bank") return `<div class="field"><label>Account Number</label><input id="${id}_account" inputmode="numeric" placeholder="Enter Account Number"><label style="margin-top:10px">IFSC Code</label><input id="${id}_ifsc" autocapitalize="characters" placeholder="Enter IFSC Code"></div>`;
    let type = "text", mode = "text", max = "";
    if (kind === "mobile") { type = "tel"; mode = "numeric"; max = 'maxlength="15"'; }
    if (kind === "aadhaar") { mode = "numeric"; max = 'maxlength="12"'; }
    if (kind === "pan") max = 'maxlength="10" style="text-transform:uppercase"';
    return `<div class="field"><label for="${id}">${escapeHtml(doc.manual_label || doc.name)}</label><input id="${id}" type="${type}" inputmode="${mode}" ${max} placeholder="${escapeHtml(doc.manual_label || doc.name)}"></div>`;
  }

  function documentBlock(doc) {
    const manual = doc.manual_allowed ? `<div class="manual-area" id="manualArea_${doc.id}">${inputForDocument(doc)}</div>` : "";
    const upload = doc.upload_allowed ? `<div class="upload-area ${doc.manual_allowed ? "hidden" : ""}" id="uploadArea_${doc.id}"><div class="field"><label for="file_${doc.id}">Upload ${escapeHtml(doc.name)}</label><input id="file_${doc.id}" type="file" accept="image/jpeg,image/png,image/webp,application/pdf"><small>JPG, PNG, WEBP or PDF • Max 10 MB</small></div></div>` : "";
    const switcher = doc.manual_allowed && doc.upload_allowed ? `<div class="method-switch"><button type="button" class="active" data-doc="${doc.id}" data-method="manual">Enter Manually</button><button type="button" data-doc="${doc.id}" data-method="upload">Upload File</button></div>` : "";
    return `<div class="form-card" data-doc-card="${doc.id}"><h3>${escapeHtml(doc.name)}${doc.required ? " *" : ""}</h3>${switcher}${manual}${upload}</div>`;
  }

  function openApplication(walletId) {
    if (!initData) { showNotice("Application submit करने के लिए portal को Telegram Bot के अंदर खोलें।"); return; }
    selectedWallet = bootstrap.wallets.find((item) => item.id === walletId);
    if (!selectedWallet) return;
    $("applyContent").innerHTML = `
      <div class="apply-summary"><p class="eyebrow">New Application</p><h2>${escapeHtml(selectedWallet.name)}</h2><p>Total Fee ${money(selectedWallet.total_fee)} • First Payment ${money(selectedWallet.initial_amount)}</p></div>
      <div class="stepper"><span class="active"></span><span class="active"></span><span class="active"></span><span></span></div>
      <form id="applicationForm">
        ${selectedWallet.documents.map(documentBlock).join("")}
        <div class="form-card"><h3>Initial Payment</h3>
          ${selectedWallet.has_qr ? `<div class="qr-card"><img src="/miniapp/wallet/${selectedWallet.id}/qr" alt="Payment QR"></div>` : '<div class="empty">Payment QR is not configured. Please use the UPI details below.</div>'}
          <div class="payment-meta"><div><b>Amount</b><br>${money(selectedWallet.initial_amount)}</div><div><b>UPI ID</b><br>${escapeHtml(selectedWallet.upi_id || "Contact Support")}</div><div><b>Banking Name</b><br>${escapeHtml(selectedWallet.banking_name || "Verify in UPI App")}</div><div><b>Remaining</b><br>${money(selectedWallet.remaining_amount)}</div></div>
          <div class="field" style="margin-top:14px"><label for="initialUtr">UTR Number *</label><input id="initialUtr" autocomplete="off" placeholder="Enter payment UTR"></div>
          <div class="field"><label for="initialReceipt">Payment Receipt *</label><input id="initialReceipt" type="file" accept="image/jpeg,image/png,image/webp,application/pdf"><small>JPG, PNG, WEBP or PDF • Max 10 MB</small></div>
        </div>
        <div id="applyError" class="error-box hidden"></div>
        <button id="submitApplication" type="submit" class="primary-btn">Submit Application Securely</button>
      </form>`;
    document.querySelectorAll(".method-switch button").forEach((button) => button.addEventListener("click", () => switchMethod(button)));
    $("applicationForm").addEventListener("submit", submitApplication);
    showView("apply");
  }

  function switchMethod(button) {
    const docId = button.dataset.doc, method = button.dataset.method;
    button.parentElement.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === button));
    $(`manualArea_${docId}`)?.classList.toggle("hidden", method !== "manual");
    $(`uploadArea_${docId}`)?.classList.toggle("hidden", method !== "upload");
  }

  function manualValue(doc) {
    const manualArea = $(`manualArea_${doc.id}`);
    if (!manualArea || manualArea.classList.contains("hidden")) return "";
    const kind = effectiveManualKind(doc);
    if (kind === "bank") {
      const account = $(`manual_${doc.id}_account`).value.trim();
      const ifsc = $(`manual_${doc.id}_ifsc`).value.trim().toUpperCase();
      return account || ifsc ? JSON.stringify({ account_number: account, ifsc }) : "";
    }
    let value = $(`manual_${doc.id}`)?.value.trim() || "";
    if (kind === "pan") value = value.toUpperCase();
    return value;
  }

  async function submitApplication(event) {
    event.preventDefault();
    const button = $("submitApplication"), errorBox = $("applyError");
    errorBox.classList.add("hidden");
    const form = new FormData();
    form.append("init_data", initData); form.append("wallet_id", selectedWallet.id); form.append("utr", $("initialUtr").value.trim());
    const manual = {};
    selectedWallet.documents.forEach((doc) => {
      const value = manualValue(doc); if (value) manual[String(doc.id)] = value;
      const file = $(`file_${doc.id}`)?.files?.[0]; if (file && !$(`uploadArea_${doc.id}`)?.classList.contains("hidden")) form.append(`doc_${doc.id}`, file);
    });
    form.append("manual_values", JSON.stringify(manual));
    const receipt = $("initialReceipt").files[0]; if (receipt) form.append("receipt", receipt);
    button.disabled = true; button.textContent = "Submitting securely…";
    try {
      const data = await formApi("/miniapp/api/applications", form);
      $("successCode").textContent = data.application.application_id;
      $("successWallet").textContent = `${data.application.wallet} • ${data.application.status_label}`;
      tg?.HapticFeedback?.notificationOccurred("success"); showView("success");
    } catch (error) {
      errorBox.textContent = error.message; errorBox.classList.remove("hidden"); tg?.HapticFeedback?.notificationOccurred("error");
    } finally { button.disabled = false; button.textContent = "Submit Application Securely"; }
  }

  async function loadApplications() {
    const list = $("applicationsList");
    if (!initData) { list.innerHTML = '<div class="empty">Open this portal from Telegram Bot to view your applications.</div>'; return; }
    list.innerHTML = '<div class="skeleton">Loading applications…</div>';
    try {
      const data = await jsonApi("/miniapp/api/my-applications", { init_data: initData });
      if (!data.applications.length) { list.innerHTML = '<div class="empty">No submitted applications found.</div>'; return; }
      list.innerHTML = data.applications.map((item) => `
        <article class="application-card"><div class="application-top"><div><h3>${escapeHtml(item.application_id)}</h3><p>${escapeHtml(item.wallet)}</p></div><span class="badge">${escapeHtml(item.status_label)}</span></div>
        <p>Initial Paid: ${money(item.paid_initial)} • Remaining: ${money(item.remaining_amount)}</p>
        ${item.status === "WALLET_READY" && !item.final_payment_submitted ? `<div class="application-actions"><button type="button" class="primary-btn final-payment-btn" data-id="${item.id}">Submit Final Payment</button></div>` : ""}</article>`).join("");
      document.querySelectorAll(".final-payment-btn").forEach((button) => button.addEventListener("click", () => openFinalPayment(Number(button.dataset.id))));
    } catch (error) { list.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`; }
  }

  async function trackApplication() {
    const result = $("trackResult"), code = $("applicationId").value.trim(); result.classList.remove("hidden");
    if (!initData) { result.textContent = "Open this portal from Telegram Bot for secure tracking."; return; }
    if (!code) { result.textContent = "Please enter Application ID."; return; }
    result.textContent = "Checking…";
    try { const data = await jsonApi("/miniapp/api/track", { init_data: initData, application_id: code }); const item = data.application; result.innerHTML = `<b>${escapeHtml(item.application_id)}</b><br>${escapeHtml(item.wallet)}<br><span class="badge" style="margin-top:8px">${escapeHtml(item.status_label)}</span>`; }
    catch (error) { result.textContent = error.message; }
  }

  async function openFinalPayment(applicationId) {
    activeFinalApplicationId = applicationId;
    try {
      const info = await jsonApi("/miniapp/api/final-payment-info", { init_data: initData, application_id: applicationId });
      $("finalPaymentContent").innerHTML = `<div class="apply-summary"><p class="eyebrow">Final Payment</p><h2>${escapeHtml(info.application_id)}</h2><p>Remaining Amount ${money(info.remaining_amount)}</p></div><form id="finalPaymentForm"><div class="form-card"><h3>Complete Remaining Payment</h3>${info.has_qr ? '<div class="qr-card"><img src="/miniapp/final-payment-qr" alt="Final Payment QR"></div>' : ""}<div class="payment-meta"><div><b>UPI ID</b><br>${escapeHtml(info.upi_id || "Contact Support")}</div><div><b>Banking Name</b><br>${escapeHtml(info.banking_name || "Verify in UPI App")}</div></div><div class="field" style="margin-top:14px"><label for="finalUtr">UTR Number *</label><input id="finalUtr" placeholder="Enter final payment UTR"></div><div class="field"><label for="finalReceipt">Payment Receipt *</label><input id="finalReceipt" type="file" accept="image/jpeg,image/png,image/webp,application/pdf"></div></div><div id="finalError" class="error-box hidden"></div><button id="submitFinalPayment" class="primary-btn" type="submit">Submit Final Payment</button></form>`;
      $("finalPaymentForm").addEventListener("submit", submitFinalPayment); showView("finalPayment");
    } catch (error) { showNotice(error.message); }
  }

  async function submitFinalPayment(event) {
    event.preventDefault(); const button = $("submitFinalPayment"), errorBox = $("finalError"), form = new FormData();
    form.append("init_data", initData); form.append("application_id", activeFinalApplicationId); form.append("utr", $("finalUtr").value.trim()); const receipt = $("finalReceipt").files[0]; if (receipt) form.append("receipt", receipt);
    button.disabled = true; button.textContent = "Submitting…"; errorBox.classList.add("hidden");
    try { const data = await formApi("/miniapp/api/final-payment", form); tg?.HapticFeedback?.notificationOccurred("success"); showNotice(`Final payment submitted: ${data.status_label}`); showView("applications"); }
    catch (error) { errorBox.textContent = error.message; errorBox.classList.remove("hidden"); }
    finally { button.disabled = false; button.textContent = "Submit Final Payment"; }
  }

  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  $("refreshWallets")?.addEventListener("click", loadBootstrap);
  $("refreshApplications")?.addEventListener("click", loadApplications);
  $("trackButton")?.addEventListener("click", trackApplication);
  $("applicationId")?.addEventListener("keydown", (event) => { if (event.key === "Enter") trackApplication(); });
  if (initUser) $("welcomeName").textContent = [initUser.first_name, initUser.last_name].filter(Boolean).join(" ") || "User";
  else showNotice("Preview mode: services are visible, but application submission and tracking require Telegram verified access.");
  loadBootstrap();
})();
