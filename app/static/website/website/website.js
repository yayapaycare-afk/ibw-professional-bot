(() => {
  "use strict";

  const state = {
    bootstrap: null,
    selectedWallet: null,
    applications: [],
    finalApplicationId: null,
  };

  const $ = (id) => document.getElementById(id);

  const money = (value) =>
    `₹${Number(value || 0).toLocaleString("en-IN")}`;

  const escapeHtml = (value) => {
    const div = document.createElement("div");
    div.textContent = String(value ?? "");
    return div.innerHTML;
  };

  const walletLogo = (name) => {
    const key = String(name || "")
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "");

    const logos = {
      paytmbusiness: "paytm-business.png",
      phonepaybusiness: "phonepe-business.png",
      phonepebusiness: "phonepe-business.png",
      googlepaybusiness: "googlepay-business.png",
      gpaybusiness: "googlepay-business.png",
      bharatpaybusiness: "bharatpe-business.png",
      bharatpebusiness: "bharatpe-business.png",
      mobikwikbusiness: "mobikwik-business.png",
      bajajpaybusiness: "bajajpay-business.png",
      pinelabsbusiness: "pinelabs-business.png",
    };

    const filename = logos[key];

    return filename
      ? `/static/miniapp/logos/${filename}`
      : "/static/miniapp/logos/ibw-logo.png";
  };

  function showToast(message) {
    const toast = $("websiteToast");
    if (!toast) return;

    toast.textContent = message;
    toast.classList.add("show");

    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
      toast.classList.remove("show");
    }, 1800);
  }

  async function copyText(value, message = "Copied ✅") {
    const text = String(value || "").trim();
    if (!text) return;

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
      }

      showToast(message);
    } catch (error) {
      showToast("Copy failed — long press to copy");
    }
  }

  function showView(name) {
    document.querySelectorAll(".website-view").forEach((section) => {
      section.classList.toggle("hidden", section.id !== `${name}View`);
    });

    document.querySelectorAll("[data-view]").forEach((button) => {
      button.classList.toggle(
        "active",
        button.dataset.view === name
      );
    });

    window.scrollTo({
      top: 0,
      behavior: "smooth",
    });

    if (name === "applications") {
      loadApplications();
    }
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      cache: "no-store",
      credentials: "same-origin",
      ...options,
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(
        data.detail ||
        data.message ||
        "Request failed"
      );
    }

    return data;
  }

  async function loadBootstrap() {
    const walletList = $("walletList");

    try {
      const data = await api("/website/api/bootstrap");
      state.bootstrap = data;

      if ($("serviceBadge")) {
        $("serviceBadge").textContent =
          data.service_available
            ? "● ONLINE"
            : "● CLOSED";

        $("serviceBadge").classList.toggle(
          "online",
          Boolean(data.service_available)
        );

        $("serviceBadge").classList.toggle(
          "offline",
          !data.service_available
        );
      }

      if ($("workingHours")) {
        $("workingHours").textContent =
          data.working_hours || "—";
      }

      renderWallets();
    } catch (error) {
      if (walletList) {
        walletList.innerHTML = `
          <div class="empty">
            ${escapeHtml(error.message)}
          </div>
        `;
      }
    }
  }

  function renderWallets() {
    const walletList = $("walletList");
    const wallets = state.bootstrap?.wallets || [];

    if (!walletList) return;

    if (!wallets.length) {
      walletList.innerHTML = `
        <div class="empty">
          No wallet service is currently available.
        </div>
      `;
      return;
    }

    walletList.innerHTML = wallets.map((wallet) => `
      <article class="wallet-card">
        <div class="wallet-card-head">
          <div class="wallet-brand">
            <img
              src="${walletLogo(wallet.name)}"
              alt="${escapeHtml(wallet.name)} logo"
              class="wallet-logo"
            >
            <div>
              <h3>${escapeHtml(wallet.name)}</h3>
              <small>
                Estimated Wallet Processing Time
              </small>
              <strong>
                ${escapeHtml(
                  wallet.processing_time ||
                  "Subject to verification"
                )}
              </strong>
            </div>
          </div>

          <div class="wallet-price">
            ${money(wallet.total_fee)}
          </div>
        </div>

        ${
          wallet.description
            ? `<p>${escapeHtml(wallet.description)}</p>`
            : ""
        }

        <div class="fee-grid">
          <div>
            <b>First Payment</b>
            <span>${money(wallet.initial_amount)}</span>
            <small>Pay at application start</small>
          </div>

          <div>
            <b>Remaining</b>
            <span>${money(wallet.remaining_amount)}</span>
            <small>After wallet ready</small>
          </div>
        </div>

        <div class="document-chips">
          ${(wallet.documents || []).map((document) => `
            <span>${escapeHtml(document.name)}</span>
          `).join("")}
        </div>

        <button
          type="button"
          class="primary-btn apply-wallet-btn"
          data-wallet-id="${wallet.id}"
        >
          Apply for ${escapeHtml(wallet.name)}
        </button>
      </article>
    `).join("");

    document
      .querySelectorAll(".apply-wallet-btn")
      .forEach((button) => {
        button.addEventListener("click", () => {
          openApplication(Number(button.dataset.walletId));
        });
      });
  }

  function documentField(documentRule) {
    const id = `document_${documentRule.id}`;
    const kind = String(
      documentRule.manual_kind || ""
    ).toLowerCase();

    const name = String(
      documentRule.name || ""
    ).toLowerCase();

    const isBank =
      kind === "bank" ||
      name.includes("bank") ||
      name.includes("ifsc") ||
      name.includes("account");

    if (isBank) {
      return `
        <div class="document-card">
          <h3>
            ${escapeHtml(documentRule.name)}
            ${documentRule.required ? " *" : ""}
          </h3>

          <label>Account Number</label>
          <input
            id="${id}_account"
            inputmode="numeric"
            placeholder="Enter Account Number"
          >

          <label>IFSC Code</label>
          <input
            id="${id}_ifsc"
            autocapitalize="characters"
            placeholder="Enter IFSC Code"
          >
        </div>
      `;
    }

    const uploadInput = documentRule.upload_allowed
      ? `
        <label>
          Upload ${escapeHtml(documentRule.name)}
        </label>

        <input
          id="${id}_file"
          type="file"
          accept="image/jpeg,image/png,image/webp,application/pdf"
        >

        <small>
          JPG, PNG, WEBP or PDF • Maximum 10 MB
        </small>
      `
      : "";

    const manualInput = documentRule.manual_allowed
      ? `
        <label>
          ${
            escapeHtml(
              documentRule.manual_label ||
              documentRule.name
            )
          }
        </label>

        <input
          id="${id}_manual"
          type="text"
          placeholder="${
            escapeHtml(
              documentRule.manual_label ||
              documentRule.name
            )
          }"
        >
      `
      : "";

    return `
      <div class="document-card">
        <h3>
          ${escapeHtml(documentRule.name)}
          ${documentRule.required ? " *" : ""}
        </h3>

        ${manualInput}
        ${uploadInput}
      </div>
    `;
  }

  function openApplication(walletId) {
    const wallet = state.bootstrap?.wallets?.find(
      (item) => Number(item.id) === Number(walletId)
    );

    if (!wallet) {
      showToast("Wallet unavailable");
      return;
    }

    state.selectedWallet = wallet;

    const content = $("applicationContent");
    if (!content) return;

    content.innerHTML = `
      <div class="application-summary">
        <img
          src="${walletLogo(wallet.name)}"
          alt="${escapeHtml(wallet.name)} logo"
        >

        <div>
          <span>New Website Application</span>
          <h2>${escapeHtml(wallet.name)}</h2>
          <p>
            Total Fee ${money(wallet.total_fee)}
            • First Payment ${money(wallet.initial_amount)}
          </p>
        </div>
      </div>

      <form id="websiteApplicationForm">
        <div class="document-card">
          <h3>Customer Information</h3>

          <label for="customerName">
            Full Name *
          </label>

          <input
            id="customerName"
            name="full_name"
            type="text"
            autocomplete="name"
            placeholder="Enter your full name"
            required
          >

          <label for="customerMobile">
            Mobile Number *
          </label>

          <input
            id="customerMobile"
            name="mobile_number"
            type="tel"
            inputmode="numeric"
            maxlength="10"
            placeholder="Enter 10-digit mobile number"
            required
          >
        </div>

        ${(wallet.documents || []).map(documentField).join("")}

        <div class="document-card">
          <h3>First Payment</h3>

          ${
            wallet.has_qr
              ? `
                <div class="payment-qr">
                  <img
                    src="/website/wallet/${wallet.id}/qr"
                    alt="Payment QR"
                  >
                </div>
              `
              : `
                <div class="empty">
                  Payment QR is not configured.
                </div>
              `
          }

          <div class="payment-details">
            <div>
              <b>Amount</b>
              <span>${money(wallet.initial_amount)}</span>
            </div>

            <button
              type="button"
              class="copy-payment-value"
              data-copy-value="${
                escapeHtml(wallet.upi_id || "")
              }"
            >
              <b>UPI ID</b>
              <span>
                ${
                  escapeHtml(
                    wallet.upi_id ||
                    "Contact Support"
                  )
                }
              </span>
              <small>Tap to copy</small>
            </button>

            <div>
              <b>Banking Name</b>
              <span>
                ${
                  escapeHtml(
                    wallet.banking_name ||
                    "Verify in UPI App"
                  )
                }
              </span>
            </div>

            <div>
              <b>Remaining</b>
              <span>${money(wallet.remaining_amount)}</span>
            </div>
          </div>

          <label for="paymentUtr">
            UTR Number *
          </label>

          <input
            id="paymentUtr"
            type="text"
            autocomplete="off"
            placeholder="Enter payment UTR"
            required
          >

          <label for="paymentReceipt">
            Payment Receipt *
          </label>

          <input
            id="paymentReceipt"
            type="file"
            accept="image/jpeg,image/png,image/webp,application/pdf"
            required
          >
        </div>

        <div
          id="applicationError"
          class="error-box hidden"
        ></div>

        <button
          id="submitWebsiteApplication"
          type="submit"
          class="primary-btn"
        >
          Submit Application Securely
        </button>
      </form>
    `;

    $("websiteApplicationForm")
      ?.addEventListener(
        "submit",
        submitApplication
      );

    showView("application");
  }

  function manualDocumentValue(documentRule) {
    const id = `document_${documentRule.id}`;
    const kind = String(
      documentRule.manual_kind || ""
    ).toLowerCase();

    const name = String(
      documentRule.name || ""
    ).toLowerCase();

    const isBank =
      kind === "bank" ||
      name.includes("bank") ||
      name.includes("ifsc") ||
      name.includes("account");

    if (isBank) {
      const account = $(`${id}_account`)
        ?.value.trim() || "";

      const ifsc = $(`${id}_ifsc`)
        ?.value.trim()
        .toUpperCase() || "";

      if (!account && !ifsc) return "";

      return JSON.stringify({
        account_number: account,
        ifsc,
      });
    }

    return $(`${id}_manual`)
      ?.value.trim() || "";
  }

  async function submitApplication(event) {
    event.preventDefault();

    const wallet = state.selectedWallet;
    if (!wallet) return;

    const button = $("submitWebsiteApplication");
    const errorBox = $("applicationError");

    errorBox?.classList.add("hidden");

    const formData = new FormData();

    formData.append(
      "wallet_id",
      String(wallet.id)
    );

    formData.append(
      "full_name",
      $("customerName")?.value.trim() || ""
    );

    formData.append(
      "mobile_number",
      $("customerMobile")?.value.trim() || ""
    );

    formData.append(
      "utr",
      $("paymentUtr")?.value.trim() || ""
    );

    const manualValues = {};

    (wallet.documents || []).forEach((documentRule) => {
      const manualValue =
        manualDocumentValue(documentRule);

      if (manualValue) {
        manualValues[String(documentRule.id)] =
          manualValue;
      }

      const file =
        $(`document_${documentRule.id}_file`)
          ?.files?.[0];

      if (file) {
        formData.append(
          `doc_${documentRule.id}`,
          file
        );
      }
    });

    formData.append(
      "manual_values",
      JSON.stringify(manualValues)
    );

    const receipt =
      $("paymentReceipt")?.files?.[0];

    if (receipt) {
      formData.append("receipt", receipt);
    }

    if (button) {
      button.disabled = true;
      button.textContent =
        "Submitting securely…";
    }

    try {
      const data = await api(
        "/website/api/applications",
        {
          method: "POST",
          body: formData,
        }
      );

      const application =
        data.application || data;

      if ($("successApplicationId")) {
        $("successApplicationId").textContent =
          application.application_id;

        $("successApplicationId").dataset.copyValue =
          application.application_id;
      }

      if ($("successWalletName")) {
        $("successWalletName").textContent =
          application.wallet ||
          wallet.name;
      }

      showView("success");
    } catch (error) {
      if (errorBox) {
        errorBox.textContent = error.message;
        errorBox.classList.remove("hidden");
      }
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent =
          "Submit Application Securely";
      }
    }
  }

  async function loadApplications() {
    const list = $("applicationsList");
    if (!list) return;

    list.innerHTML = `
      <div class="loading-card">
        Loading applications…
      </div>
    `;

    try {
      const data = await api(
        "/website/api/my-applications"
      );

      state.applications =
        data.applications || [];

      if (!state.applications.length) {
        list.innerHTML = `
          <div class="empty">
            No applications found in this browser.
          </div>
        `;
        return;
      }

      list.innerHTML = state.applications.map((item) => `
        <article class="application-card">
          <div class="application-card-head">
            <div>
              <button
                type="button"
                class="application-id-copy"
                data-copy-value="${
                  escapeHtml(item.application_id)
                }"
              >
                ${escapeHtml(item.application_id)}
                <small>Tap to copy</small>
              </button>

              <p>${escapeHtml(item.wallet)}</p>
            </div>

            <span class="status-pill">
              ${escapeHtml(item.status_label)}
            </span>
          </div>

          <p>
            Initial Paid:
            ${money(item.paid_initial)}
            • Remaining:
            ${money(item.remaining_amount)}
          </p>

          ${
            item.status === "WALLET_READY" &&
            !item.final_payment_submitted
              ? `
                <button
                  type="button"
                  class="primary-btn final-payment-btn"
                  data-application-id="${item.id}"
                >
                  Submit Final Payment
                </button>
              `
              : ""
          }
        </article>
      `).join("");

      document
        .querySelectorAll(".final-payment-btn")
        .forEach((button) => {
          button.addEventListener("click", () => {
            openFinalPayment(
              Number(button.dataset.applicationId)
            );
          });
        });
    } catch (error) {
      list.innerHTML = `
        <div class="empty">
          ${escapeHtml(error.message)}
        </div>
      `;
    }
  }

  async function trackApplication() {
    const input = $("trackApplicationId");
    const mobileInput = $("trackMobileNumber");
    const result = $("trackResult");

    if (!result) return;

    const applicationId =
      input?.value.trim().toUpperCase() || "";

    const mobileNumber =
      mobileInput?.value.trim() || "";

    if (!applicationId) {
      result.textContent =
        "Application ID enter karein.";
      result.classList.remove("hidden");
      return;
    }

    result.textContent = "Checking…";
    result.classList.remove("hidden");

    try {
      const data = await api(
        "/website/api/track",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            application_id: applicationId,
            mobile_number: mobileNumber,
          }),
        }
      );

      const item =
        data.application || data;

      result.innerHTML = `
        <button
          type="button"
          class="application-id-copy"
          data-copy-value="${
            escapeHtml(item.application_id)
          }"
        >
          ${escapeHtml(item.application_id)}
          <small>Tap to copy</small>
        </button>

        <p>${escapeHtml(item.wallet)}</p>

        <span class="status-pill">
          ${escapeHtml(item.status_label)}
        </span>

        <p>
          Remaining:
          ${money(item.remaining_amount)}
        </p>
      `;
    } catch (error) {
      result.textContent = error.message;
    }
  }

  async function openFinalPayment(applicationId) {
    state.finalApplicationId = applicationId;

    try {
      const info = await api(
        "/website/api/final-payment-info",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            application_id: applicationId,
          }),
        }
      );

     
