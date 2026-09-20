(() => {
  "use strict";

  const STORAGE_KEY = "wealth-monitor:holdings:v1";
  const catalog = JSON.parse(document.querySelector("#holdings-catalog").textContent);
  const catalogByCode = new Map(catalog.map((product) => [product.code.toUpperCase(), product]));
  const form = document.querySelector("#holding-form");
  const codeInput = document.querySelector("#product-code");
  const nameInput = document.querySelector("#product-name");
  const typeInput = document.querySelector("#transaction-type");
  const dateInput = document.querySelector("#transaction-date");
  const sharesInput = document.querySelector("#transaction-shares");
  const message = document.querySelector("#form-message");
  let state = loadState();

  function localDate() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function loadState() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (saved?.version === 1 && Array.isArray(saved.transactions)) return saved;
    } catch (_) {
      // A damaged local value is ignored; the page remains usable.
    }
    return { version: 1, transactions: [] };
  }

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      return true;
    } catch (_) {
      message.textContent = "浏览器未能保存数据，请检查是否使用了受限或无痕模式。";
      message.className = "form-message error";
      return false;
    }
  }

  function normalizeCode(value) {
    return value.trim().toUpperCase();
  }

  function signedShares(transaction) {
    return transaction.type === "SELL" ? -Number(transaction.shares) : Number(transaction.shares);
  }

  function positionAt(code, date) {
    return state.transactions
      .filter((item) => item.code === code && item.date <= date)
      .reduce((total, item) => total + signedShares(item), 0);
  }

  function ledgerIsValid(transactions) {
    const balances = new Map();
    const ordered = [...transactions].sort((a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id));
    for (const item of ordered) {
      const balance = (balances.get(item.code) || 0) + signedShares(item);
      if (balance < -0.000001) return false;
      balances.set(item.code, balance);
    }
    return true;
  }

  function numberOrNull(value) {
    const number = Number(value);
    return value !== null && value !== "" && Number.isFinite(number) ? number : null;
  }

  function normalizedNav(product) {
    return (product?.nav || []).map((row) => ({
      date: row.date,
      unit: numberOrNull(row.unit_nav),
      cumulative: numberOrNull(row.cumulative_nav),
      income: numberOrNull(row.ten_thousand_income),
    })).sort((a, b) => a.date.localeCompare(b.date));
  }

  function calculateProduct(code) {
    const transactions = state.transactions.filter((item) => item.code === code);
    const product = catalogByCode.get(code);
    const name = product?.name || transactions[0]?.name || code;
    const shares = positionAt(code, localDate());
    const rows = normalizedNav(product);
    if (!rows.length) return { code, name, shares, product, status: "NO_NAV" };

    const latest = rows.at(-1);
    const isCash = latest.income !== null;
    const unit = latest.unit ?? latest.cumulative;
    const value = isCash ? shares : (unit === null ? null : shares * unit);
    let latestProfit = null;
    let cumulativeProfit = 0;
    let calculatedDays = 0;

    for (let index = 1; index < rows.length; index += 1) {
      const previous = rows[index - 1];
      const current = rows[index];
      const eligibleShares = positionAt(code, previous.date);
      let profit = null;
      if (current.income !== null) {
        profit = eligibleShares * current.income / 10000;
      } else {
        const previousValue = previous.cumulative ?? previous.unit;
        const currentValue = current.cumulative ?? current.unit;
        if (previousValue !== null && currentValue !== null) {
          profit = eligibleShares * (currentValue - previousValue);
        }
      }
      if (profit !== null) {
        cumulativeProfit += profit;
        calculatedDays += 1;
        if (index === rows.length - 1) latestProfit = profit;
      }
    }

    return {
      code, name, shares, product, latest, unit, value, latestProfit,
      cumulativeProfit: calculatedDays ? cumulativeProfit : null,
      status: latestProfit === null ? "INSUFFICIENT" : "READY",
      isCash,
    };
  }

  function formatMoney(value, signed = false) {
    if (value === null || !Number.isFinite(value)) return "—";
    const prefix = signed && value > 0 ? "+" : "";
    return `${prefix}${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function formatShares(value) {
    return value.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", "\"": "&quot;",
    })[character]);
  }

  function renderPositions() {
    const codes = [...new Set(state.transactions.map((item) => item.code))];
    const positions = codes.map(calculateProduct).filter((item) => item.shares > 0.000001);
    const container = document.querySelector("#positions");
    document.querySelector("#positions-empty").hidden = positions.length > 0;
    document.querySelector("#holding-count").textContent = positions.length;
    document.querySelector("#transaction-count").textContent = `${state.transactions.length} 笔`;

    let totalValue = 0;
    let hasValue = false;
    let totalLatestProfit = 0;
    let hasLatestProfit = false;
    const latestDates = [];

    container.innerHTML = positions.map((position) => {
      if (position.value !== null && position.value !== undefined) {
        totalValue += position.value;
        hasValue = true;
      }
      if (position.latestProfit !== null && position.latestProfit !== undefined) {
        totalLatestProfit += position.latestProfit;
        hasLatestProfit = true;
      }
      if (position.latest?.date) latestDates.push(position.latest.date);

      const profitClass = position.latestProfit > 0 ? "positive" : (position.latestProfit < 0 ? "negative" : "");
      let dataStatus = "云端暂无该产品净值，持仓记录已保存在本机";
      if (position.status === "INSUFFICIENT") dataStatus = `最新净值 ${position.latest.date}，至少需要两个净值点计算收益`;
      if (position.status === "READY") dataStatus = position.latest.date === localDate() ? "今日净值已更新" : `最新净值日 ${position.latest.date} · 今日暂无新净值`;
      const detailLink = position.product?.detail_url ? `<a href="${escapeHtml(position.product.detail_url)}">查看公开资料 →</a>` : "";
      return `<article class="position-card">
        <div class="position-head"><div><h3>${escapeHtml(position.name)}</h3><span>${escapeHtml(position.code)}</span></div>${detailLink}</div>
        <div class="position-stats">
          <div><span>当前份额</span><b>${formatShares(position.shares)}</b></div>
          <div><span>最新净值</span><b>${position.unit === null || position.unit === undefined ? "—" : position.unit.toFixed(6)}</b></div>
          <div><span>持仓估值</span><b>${formatMoney(position.value)}</b></div>
          <div><span>最新披露收益</span><b class="${profitClass}">${formatMoney(position.latestProfit, true)}</b></div>
          <div><span>记录以来净值收益</span><b>${formatMoney(position.cumulativeProfit, true)}</b></div>
        </div>
        <p>${escapeHtml(dataStatus)}</p>
        <div class="position-actions"><button data-position-code="${escapeHtml(position.code)}" data-kind="BUY">追加买入</button><button data-position-code="${escapeHtml(position.code)}" data-kind="SELL">记录赎回</button></div>
      </article>`;
    }).join("");

    document.querySelector("#portfolio-value").textContent = hasValue ? formatMoney(totalValue) : "—";
    const profitElement = document.querySelector("#latest-profit");
    profitElement.textContent = hasLatestProfit ? formatMoney(totalLatestProfit, true) : "—";
    profitElement.className = totalLatestProfit > 0 ? "positive" : (totalLatestProfit < 0 ? "negative" : "");
    const uniqueDates = [...new Set(latestDates)];
    document.querySelector("#latest-profit-date").textContent = uniqueDates.length === 1 ? `净值日 ${uniqueDates[0]}` : (uniqueDates.length ? "各产品最新披露日" : "等待净值");
    document.querySelector("#valuation-note").textContent = latestDates.length && !latestDates.includes(localDate()) ? "今天暂无新净值，沿用最近披露数据" : "";
  }

  function renderTransactions() {
    const rows = document.querySelector("#transaction-rows");
    const transactions = [...state.transactions].sort((a, b) => b.date.localeCompare(a.date) || b.id.localeCompare(a.id));
    if (!transactions.length) {
      rows.innerHTML = '<tr><td colspan="5" class="empty">暂无份额变动记录</td></tr>';
      return;
    }
    rows.innerHTML = transactions.map((item) => `<tr><td>${escapeHtml(item.date)}</td><td><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.code)}</small></td><td><span class="transaction-type ${item.type === "SELL" ? "sell" : ""}">${item.type === "SELL" ? "赎回" : "买入"}</span></td><td>${item.type === "SELL" ? "−" : "+"}${formatShares(Number(item.shares))}</td><td><button class="delete-transaction" data-delete-id="${escapeHtml(item.id)}">删除</button></td></tr>`).join("");
  }

  function render() {
    renderPositions();
    renderTransactions();
  }

  function fillProductName() {
    const product = catalogByCode.get(normalizeCode(codeInput.value));
    nameInput.value = product ? product.name : "";
  }

  codeInput.addEventListener("input", fillProductName);
  dateInput.value = localDate();
  const requestedCode = normalizeCode(new URLSearchParams(location.search).get("code") || "");
  if (requestedCode) {
    codeInput.value = requestedCode;
    fillProductName();
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const code = normalizeCode(codeInput.value);
    const product = catalogByCode.get(code);
    const name = (product?.name || nameInput.value.trim() || code).slice(0, 120);
    const shares = Number(sharesInput.value);
    if (!code || !dateInput.value || !Number.isFinite(shares) || shares <= 0) return;
    const transaction = {
      id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      code, name, type: typeInput.value, date: dateInput.value, shares,
    };
    const updated = [...state.transactions, transaction];
    if (!ledgerIsValid(updated)) {
      message.textContent = "赎回份额超过该日期已有份额，请检查生效日期和数量。";
      message.className = "form-message error";
      return;
    }
    state.transactions = updated;
    if (!saveState()) {
      state.transactions = state.transactions.filter((item) => item.id !== transaction.id);
      return;
    }
    message.textContent = "已保存到当前浏览器。";
    message.className = "form-message success";
    sharesInput.value = "";
    render();
  });

  document.addEventListener("click", (event) => {
    const positionButton = event.target.closest("[data-position-code]");
    if (positionButton) {
      codeInput.value = positionButton.dataset.positionCode;
      typeInput.value = positionButton.dataset.kind;
      fillProductName();
      sharesInput.focus();
      form.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    const deleteButton = event.target.closest("[data-delete-id]");
    if (!deleteButton || !confirm("删除这笔份额变动记录？")) return;
    const updated = state.transactions.filter((item) => item.id !== deleteButton.dataset.deleteId);
    if (!ledgerIsValid(updated)) {
      alert("删除后会导致历史份额小于零。请先删除对应的赎回记录。");
      return;
    }
    const previous = state.transactions;
    state.transactions = updated;
    if (!saveState()) {
      state.transactions = previous;
      return;
    }
    render();
  });

  render();
})();
