(() => {
  const tg = window.Telegram?.WebApp;

  if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor?.("secondary_bg_color");
  }

  const initData = tg?.initData || "";
  const initUser = tg?.initDataUnsafe?.user;

  const notice = document.getElementById("telegramNotice");
  const views = [...document.querySelectorAll(".view-section")];

  function showNotice(message) {
    if (!notice) return;

    notice.textContent = message;
    notice.classList.remove("hidden");
  }

  function showView(name) {
    views.forEach((view) => {
      view.classList.toggle("hidden", view.id !== `${name}View`);
    });

    document
      .getElementById(`${name}View`)
      ?.scrollIntoView({
        behavior: "smooth",
        block: "start"
      });
  }

  async function api(path, body) {
    const response = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: body
        ? {
            "Content-Type": "application/json"
          }
        : {},
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store"
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(data.detail || "Request failed");
    }

    return data;
  }

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = String(value ?? "");
    return div.innerHTML;
  }

  async function loadWallets() {
    const list = document.getElementById("walletList");

    if (!list) return;

    list.innerHTML =
      '<div class="loading">Loading wallet services…</div>';

    try {
      const data = await api("/miniapp/api/wallets");

      if (!data.wallets.length) {
        list.innerHTML =
          '<div class="empty">No wallet service is currently available.</div>';
        return;
      }

      list.innerHTML = data.wallets
        .map(
          (wallet) => `
            <article class="wallet-card">
              <div class="wallet-top">
                <div>
                  <b>${escapeHtml(wallet.name)}</b>
                  <p>${escapeHtml(
                    wallet.processing_time ||
                      "Subject to verification"
                  )}</p>
                </div>

                <span class="price">
                  ₹${wallet.total_fee}
                </span>
              </div>

              ${
                wallet.description
                  ? `<p>${escapeHtml(wallet.description)}</p>`
                  : ""
              }

              <div class="fee-row">
                <div class="fee-box">
                  <b>First Payment</b><br>
                  ₹${wallet.initial_amount}
                  (${wallet.initial_percent}%)
                </div>

                <div class="fee-box">
                  <b>Remaining</b><br>
                  ₹${wallet.remaining_amount}
                </div>
              </div>

              <p><b>Required Documents</b></p>

              <ul class="doc-list">
                ${
                  wallet.documents
                    .map(
                      (doc) =>
                        `<li>${escapeHtml(doc)}</li>`
                    )
                    .join("") ||
                  "<li>Configured during application</li>"
                }
              </ul>
            </article>
          `
        )
        .join("");
    } catch (error) {
      list.innerHTML = `
        <div class="empty">
          ${escapeHtml(error.message)}
        </div>
      `;
    }
  }

  async function loadApplications() {
    const list = document.getElementById(
      "applicationsList"
    );

    if (!list) return;

    if (!initData) {
      list.innerHTML = `
        <div class="empty">
          My Applications देखने के लिए Mini App को
          Telegram Bot के अंदर खोलें।
        </div>
      `;
      return;
    }

    list.innerHTML =
      '<div class="loading">Loading applications…</div>';

    try {
      const data = await api(
        "/miniapp/api/applications",
        {
          init_data: initData
        }
      );

      if (!data.applications.length) {
        list.innerHTML = `
          <div class="empty">
            No submitted applications found.
          </div>
        `;
        return;
      }

      list.innerHTML = data.applications
        .map(
          (item) => `
            <article class="application-card">
              <div class="application-top">
                <b>
                  ${escapeHtml(item.application_id)}
                </b>

                <span class="badge">
                  ${escapeHtml(item.status_label)}
                </span>
              </div>

              <p>
                ${escapeHtml(item.wallet)}
              </p>
            </article>
          `
        )
        .join("");
    } catch (error) {
      list.innerHTML = `
        <div class="empty">
          ${escapeHtml(error.message)}
        </div>
      `;
    }
  }

  async function trackApplication() {
    const result =
      document.getElementById("trackResult");

    const input =
      document.getElementById("applicationId");

    if (!result || !input) return;

    const code = input.value.trim();

    result.classList.remove("hidden");

    if (!initData) {
      result.textContent =
        "Secure tracking के लिए Mini App को Telegram Bot के अंदर खोलें।";
      return;
    }

    if (!code) {
      result.textContent =
        "Please enter your Application ID.";
      return;
    }

    result.textContent = "Checking…";

    try {
      const data = await api(
        "/miniapp/api/track",
        {
          init_data: initData,
          application_id: code
        }
      );

      result.innerHTML = `
        <b>
          ${escapeHtml(
            data.application.application_id
          )}
        </b>
        <br>

        ${escapeHtml(data.application.wallet)}
        <br>

        <span class="badge">
          ${escapeHtml(
            data.application.status_label
          )}
        </span>
      `;
    } catch (error) {
      result.textContent = error.message;
    }
  }

  document
    .querySelectorAll("[data-view]")
    .forEach((button) => {
      button.addEventListener("click", () => {
        const view = button.dataset.view;

        showView(view);

        if (view === "applications") {
          loadApplications();
        }
      });
    });

  document
    .querySelector("[data-refresh-wallets]")
    ?.addEventListener("click", loadWallets);

  document
    .querySelector("[data-refresh-applications]")
    ?.addEventListener(
      "click",
      loadApplications
    );

  document
    .getElementById("trackButton")
    ?.addEventListener(
      "click",
      trackApplication
    );

  document
    .getElementById("applicationId")
    ?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        trackApplication();
      }
    });

  document
    .getElementById("applyButton")
    ?.addEventListener("click", () => {
      showView("apply");
    });

  document
    .getElementById("closeMiniApp")
    ?.addEventListener("click", () => {
      if (tg) {
        tg.close();
      } else {
        showNotice(
          "यह page Telegram Bot के अंदर Mini App के रूप में खोलें, फिर /apply command tap करें।"
        );
      }
    });

  if (initUser) {
    const name = [
      initUser.first_name,
      initUser.last_name
    ]
      .filter(Boolean)
      .join(" ");

    const welcomeName =
      document.getElementById("welcomeName");

    if (welcomeName) {
      welcomeName.textContent =
        name || "User";
    }
  } else {
    showNotice(
      "Preview mode: Wallet services दिखेंगी। My Applications और Track Status के लिए इसे Telegram Bot के अंदर खोलें।"
    );
  }

  loadWallets();
})();
