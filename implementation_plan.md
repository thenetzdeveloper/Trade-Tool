# Implementation Plan: Economic Calendar Fix, MT5 Settings, Dynamic AI SL/TP, Reverse Exits & Background Auto-Trading Daemon

We will enhance the Gold Bot AI application with:
1. **Economic Calendar UI Fix**: Align the calendar card padding and width to prevent horizontal squeezing or cut-off on standard screen sizes.
2. **Settings Page UI Enhancements**:
   - Add a dropdown selector for **MT5 Account Type** (Demo vs Real) with proper Khmer labels.
   - Add a separate, distinct **Save Configuration** submit button for the MT5 and Risk Management card.
   - Display a status tag indicating the account type (`Connected (DEMO)` / `Connected (REAL)`) on the sidebar status card and status API.
3. **Dynamic AI SL/TP & Exits (Exits / WAIT Logic)**:
   - Modify the order placement function to accept the AI's predicted `stop_loss` and `take_profit` levels directly, falling back to static config values if the AI response is absent.
   - Implement **Reverse Trade Closures**: Automatically detect and close any existing open position of the *opposite* direction on Gold before entering a new buy/sell trade.
4. **Automated Background Trading Daemon**:
   - Run a persistent background thread (`threading.Thread`) that monitors the active timeframe (e.g. H1).
   - Detect when a new candle has opened by inspecting historical rates timestamps.
   - When a new candle opens and `live_trading` is enabled, automatically trigger the technical calculations + AI prompt generation, query Gemini/OpenAI, and submit/close orders on the logged-in MT5 account.
5. **Real-time Logs Syncing**:
   - Maintain a global `BACKEND_LOGS` list on the Flask server.
   - Log background daemon activities (candle detections, AI analysis starts, order placements, opposite closures) to this list.
   - Expose a `/api/logs` endpoint and poll it from `dashboard.js` to update the console terminal log screen in real-time.

---

## User Review Required

> [!IMPORTANT]
> **MT5 Auto-Close (Exits Logic)**:
> - The reverse trade closure logic will immediately trigger when the AI issues a `BUY` or `SELL` signal. If the account holds a short position on gold, and a `BUY` signal is generated, the bot will close the short position before opening a long position.
> - For `WAIT` signals, the bot does not take any actions on active trades. It will only monitor and wait.
> - **Please confirm this is your preferred exits logic.**

---

## Proposed Changes

### 1. Python Server Backend (`app.py`)

#### [MODIFY] [app.py](file:///c:/Netz/Trade-Tool/app.py)
- Introduce a global list `BACKEND_LOGS` and a helper function `add_backend_log(message, type)` to persist server-side logs.
- Refactor the core AI analysis and order submission logic out of the `/api/analyze` Flask route into a helper function `run_ai_analysis_and_trade(timeframe="H1")`.
- Update `execute_mt5_order(config, signal_type, current_price, sl=None, tp=None)` to:
  - Close any active opposite gold positions (`POSITION_TYPE_BUY` if selling, or `POSITION_TYPE_SELL` if buying) before submitting the new order.
  - Apply the dynamic AI-generated `sl` and `tp` values to the MT5 trade request if they are passed.
- Add an `auto_trading_daemon()` function running in a background thread that monitors candle opens for timeframe `H1` and runs the AI trade logic when a new candle starts.
- Add `/api/logs` endpoint to return the logs list.
- Update `/api/status` to return whether the account type is Demo or Real (`mt5_account_type` property).

---

### 2. Frontend Layout & CSS (`templates/index.html`, `static/css/style.css`)

#### [MODIFY] [index.html](file:///c:/Netz/Trade-Tool/templates/index.html)
- Add padding to the economic calendar section for cleaner visual framing.
- Update the MT5 form in the Settings tab to:
  - Add an Account Type dropdown (`mt5_account_type` select).
  - Add a dedicated submit button: `រក្សាទុកការកំណត់ MT5 (Save MT5 Settings)`.
- Update the sidebar MT5 connection badge text dynamically to show account type.

#### [MODIFY] [style.css](file:///c:/Netz/Trade-Tool/static/css/style.css)
- Add a padding ruleset for the calendar card content wrapper to separate widget content from the borders.
- Style the new account type selector elements and dedicated submit buttons in the MT5 card.

---

### 3. Frontend Controller (`static/js/dashboard.js`)

#### [MODIFY] [dashboard.js](file:///c:/Netz/Trade-Tool/static/js/dashboard.js)
- Implement `updateTerminalLogs()` polling (every 4 seconds) to fetch background logs from `/api/logs` and append them to the log terminal.
- Update `saveConfig()` and settings initialization logic to support the new `mt5_account_type` parameter and handle the separate submit button.
- Update the MT5 badge rendering to display `Connected (DEMO)` or `Connected (REAL)` based on the updated `/api/status` API.

---

## Verification Plan

### Automated/Local Tests
- Propose and run a python request query to `/api/logs` to confirm logs are populated and returned correctly.
- Test MT5 connection mock function with the new `account_type` configs.

### Manual Verification
1. Launch the server and check the settings page.
2. Select "Demo Account" and save MT5 settings, then verify the sidebar shows `Connected (DEMO)`.
3. Switch to "Real Account" and save, verify status updates to `Connected (REAL)`.
4. Switch to the Calendar tab and visually confirm that the table columns and data boundaries have clean spacing.
5. Review the System & Trade logs tab to confirm background logs are polling and appending correctly.
6. Verify dynamic SL/TP and reverse trade closures by simulating a buy or sell signal while an opposite trade is running.
