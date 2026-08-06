data.application.application_id;
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
        <article class="application-card"><div class="application-top"><div><button type="button" class="copyable application-id-copy" data-copy-value="${escapeHtml(item.application_id)}" data-copy-message="Application ID copied ✅">${escapeHtml(item.application_id)}<small>Tap to copy</small></button><p>${escapeHtml(item.wallet)}</p></div><span class="badge">${escapeHtml(item.status_label)}</span></div>
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
    try { const data = await jsonApi("/miniapp/api/track", { init_data: initData, application_id: code }); const item = data.application; result.innerHTML = `<button type="button" class="copyable application-id-copy" data-copy-value="${escapeHtml(item.application_id)}" data-copy-message="Application ID copied ✅">${escapeHtml(item.application_id)}<small>Tap to copy</small></button><br>${escapeHtml(item.wallet)}<br><span class="badge" style="margin-top:8px">${escapeHtml(item.status_label)}</span>`; }
    catch (error) { result.textContent = error.message; }
  }

  async function openFinalPayment(applicationId) {
    activeFinalApplicationId = applicationId;
    try {
      const info = await jsonApi("/miniapp/api/final-payment-info", { init_data: initData, application_id: applicationId });
      $("finalPaymentContent").innerHTML = `<div class="apply-summary"><p class="eyebrow">Final Payment</p><button type="button" class="copyable final-app-id" data-copy-value="${escapeHtml(info.application_id)}" data-copy-message="Application ID copied ✅">${escapeHtml(info.application_id)}<small>Tap to copy</small></button><p>Remaining Amount ${money(info.remaining_amount)}</p></div><form id="finalPaymentForm"><div class="form-card"><h3>Complete Remaining Payment</h3>${info.has_qr ? '<div class="qr-card"><img src="/miniapp/final-payment-qr" alt="Final Payment QR"></div>' : ""}<div class="payment-meta"><button type="button" class="copyable payment-copy" data-copy-value="${escapeHtml(info.upi_id || "")}" data-copy-message="UPI ID copied ✅"><b>UPI ID</b><br><span>${escapeHtml(info.upi_id || "Contact Support")}</span><small>Tap to copy</small></button><div><b>Banking Name</b><br>${escapeHtml(info.banking_name || "Verify in UPI App")}</div></div><div class="field" style="margin-top:14px"><label for="finalUtr">UTR Number *</label><input id="finalUtr" placeholder="Enter final payment UTR"></div><div class="field"><label for="finalReceipt">Payment Receipt *</label><input id="finalReceipt" type="file" accept="image/jpeg,image/png,image/webp,application/pdf"></div></div><div id="finalError" class="error-box hidden"></div><button id="submitFinalPayment" class="primary-btn" type="submit">Submit Final Payment</button></form>`;
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
  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-copy-value]");
    if (!target) return;
    copyText(target.dataset.copyValue, target.dataset.copyMessage || "Copied ✅");
  });

  if (initUser && $("welcomeName")) {
    $("welcomeName").textContent = initUser.first_name || "User";
  }

  showView("home");
  loadBootstrap();
})();
