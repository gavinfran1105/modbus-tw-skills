# 安全說明 / Security

- 本 repo 的腳本**不連任何 Modbus 設備、不連網路**，只讀寫你指定的本機檔案；只用 Python 標準函式庫，沒有第三方相依套件。
- `decode_candidates.py` 只接受唯讀功能碼（FC03／FC04）的掃描結果，遇到寫入功能碼直接拒絕。
- skill 的規則禁止 AI 自動寫入設備。對運轉中的設備，請只做唯讀讀取，並先確認現場允許。
- 不要把原廠手冊、客戶的位置表、案場 IP 或設定檔提交到公開 repo。範例資料全部是虛構的。
- 發現安全問題請開 GitHub Issue（不要附上任何現場資料）。

The scripts never open network or serial connections; they only transform local files. The skills forbid automated Modbus writes.
