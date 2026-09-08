# 實做規劃書：ResiLight

**用途**：本文件是給負責撰寫程式碼的 AI Agent（目前指定 Gemini 3.8 Flash）的技術實作規格書，對應提案文件 `提案規劃書_ResiLight.md`。**開始實作前，請先讀完 `實做規劃書_00_共用基礎建設.md` 並完成該文件描述的環境安裝與基礎 pipeline**，本文件只描述 ResiLight 特有的部分，不重複共用基礎建設的內容。

**專案一句話定位**：5G MEC 通訊品質劣化時的號誌控制分層降階系統，核心 demo 是「模擬網路斷線/延遲飆升 → 系統從全局協調平滑降級為本地獨立控制 → 連線恢復後無擾動切回」的對比展示。

---

## 一、整體要達成的目標（驗收標準）

1. 一個可以模擬「路口間通訊品質」的獨立軟體層（延遲、抖動、封包遺失可人工控制），這個東西 SUMO 本身不提供，需要另外寫
2. 一個三層降階狀態機：Level 0（MARL 全局協調）/ Level 1（鄰居 P2P 協調）/ Level 2（Max Pressure 獨立運作），能依通訊品質指標自動切換
3. 一個正確實作的 Max Pressure 規則控制器（Level 2 用，公式見下）
4. 一個無擾動切換（Bumpless Transfer）機制，展示連線恢復時的平滑過渡
5. 量化對比：有降階機制 vs 沒有降階機制，在網路劣化情境下的通行效率差異
6. LLM 診斷 Agent 的最小可行版本：讀取降階事件記錄，呼叫 LLM API 生成事件摘要文字，輸出到一個簡單的儀表板（可以只是終端機輸出或簡單網頁，不需要做得多精美）

**不要求**：Level 0 的 MARL 控制器不需要做到 WaveGuard 那種 Grid BEV + 多目標獎勵的複雜度，這裡只需要一個「堪用」的協調控制器，可以直接用 LibSignal 或 sumo-rl 現成的 baseline（例如 MPLight），把力氣留給本專案真正的差異化部分（降階邏輯本身）。

---

## 二、核心技術組件與實作規格

### 2.1 網路品質模擬層（本專案最需要自己寫的部分）

SUMO/TraCI 模擬的是車流物理，不模擬網路通訊品質，這部分完全要自己實作一個獨立模組，建議命名 `network_sim/link_quality.py`：

```
class NetworkQualitySimulator:
    功能：
    - 維護每個路口（或每對相鄰路口）目前的通訊品質狀態：latency_ms, jitter_ms, packet_loss_rate
    - 提供 inject_event(scenario) 方法，可以在指定的模擬時間步注入劣化事件
      例如：inject_event(start_step=500, duration_steps=200, latency_ms=500, packet_loss_rate=1.0)
      代表從第500步開始，持續200步，模擬完全斷線（封包遺失率100%）
    - 提供 get_current_quality(intersection_id) 方法，讓降階狀態機查詢當下品質
    - 在「訊息傳遞」的地方（例如 MARL agent 之間交換狀態向量時）實際套用延遲/遺失邏輯：
      若 packet_loss_rate 觸發（用亂數判斷），該次狀態交換視為失敗，agent 收不到鄰居最新狀態；
      若有 latency_ms，可以用一個緩衝佇列模擬「訊息要過幾個模擬步才會送達」
```

這個模組是整個 ResiLight demo 能不能成立的關鍵，因為它negative-simulates了「網路不完美」這件事——沒有這個模組，降階機制就沒有觸發的理由，等於整個提案的核心賣點做不出來，**優先度最高，第一個開始寫**。

### 2.2 三層降階狀態機

```
class DegradationController:
    狀態: Level.NORMAL / Level.PARTIAL / Level.FALLBACK

    evaluate_link_quality(latency, jitter, packet_loss) -> Level:
        # 建議初始閾值（可依模擬結果調整）：
        if latency < 50ms and jitter < 10ms and packet_loss < 1%:
            return Level.NORMAL
        elif latency < 200ms and packet_loss < 10%:
            return Level.PARTIAL
        else:
            return Level.FALLBACK

    每個路口每個模擬步都要呼叫一次這個方法，決定當下要用哪個控制器輸出號誌決策：
        Level.NORMAL   -> 用 Level 0 的 MARL agent 輸出
        Level.PARTIAL  -> 用只跟鄰居直接交換資訊（不透過中央協調）的簡化協調邏輯
                          （最簡單的實作方式：拿掉 GAT 的全局聚合，只用相鄰路口的
                           排隊長度做簡單加權，不需要另外訓練一個新模型）
        Level.FALLBACK -> 用 Max Pressure 規則控制器（見 2.3）
```

**Level 1（部分降階）不需要另外訓練一個新的 RL 模型**——時間有限的情況下，用一個簡單的規則式「鄰居感知」邏輯（例如：根據鄰居回報的排隊長度，稍微調整自己的相位時長）就足以在demo裡展示「有比完全獨立運作更好、但不到全局協調的中間狀態」，不要為了這一層另外投入 RL 訓練成本。

### 2.3 Max Pressure 規則控制器

這是有明確數學公式、不需要訓練、可以直接照著實作的部分（Varaiya, 2013）：

```
對每個路口的每個可能相位 p，計算該相位的「壓力」：
  pressure(p) = Σ(進入該相位控制之進車道的車輛數) - Σ(該相位對應離開車道的車輛數)

選擇 pressure(p) 最大的相位作為下一個要執行的相位
（進出車道的車輛數可直接用 traci.lane.getLastStepVehicleNumber() 取得）
```

這個控制器完全不依賴任何鄰居或雲端資訊，純粹用路口自己的本地感測資料運作，符合 Level 2 完全獨立運作的定位。**這部分建議最先實作完成，因為它同時是 Level 2 的核心，也是 WaveGuard 專案安全降階機制可以直接複用的元件。**

### 2.4 無擾動切換（Bumpless Transfer）

這是 ResiLight 提案書裡最具差異化、但也是文獻裡沒有直接對應實作可以參考的部分，**需要團隊自己設計具體的轉換邏輯**，這裡給一個可執行的具體建議（不是照抄哪篇論文，是把控制理論概念翻譯到號誌相位這個離散決策場域）：

```
當偵測到從 Level.FALLBACK（或 PARTIAL）要切回 Level.NORMAL 時：
  不要在下一個模擬步立刻套用 MARL agent 的原始輸出
  改為：設定一個過渡期（建議 K = 3-5 個號誌週期）
  在過渡期內，每個週期的相位時長 = (1 - w_k) * MaxPressure建議時長 + w_k * MARL建議時長
  其中 w_k 從 0 線性（或用更平滑的曲線）增加到 1，跨越 K 個週期
  過渡期結束後，完全採用 MARL 輸出，正式回到 Level.NORMAL
```

**這是本專案最值得在 demo 裡特別展示的一段**：跑一次「直接切回」（沒有過渡期，Bump）跟「有過渡期平滑切回」的對比，量化展示相位時長的變化幅度差異（可以用一張時間序列圖，X軸是模擬時間，Y軸是相位時長，直接切回會有明顯的跳動，平滑切回是連續曲線）。

### 2.5 LLM 診斷 Agent

**這個元件完全獨立於安全控制迴路，優先度最低，時間不夠可以最後做或用極簡版本**：

```
1. DegradationController 每次狀態切換時，寫一筆事件記錄到 log（json格式）：
   {timestamp, from_level, to_level, latency, jitter, packet_loss, duration}
2. 一個獨立的腳本（例如 llm_agent/diagnose.py）定期讀取這些 log
3. 把最近的事件記錄組成 prompt，呼叫 LLM API（建議直接用 Gemini API，
   因為程式撰寫本身就是交給 Gemini，串接 Gemini API 應該對它來說最順手，
   也可以視情況換成其他 LLM API，不強制）
4. Prompt 設計方向：「以下是交通號誌系統的網路降階事件記錄，請用繁體中文
   生成一段簡短摘要，說明可能的成因（如短暫干擾 vs 持續性故障），並給
   交控中心操作員一個處理建議」
5. 輸出結果印到終端機或寫進一個簡單的 log 檔／網頁即可，不需要做成正式產品等級的儀表板
```

**明確的架構邊界**：這個 Agent 只讀 log，不能有任何寫回 DegradationController 或號誌控制邏輯的路徑，這是提案書裡承諾的安全邊界（LLM 輸出的內容再怎麼有誤差，都不能影響實際號誌控制行為），實作時務必遵守，不要為了方便把 LLM 輸出直接接回控制邏輯。

---

## 三、Demo 情境腳本

1. 選一個 5-8 路口的路廊（可與 WaveGuard 共用同一份路網設定）
2. 模擬跑到穩定狀態後，用 `NetworkQualitySimulator.inject_event()` 觸發一次完全斷線事件（模擬施工挖斷光纖），持續一段時間後再讓連線恢復
3. 分別跑「無降階機制」（斷線時直接沿用最後一次的舊決策或整個停滯）與「ResiLight 三段式降階」兩種模式，記錄同一段時間內的路口延誤、通行量
4. 額外跑一次「直接切回 vs Bumpless Transfer 平滑切回」的對比（見 2.4 節）
5. 輸出：降階狀態即時儀表板（可以簡單到只是一個會即時印出目前 Level、通訊品質數值的文字介面）+ 通行效率對比曲線圖 + LLM 診斷 Agent 生成的事件摘要範例截圖

---

## 四、技術棧清單（本專案額外需要的，共用部分見 00 文件）

```
（Level 0 MARL）sumo-rl 或 LibSignal 的 MPLight baseline，直接用現成的，不用像 WaveGuard 那樣客製化狀態表示
自訂 network_sim/ 模組（無現成套件可用，需自己實作，見 2.1 節）
matplotlib（相位時長對比圖、通行效率對比圖）
Gemini API（或其他 LLM API）的 Python SDK，用於 LLM 診斷 Agent
```

---

## 五、實作優先順序建議

1. 共用基礎建設（見 00 文件）跑通
2. **network_sim 網路品質模擬層**（2.1 節）——最優先，沒有這個後面全部做不了
3. Max Pressure 控制器（2.3 節）——公式明確，做出來立刻能驗證正確性
4. 三層降階狀態機（2.2 節），先接一個最簡單的 Level 0（固定時制或現成 MPLight baseline 都可以，不用等 MARL 訓練完美再往下做）
5. Bumpless Transfer 過渡邏輯（2.4 節）
6. Demo 情境腳本（第三節）跑出對比數據
7. 時間允許再做 LLM 診斷 Agent（2.5 節），這個沒做完也不影響核心論述成立

**如果時間不夠，LLM診斷Agent（2.5節）是第一個可以砍的，其次是Level 1的鄰居P2P邏輯（可以先用「Level 0與Level 2兩層」代替三層，demo時誠實說明「中間層為簡化實作」）。network_sim、Max Pressure、降階狀態機、Bumpless Transfer 這四個是核心賣點，不建議砍。**

---

## 六、給實作 Agent 的注意事項

1. **Bumpless Transfer 的具體轉換公式是本團隊自己設計翻譯出來的**，不是直接照抄某篇論文的公式（因為查證過，沒有論文把這個概念直接應用在交通號誌領域），實作時可以依實驗結果微調過渡曲線的形狀（線性 vs 指數 vs 其他），不需要拘泥於文件裡給的線性公式，只要「有一個明確、可重現、能展示出平滑效果」的機制就符合提案書的主張。
2. **network_sim 模組要能被兩個情境腳本重複使用、參數化控制**（斷線多久、延遲多高都要能從設定檔或函式參數控制），不要寫死成只能跑一種情境，決賽 demo 現場可能需要臨時調整情境參數。
3. LLM API 呼叫需要 API金鑰，這部分屬於機密資訊，不要把金鑰寫死在程式碼裡提交或外洩，用環境變數或 `.env` 檔案（並確認 `.gitignore` 排除掉）管理。
4. 提案書裡「劣化容忍度」等指標目前沒有具體數字，等模擬跑出真實結果後，要回頭更新提案書裡的預期成果表格，不要讓最終文件停留在「待模擬驗證」的佔位狀態。
