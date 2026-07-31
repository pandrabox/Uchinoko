# Uchinoko for Palworld 使用方法 — VRChat 角色模型篇

*[日本語](manual.md) | [English](manual.en.md) | [한국어](manual.ko.md) | [简体中文](manual.zh-CN.md)*

## 角色模型的使用方法
開啟自己角色模型的 Unity 專案(可在 Unity 2022.3.22f1 上運作)。
![](img/2.webp)

將 Hierarchy 中自己的角色模型拖曳並放到 Assets 底下(這樣會將其轉為 prefab)。
![](img/3.webp)

在剛才建立的圖示上按右鍵,選擇「Show in Explorer」。
**結束 Unity**。
![](img/4.webp)

開啟 Uchinoko for Palworld(Uchinoko.exe)。
![](img/1.webp)

**僅第一次啟動時**,會顯示「首次設定」對話方塊,自動下載轉換所需的 Blender(約 350MB)。依網路環境不同可能需要數分鐘,請**耐心等待**。若在此處取消,之後的轉換將全部失敗。若進行不順利,請參考下方的「發生問題時」。

從檔案總管將自己角色模型的 prefab 檔案拖放到 Uchinoko for Palworld 上。
![](img/5.webp)

稍待片刻。
![](img/6.webp)

縮圖顯示後,「完整轉換(建立 MOD)」按鈕即可點選,請點選它。
![](img/7.webp)

會顯示使用條款,請確認內容後同意。
![](img/8.webp)

稍待片刻後即完成套用(請先關閉幻獸帕魯)。
![](img/9.webp)


## 發生問題時: 首次設定(下載 Blender)失敗

因網路連線問題等原因,首次啟動時的 Blender 自動下載有時會失敗。若拖放後讀取一直無法完成,或因錯誤而停止,請先懷疑這個原因。

1. 請先確認網路連線,然後重新啟動 Uchinoko for Palworld,或按下畫面右下角的「重新取得 Blender」按鈕。
2. 若仍然失敗,可以手動準備。
   1. 從 https://www.blender.org/download/ 下載 Blender 4.3.2 的 Windows x64 版(Portable/zip)。
   2. 解壓縮下載的 zip,將內含 `blender.exe` 的資料夾內容,直接複製到與 Uchinoko for Palworld 同一位置的 `assets\tools\blender-4.3.2-windows-x64\` 資料夾中(**依版本不同,此資料夾可能位於 `_internal\assets\tools\blender-4.3.2-windows-x64\`**。可透過 Uchinoko for Palworld 同一位置是否存在 `_internal` 資料夾來判斷)。


## Tips

- 本轉換工具是供個人使用自己的角色模型遊玩的工具。不支援多人遊玩等用途。
- 不支援與其他 pak MOD 併用。偵測到其他 pak MOD 時會顯示警告。
- 右下角的選單可以執行多種操作。
  - 套用至幻獸帕魯…當您轉換了多個角色並想切換,或轉換完成時幻獸帕魯正在執行而未能順利套用時使用
  - 解除 MOD…想要解除時使用
  - 重新整理清單…重新整理 MOD 清單
  - 刪除轉換結果…想刪除不再需要的角色時使用
  - 問題回報…遇到困難時使用
  - 手動複製紀錄…附加於問題回報中,能協助我們更快排解問題
