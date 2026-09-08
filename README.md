# ResiLight — 5G MEC 韌性降階號誌控制系統

> 2026 中華電信智慧創新應用大賽（智慧交通主題）

## 專案簡介
ResiLight 是專為 5G MEC 智慧號誌打造的高韌性容錯降階控制架構。解決當 5G 專網、回程光纖或 MEC 邊緣節點發生連線劣化與中斷時，智慧交通號誌如何平滑降階並在通訊恢復時無擾動銜接（Bumpless Transfer）的核心可靠度工程問題。

## 系統核心架構
- **Level 0（正常模式）**：雲端/邊緣 MARL 全局協同控制。
- **Level 1（部分降階）**：相鄰路口 P2P 邊緣局部協調。
- **Level 2（完全降階）**：路側獨立 Max Pressure 確定性規則引擎（Varaiya, 2013）。
- **無擾動切換（Bumpless Transfer）**：網路恢復時的狀態對齊與平滑時制過渡機制。
- **LLM 診斷 Agent**：交控中心維運解釋層（位於安全控制迴路之外）。

## 模組結構
- `envs/`：SUMO 微觀模擬環境配置、程式化號誌路網建置、TraCI 通訊介面封裝。
- `controllers/`：號誌控制器（固定時制 Baseline、Max Pressure 後備控制等）。
- `network_sim/`：5G 通訊品質劣化模擬器（延遲、抖動、封包遺失注入）。
- `tests/`：單元與整合驗證測試。

## 快速開始
```bash
pip install -r requirements.txt
python run_phase1_demo.py
pytest tests/ -v
```
