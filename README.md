# Victor PDF Tools Box

## UI 第二代：Qt 桌面版

現在的 `start_desktop_app.bat` 會啟動 PySide6 / Qt 版介面：

- 直接把 PDF 拖入縮圖區
- 每個 PDF 會像 Adobe DC 一樣開成獨立文件 Tab
- 縮圖可按住滑鼠左鍵直接拖到目標位置插入重排，拖動時會顯示縮小頁面預覽
- 每張縮圖下方顯示目前 `Page N`、原始頁碼及檔名，方便核對位置
- 雙擊頁面縮圖可開啟大圖預覽
- 旋轉頁面後縮圖會即時以旋轉後方向重畫，橫向頁面會以橫向頁框顯示
- 縮圖卡片之間留有較明顯間距，方便閱讀和拖拉
- 支援複製 / 剪下 / 貼上頁面到其他 PDF Tab，快捷鍵為 `Ctrl+C` / `Ctrl+X` / `Ctrl+V`
- 支援復原上一個頁面編輯動作，快捷鍵為 `Ctrl+Z`
- 支援刪除選取頁面，快捷鍵為 `Delete`
- 大 PDF 會先顯示頁面卡片，再分批補上縮圖，避免拖第二個檔案時卡死
- 上方顯示總頁數及目前選取頁數
- 多選縮圖後用上方按鈕統一左轉 / 右轉
- 擷取可直接輸入頁碼範圍，例如 `1-12,15-18`
- 擷取合併後會把輸出的 PDF 自動開成新文件 Tab
- 可用「合併文件...」選擇已開文件 Tab 或外部 PDF，再拖拉文件圖示調整合併順序
- 合併文件對話框支援移除選取、清空清單、復原上一個動作；快捷鍵為 `Delete` / `Ctrl+Z`，亦可右鍵操作
- 合併清單中的文件會以綠色邊框顯示選取狀態，未選取就移除時會提示
- 可將目前排列和旋轉儲存為最新版 PDF
- 「常用 PDF 工具」分頁已補回批次工具：合併、拆分 ZIP、抽頁、刪頁、旋轉、加密、解密、壓縮、抽文字、圖片轉 PDF、PDF 資訊、頁碼、水印、刪空白頁、清理 Metadata
- 常用工具支援拖放 PDF / 圖片到清單；輸出 PDF 會自動開成新文件 Tab
- 「文字標註 / 覆蓋」分頁：即時預覽白底覆蓋與文字效果、字體／大小／粗體／顏色、點擊設定位置後另存並自動開新 Tab
- GitHub Actions 會在每次 push / PR 自動執行單元測試（`.github/workflows/test.yml`）
- 組織分頁可勾選「儲存 PDF 後開成新 Tab」「匯出後開啟輸出資料夾」
- 常用工具可勾選「PDF 輸出後開成新 Tab」「ZIP / TXT 輸出後開啟資料夾」；偏好會記住

舊版 Tkinter 程式仍保留在 `desktop_app.py`，方便需要過渡或回查功能時使用。

## 建議後續功能

- OCR、PDF 轉 Word、電子簽名等高階功能（需先評估授權）
- 處理紀錄 / audit log（公司多人共用時）
- 自動清理暫存 workspace 排程

公司內部本機 PDF 工具箱，目標是提供接近常見 PDF 軟件的日常功能，同時避免把上市公司財務資料、審計文件或個人資料上傳到外部服務。

## 已有功能

- 合併 PDF
- 逐頁拆分 PDF
- 抽取指定頁碼
- 刪除指定頁碼
- 旋轉頁面
- PDF 加密
- 已知密碼 PDF 解密
- 基礎壓縮
- 抽取 PDF 文字
- 圖片轉 PDF
- PDF 頁數及 metadata 資訊

## 桌面 EXE 版

如想用獨立視窗介面，可先直接啟動桌面版：

```powershell
start_desktop_app.bat
```

桌面版支援：

- 直接把 PDF / 圖片檔拖入清單
- 加入 PDF 後展開成每一頁
- 切換「大圖示模式」查看每頁縮圖
- 在大圖示模式直接拖拉縮圖重排頁面
- 在組織頁面選取縮圖後，用上方左轉 / 右轉按鈕旋轉頁面，並儲存為最新版 PDF
- 擷取選取頁面或輸入頁碼範圍，例如 `1-12,15-18`，可合併成一份 PDF 或每頁單獨匯出
- 拖曳頁面調整順序
- 用「上移 / 下移」微調頁面
- 移除指定頁面
- 按清單次序匯出新 PDF
- 文字標註 / 覆蓋修改：預覽頁面、點擊位置、加文字或白底覆蓋後另存
- 常用工具頁內拖曳/上下載入順序處理合併、抽頁、刪頁、旋轉、加密、解密、壓縮、抽文字、圖片轉 PDF
- 第二階段工具：加頁碼 / Footer、加水印 / 印章、刪除空白頁、清理 Metadata

打包成 EXE：

```powershell
build_exe.bat
```

完成後 EXE 會在：

```text
C:\tmp\victor_pdf_dist\VictorPDFToolsBox\VictorPDFToolsBox.exe
```

請保留整個 `C:\tmp\victor_pdf_dist\VictorPDFToolsBox` 資料夾一起移動，因為 `_internal`
內含 EXE 所需的 Python/Tkinter/PDF library。這種 onedir 模式較適合公司 Windows
安全策略；單檔 EXE 在部分電腦會被防毒或受控資料夾阻止生成。

## 本地網頁版啟動

```powershell
python -m pip install -r requirements.txt
python app.py
```

然後開啟：

```text
http://127.0.0.1:5055
```

## 合規及授權注意

本工具不使用 Adobe DC、CleverPDF 或其他第三方服務的程式碼、商標、版面或文案。第一版核心功能使用 `pypdf` 和 `Pillow`，兩者授權較適合內部工具使用。若日後加入 OCR、PDF 轉 Word、電子簽名或高階壓縮，應先檢查相關第三方程式庫或商業 API 的授權條款。

## 資料保護建議

- 建議只在公司電腦或公司內網運行。
- 不要把 `workspace/uploads` 或 `workspace/outputs` 同步到外部雲端。
- 處理未公告業績、董事會文件、薪酬、人事或銀行資料後，使用首頁「清理暫存檔」。
- 如要多人共用，建議加 Windows AD / SSO、權限分組、audit log 和自動清理排程。
