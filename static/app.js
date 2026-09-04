// ThetaGuard Minimal Read-Only Status Console & Analytics Engine
let pnlChart = null;
let volChart = null;

async function fetchJSON(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error(`Fetch error for ${url}:`, err);
    return null;
  }
}

function formatCurrency(val) {
  if (val === undefined || val === null) return "$0.00";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(val);
}

function initCharts() {
  const pnlCanvas = document.getElementById("chart-pnl");
  const volCanvas = document.getElementById("chart-vol");

  if (pnlCanvas && typeof Chart !== "undefined" && !pnlChart) {
    const ctx = pnlCanvas.getContext("2d");
    pnlChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: ["Kickoff"],
        datasets: [{
          label: "Cumulative Realized P&L ($)",
          data: [0],
          borderColor: "#3fb950",
          backgroundColor: "rgba(63, 185, 80, 0.12)",
          borderWidth: 2,
          pointRadius: 4,
          pointBackgroundColor: "#3fb950",
          pointHoverRadius: 6,
          fill: true,
          tension: 0.25,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#161b22",
            titleColor: "#f0f6fc",
            bodyColor: "#8b949e",
            borderColor: "#30363d",
            borderWidth: 1,
            callbacks: {
              label: (item) => ` Realized P&L: $${Number(item.raw).toFixed(2)}`
            }
          }
        },
        scales: {
          x: {
            grid: { color: "#21262d" },
            ticks: { color: "#8b949e", font: { size: 10 } }
          },
          y: {
            grid: { color: "#21262d" },
            ticks: {
              color: "#8b949e",
              font: { size: 10 },
              callback: (val) => `$${val}`
            }
          }
        }
      }
    });
  }

  if (volCanvas && typeof Chart !== "undefined" && !volChart) {
    const ctx = volCanvas.getContext("2d");
    volChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: ["--"],
        datasets: [
          {
            label: "SPY 52W Vol Rank",
            data: [0],
            borderColor: "#58a6ff",
            backgroundColor: "rgba(88, 166, 255, 0.1)",
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: "#58a6ff",
            tension: 0.2,
          },
          {
            label: "QQQ 52W Vol Rank",
            data: [0],
            borderColor: "#bc8cff",
            backgroundColor: "rgba(188, 140, 255, 0.1)",
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: "#bc8cff",
            tension: 0.2,
          },
          {
            label: "Entry Threshold (30.0 Floor)",
            data: [30],
            borderColor: "#d29922",
            borderWidth: 1.5,
            borderDash: [5, 5],
            pointRadius: 0,
            fill: false,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: {
          legend: {
            display: true,
            position: "top",
            labels: {
              color: "#8b949e",
              font: { size: 11 },
              boxWidth: 12,
            }
          },
          tooltip: {
            backgroundColor: "#161b22",
            titleColor: "#f0f6fc",
            bodyColor: "#8b949e",
            borderColor: "#30363d",
            borderWidth: 1,
          }
        },
        scales: {
          x: {
            grid: { color: "#21262d" },
            ticks: { color: "#8b949e", font: { size: 10 } }
          },
          y: {
            min: 0,
            max: 100,
            grid: { color: "#21262d" },
            ticks: {
              color: "#8b949e",
              font: { size: 10 },
              callback: (val) => `${val}%`
            }
          }
        }
      }
    });
  }
}

async function updateDashboard() {
  initCharts();

  // 1. Fetch System Status
  const status = await fetchJSON("/api/status");
  if (status) {
    document.getElementById("val-equity").textContent = formatCurrency(status.equity);
    document.getElementById("val-cash").textContent = formatCurrency(status.cash);
    document.getElementById("val-buying-power").textContent = `BP: ${formatCurrency(status.buying_power)}`;
    document.getElementById("val-risk").textContent = formatCurrency(status.total_capital_at_risk);
    document.getElementById("val-risk-cap").textContent = `${status.risk_pct_of_equity.toFixed(2)}% / 5.0% Portfolio Ceiling`;

    // Account ID & Data Source Badges
    const acctBadge = document.getElementById("badge-account-id");
    if (acctBadge && status.account_id) {
      const maskedId = status.account_id.length > 10 
        ? `${status.account_id.slice(0, 4)}...${status.account_id.slice(-4)}`
        : status.account_id;
      acctBadge.textContent = `ACCT: ${maskedId}`;
    }

    const sourceBadge = document.getElementById("badge-data-source");
    sourceBadge.textContent = `DATA: ${status.data_source}`;
    if (status.data_source === "ALPACA_LIVE_PAPER_API") {
      sourceBadge.className = "badge badge-source";
    } else {
      sourceBadge.className = "badge badge-neutral";
    }

    // Macro Lockout Badge
    const lockoutBadge = document.getElementById("badge-lockout");
    if (status.is_in_macro_lockout) {
      lockoutBadge.textContent = `LOCKOUT: ${status.active_macro_event || "ACTIVE"}`;
      lockoutBadge.className = "badge badge-lockout";
    } else {
      lockoutBadge.textContent = "MACRO CLEAR";
      lockoutBadge.className = "badge badge-clear";
    }
  }

  // 2. Fetch Macro Calendar
  const events = await fetchJSON("/api/macro-calendar");
  const macroTbody = document.getElementById("macro-calendar-tbody");
  if (events && events.length > 0) {
    macroTbody.innerHTML = events.map(ev => `
      <tr>
        <td><strong>${ev.name}</strong></td>
        <td>${new Date(ev.release_time).toLocaleString("en-US", { timeZone: "America/New_York" })} ET</td>
        <td>${new Date(ev.lockout_start).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" })} -> ${new Date(ev.lockout_end).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" })} ET</td>
        <td>${ev.hours_until_release > 0 ? ev.hours_until_release + " hrs" : "Released"}</td>
        <td><span class="${ev.is_active ? 'badge badge-lockout' : (new Date(ev.release_time) < new Date() ? 'badge badge-past' : 'badge badge-clear')}">${ev.is_active ? 'LOCKOUT ACTIVE' : (new Date(ev.release_time) < new Date() ? 'CLEARED' : 'UPCOMING')}</span></td>
      </tr>
    `).join("");
  } else {
    macroTbody.innerHTML = `<tr><td colspan="5" class="text-center">No active or upcoming macro lockouts found.</td></tr>`;
  }

  // 3. Fetch Active Positions
  const positions = await fetchJSON("/api/positions");
  const posTbody = document.getElementById("positions-tbody");
  const countBadge = document.getElementById("active-spreads-count");
  if (positions && positions.length > 0) {
    countBadge.textContent = `${positions.length} / ${(status && status.max_concurrent_spreads) || 2} Active`;
    posTbody.innerHTML = positions.map(p => `
      <tr>
        <td><code>${p.id}</code></td>
        <td><strong>${p.underlying}</strong></td>
        <td>$${p.short_strike} (${p.short_delta ? p.short_delta.toFixed(3) : '-'})</td>
        <td>$${p.long_strike}</td>
        <td>${p.expiration}</td>
        <td>$${p.entry_credit.toFixed(2)}</td>
        <td>$${p.max_profit.toFixed(2)}</td>
        <td>$${p.max_loss.toFixed(2)}</td>
        <td>$${p.take_profit_target.toFixed(2)}</td>
        <td>$${p.stop_loss_target.toFixed(2)}</td>
        <td><span class="badge badge-clear">${p.status}</span></td>
      </tr>
    `).join("");
  } else {
    countBadge.textContent = `0 / ${(status && status.max_concurrent_spreads) || 2} Active`;
    posTbody.innerHTML = `<tr><td colspan="11" class="text-center">No active open positions. Macro safeguards active.</td></tr>`;
  }

  // 4. Fetch Trade History & Running P&L
  // Filter all closed positions with realized PnL regardless of exit reason
  const trades = await fetchJSON("/api/trades");
  const tradesTbody = document.getElementById("trades-tbody");
  const totalTradesBadge = document.getElementById("total-trades-count");
  if (trades && trades.length > 0) {
    const closedTrades = trades.filter(t => t.realized_pnl !== null && t.realized_pnl !== undefined);
    const sortedClosedTrades = [...closedTrades].sort((a, b) => new Date(a.timestamp || 0) - new Date(b.timestamp || 0));
    const totalPnl = sortedClosedTrades.reduce((acc, t) => acc + (t.realized_pnl || 0), 0);
    
    const pnlEl = document.getElementById("val-pnl");
    pnlEl.textContent = (totalPnl >= 0 ? "+" : "-") + formatCurrency(Math.abs(totalPnl));
    pnlEl.className = totalPnl >= 0 ? "card-value text-green" : "card-value text-red";
    document.getElementById("val-pnl-sub").textContent = `${sortedClosedTrades.length} closed trades (${trades.length} total events)`;

    totalTradesBadge.textContent = `${trades.length} Records`;
    tradesTbody.innerHTML = trades.slice(-10).reverse().map(t => {
      const isClosed = t.realized_pnl !== null && t.realized_pnl !== undefined;
      const pnlStr = isClosed
        ? `<strong class="${t.realized_pnl >= 0 ? 'text-green' : 'text-red'}">${t.realized_pnl >= 0 ? '+' : '-'}$${Math.abs(t.realized_pnl).toFixed(2)}</strong>`
        : '-';
      const creditStr = t.net_credit_executed ? `$${t.net_credit_executed.toFixed(2)}` : '-';
      const isSuccessStatus = t.execution_status === 'CLOSED' || t.execution_status === 'EXPIRED_WORTHLESS' || t.execution_status === 'FILLED';
      return `
        <tr>
          <td><code>${t.trade_id}</code></td>
          <td>${t.timestamp ? new Date(t.timestamp).toISOString().replace('T', ' ').slice(0, 16) : '-'}</td>
          <td><strong>${t.underlying}</strong></td>
          <td><code>${t.action}</code></td>
          <td>${creditStr}</td>
          <td>${pnlStr}</td>
          <td><span class="badge ${isSuccessStatus ? 'badge-clear' : 'badge-neutral'}">${t.execution_status}</span></td>
        </tr>
      `;
    }).join("");

    // Update P&L Chart with strictly chronological points
    if (pnlChart) {
      const pnlLabels = ["Kickoff"];
      const pnlData = [0];
      let cumPnl = 0;
      sortedClosedTrades.forEach((t, idx) => {
        cumPnl += (t.realized_pnl || 0);
        const timeStr = t.timestamp ? new Date(t.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : `T${idx+1}`;
        pnlLabels.push(timeStr);
        pnlData.push(Number(cumPnl.toFixed(2)));
      });
      pnlChart.data.labels = pnlLabels;
      pnlChart.data.datasets[0].data = pnlData;
      pnlChart.data.datasets[0].borderColor = cumPnl >= 0 ? "#3fb950" : "#f85149";
      pnlChart.data.datasets[0].backgroundColor = cumPnl >= 0 ? "rgba(63, 185, 80, 0.12)" : "rgba(248, 81, 73, 0.12)";
      pnlChart.update();
    }
  } else {
    totalTradesBadge.textContent = "0 Records";
    tradesTbody.innerHTML = `<tr><td colspan="7" class="text-center">No completed trades recorded yet.</td></tr>`;
  }

  // 5. Fetch Volatility History Time Series (recent rolling window sorted strictly chronologically)
  const volHistory = await fetchJSON("/api/volatility-history?limit=100");
  if (volHistory && volHistory.length > 0 && volChart) {
    // Sort chronologically ascending by timestamp before charting
    const sortedVolHistory = [...volHistory].sort((a, b) => new Date(a.timestamp || 0) - new Date(b.timestamp || 0));

    const volLabels = [];
    const spyData = [];
    const qqqData = [];
    const thresholdData = [];

    sortedVolHistory.forEach(v => {
      const tStr = v.timestamp ? new Date(v.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '--';
      volLabels.push(tStr);
      spyData.push(v.spy_vol_rank);
      qqqData.push(v.qqq_vol_rank);
      thresholdData.push(v.iv_rank_floor || 30.0);
    });

    volChart.data.labels = volLabels;
    volChart.data.datasets[0].data = spyData;
    volChart.data.datasets[1].data = qqqData;
    volChart.data.datasets[2].data = thresholdData;
    volChart.update();
  }

  // Update footer timestamp
  const updatedEl = document.getElementById("last-updated");
  if (updatedEl) {
    updatedEl.textContent = `Last Updated: ${new Date().toLocaleTimeString()}`;
  }
}

// Initial bootstrap and resilient recursive polling loop
updateDashboard();
function scheduleNextPoll() {
  setTimeout(async () => {
    await updateDashboard();
    scheduleNextPoll();
  }, 5000);
}
scheduleNextPoll();
